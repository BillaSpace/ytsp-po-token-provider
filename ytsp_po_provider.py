import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx


def _env(name: str, default=None):
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _parse_expiry(value) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000.0 if value > 10_000_000_000 else value
    text = str(value).strip()
    try:
        number = float(text)
        return number / 1000.0 if number > 10_000_000_000 else number
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class POToken:
    token: str
    content_binding: Optional[str] = None
    expires_at: Optional[str] = None
    visitor_data: Optional[str] = None
    cookies_file: Optional[str] = None

    def video_kwargs(self) -> dict:
        data = {"po_token": self.token}
        if self.visitor_data:
            data["visitor_data"] = self.visitor_data
        return data

    def stream_kwargs(self) -> dict:
        data = self.video_kwargs()
        if self.cookies_file:
            data["cookies_file"] = self.cookies_file
        return data


class POTokenProvider:
    def __init__(
        self,
        base_url: str = None,
        script_path: str = None,
        timeout: float = 20,
        proxy: str = None,
        cookies_file: str = None,
        cache_file: str = None,
        max_cache_hours: float = None,
        refresh_margin: float = 300,
    ):
        self.base_url = (base_url or _env("YTSP_POT_SERVER", "http://127.0.0.1:4416")).rstrip("/")
        self.script_path = script_path or _env("YTSP_POT_SCRIPT")
        self.timeout = float(timeout)
        self.proxy = proxy or _env("YTSP_PROXY")
        self.cookies_file = cookies_file or _env("YTSP_COOKIES_FILE") or _env("YT_COOKIES_FILE")
        self.cache_file = Path(cache_file or _env("YTSP_POT_CACHE_FILE", str(Path.home() / ".cache" / "ytsp-po-provider" / "tokens.json"))).expanduser()
        self.max_cache_hours = float(max_cache_hours if max_cache_hours is not None else _env("YTSP_POT_CACHE_HOURS", "24"))
        self.refresh_margin = max(0.0, float(refresh_margin))
        self._lock = threading.RLock()
        self._validate_cookies()

    def _validate_cookies(self):
        if self.cookies_file:
            path = Path(self.cookies_file).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Cookies file not found: {path}")
            self.cookies_file = str(path.resolve())

    def _cache_key(self, binding: str) -> str:
        return str(binding or "guest")

    def _load_cache(self) -> dict:
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, data: dict):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".tokens-", suffix=".json", dir=str(self.cache_file.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, self.cache_file)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass

    def _cached(self, binding: str) -> Optional[POToken]:
        if self.max_cache_hours <= 0:
            return None
        now = time.time()
        with self._lock:
            entry = self._load_cache().get(self._cache_key(binding))
        if not isinstance(entry, dict) or not entry.get("token"):
            return None
        cached_at = float(entry.get("cached_at") or 0)
        fallback_expiry = cached_at + self.max_cache_hours * 3600
        provider_expiry = _parse_expiry(entry.get("expires_at"))
        expiry = min(fallback_expiry, provider_expiry) if provider_expiry else fallback_expiry
        if now + self.refresh_margin >= expiry:
            return None
        return POToken(
            token=entry["token"],
            content_binding=entry.get("content_binding"),
            expires_at=entry.get("expires_at"),
            visitor_data=entry.get("visitor_data"),
            cookies_file=self.cookies_file,
        )

    def _store(self, binding: str, token: POToken):
        if self.max_cache_hours <= 0:
            return
        with self._lock:
            data = self._load_cache()
            item = asdict(token)
            item.pop("cookies_file", None)
            item["cached_at"] = time.time()
            data[self._cache_key(binding)] = item
            self._save_cache(data)

    @staticmethod
    def _result(data: dict, cookies_file: str = None) -> POToken:
        token = data.get("poToken") or data.get("po_token") or data.get("token")
        if not token:
            raise RuntimeError(f"PO-token provider returned no token: {data}")
        return POToken(
            token=token,
            content_binding=data.get("contentBinding") or data.get("content_binding"),
            expires_at=data.get("expiresAt") or data.get("expires_at"),
            visitor_data=data.get("visitorData") or data.get("visitor_data"),
            cookies_file=cookies_file,
        )

    def _payload(self, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> dict:
        payload = {"content_binding": content_binding, "bypass_cache": bool(bypass_cache)}
        if self.proxy:
            payload["proxy"] = self.proxy
        if innertube_context:
            payload["innertube_context"] = innertube_context
        return payload

    def _http(self, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> POToken:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/get_pot", json=self._payload(content_binding, innertube_context, bypass_cache))
            response.raise_for_status()
            return self._result(response.json(), self.cookies_file)

    def _script(self, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> POToken:
        if not self.script_path:
            raise RuntimeError("No PO-token generation script configured")
        runtime = shutil.which("node") or shutil.which("deno")
        if not runtime:
            raise RuntimeError("Neither node nor deno is available")
        args = [runtime, self.script_path] if os.path.basename(runtime).startswith("node") else [runtime, "run", "--allow-env", "--allow-net", "--allow-read", self.script_path]
        if content_binding:
            args += ["--content-binding", content_binding]
        if self.proxy:
            args += ["--proxy", self.proxy]
        if bypass_cache:
            args.append("--bypass-cache")
        if innertube_context:
            args += ["--innertube-context", json.dumps(innertube_context, separators=(",", ":"))]
        process = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout, check=False)
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                return self._result(json.loads(line), self.cookies_file)
            except (json.JSONDecodeError, RuntimeError):
                continue
        raise RuntimeError(process.stderr.strip() or "PO-token generation failed")

    async def _ahttp(self, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> POToken:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/get_pot", json=self._payload(content_binding, innertube_context, bypass_cache))
            response.raise_for_status()
            return self._result(response.json(), self.cookies_file)

    def get(self, video_id: str = None, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> POToken:
        binding = content_binding or video_id or _env("YTSP_CONTENT_BINDING")
        if not binding:
            raise ValueError("video_id or content_binding is required")
        if not bypass_cache:
            cached = self._cached(binding)
            if cached:
                return cached
        try:
            token = self._http(binding, innertube_context, bypass_cache)
        except Exception as server_error:
            if not self.script_path:
                raise RuntimeError(f"PO-token server unavailable: {server_error}") from server_error
            token = self._script(binding, innertube_context, bypass_cache)
        self._store(binding, token)
        return token

    async def aget(self, video_id: str = None, content_binding: str = None, innertube_context: dict = None, bypass_cache: bool = False) -> POToken:
        binding = content_binding or video_id or _env("YTSP_CONTENT_BINDING")
        if not binding:
            raise ValueError("video_id or content_binding is required")
        if not bypass_cache:
            cached = await asyncio.to_thread(self._cached, binding)
            if cached:
                return cached
        try:
            token = await self._ahttp(binding, innertube_context, bypass_cache)
        except Exception as server_error:
            if not self.script_path:
                raise RuntimeError(f"PO-token server unavailable: {server_error}") from server_error
            token = await asyncio.to_thread(self._script, binding, innertube_context, bypass_cache)
        await asyncio.to_thread(self._store, binding, token)
        return token

    def clear_cache(self, content_binding: str = None):
        with self._lock:
            if content_binding is None:
                try:
                    self.cache_file.unlink()
                except FileNotFoundError:
                    pass
                return
            data = self._load_cache()
            data.pop(self._cache_key(content_binding), None)
            self._save_cache(data)
