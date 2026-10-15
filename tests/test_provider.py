from pathlib import Path
from unittest.mock import Mock

from ytsp_po_provider import POToken, POTokenProvider, _parse_expiry


def test_import_and_token_kwargs():
    token = POToken(
        token="test-token",
        visitor_data="test-visitor",
        cookies_file="/tmp/cookies.txt",
    )

    assert token.video_kwargs() == {
        "po_token": "test-token",
        "visitor_data": "test-visitor",
    }

    assert token.stream_kwargs() == {
        "po_token": "test-token",
        "visitor_data": "test-visitor",
        "cookies_file": "/tmp/cookies.txt",
    }


def test_provider_initializes(tmp_path):
    provider = POTokenProvider(
        cache_file=str(tmp_path / "tokens.json"),
        max_cache_hours=24,
    )

    assert provider.max_cache_hours == 24
    assert provider.cache_file == tmp_path / "tokens.json"
    assert provider.base_url is None
    assert Path(provider.script_path).name == "engine.js"


def test_expiry_parser():
    assert _parse_expiry(None) is None
    assert _parse_expiry("invalid") is None
    assert _parse_expiry(1700000000) == 1700000000


def test_bundled_engine_plain_token_output(monkeypatch, tmp_path):
    provider = POTokenProvider(cache_file=str(tmp_path / "tokens.json"))
    process = Mock(returncode=0, stdout="generated-token\n", stderr="")
    monkeypatch.setattr("ytsp_po_provider.provider.subprocess.run", lambda *args, **kwargs: process)
    monkeypatch.setattr(provider, "_runtime", lambda node_only=False: "/usr/bin/node")

    token = provider.get(video_id="dQw4w9WgXcQ", bypass_cache=True)

    assert token.token == "generated-token"
    assert token.content_binding == "dQw4w9WgXcQ"


def test_configured_server_falls_back_to_local_engine(monkeypatch, tmp_path):
    provider = POTokenProvider(base_url="http://127.0.0.1:1", cache_file=str(tmp_path / "tokens.json"))
    monkeypatch.setattr(provider, "_http", Mock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(provider, "_script", Mock(return_value=POToken("local", "video")))

    assert provider.get(video_id="video", bypass_cache=True).token == "local"
