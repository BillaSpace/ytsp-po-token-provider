# yt-search-python PO-token provider adapter

Standalone PO-token helper for `yt-search-python`. It is intentionally **not bundled into the main library**.

Requires Python 3.9+ and `httpx`.

It supports:

- persistent local `/get_pot` provider
- optional Node/Deno script fallback
- per-video/content-binding token cache
- provider `expiresAt` aware refresh
- maximum cache lifetime (24 hours by default)
- `cookies.txt`/Netscape session file handoff for authenticated stream requests
- sync and async APIs
- environment-variable configuration

It does **not** store or automate a Google email/password login. For authenticated YouTube sessions, export cookies and point the adapter/library at the cookie file instead.

## Install

```bash
python3 -m pip install 'httpx>=0.28.1,<1.0'
```

## Environment

```bash
export YTSP_POT_SERVER='http://127.0.0.1:4416'
export YTSP_COOKIES_FILE='/root/youtube-cookies.txt'   # optional
export YTSP_POT_CACHE_HOURS='24'                       # optional max TTL
export YTSP_POT_CACHE_FILE='~/.cache/ytsp-po-provider/tokens.json'
```

The provider's own `expiresAt` always wins when it expires sooner than the configured cache window. Tokens are cached by content binding, normally the video ID, so one video's token is never reused for another video.

## Sync

```python
from ytsp_po_provider import POTokenProvider
from youtubesearchpython import Video, StreamURLFetcher

video_id='pnxL4OOzPEc'
pot=POTokenProvider().get(video_id=video_id)

formats=Video.getFormats(video_id, **pot.video_kwargs())
stream=StreamURLFetcher(**pot.stream_kwargs()).get(video_id, 18)
print(stream)
```

## Async

```python
from ytsp_po_provider import POTokenProvider
from youtubesearchpython.future import Video, StreamURLFetcher

video_id='pnxL4OOzPEc'
pot=await POTokenProvider().aget(video_id=video_id)

formats=await Video.getFormats(video_id, **pot.video_kwargs())
stream=await StreamURLFetcher(**pot.stream_kwargs()).get(video_id, 18)
print(stream)
```

## Cookies/session support

Either pass the cookie path explicitly:

```python
provider=POTokenProvider(cookies_file='/root/youtube-cookies.txt')
pot=provider.get(video_id='pnxL4OOzPEc')
fetcher=StreamURLFetcher(**pot.stream_kwargs())
```

or set:

```bash
export YTSP_COOKIES_FILE='/root/youtube-cookies.txt'
```

`stream_kwargs()` includes `cookies_file` for `StreamURLFetcher`. `video_kwargs()` intentionally contains only the PO/visitor fields accepted by `Video.getFormats`.

## Automatic refresh/cache

Default maximum cache window is 24 hours, but `expiresAt` returned by the provider is respected and causes an earlier refresh. Use `bypass_cache=True` to force a fresh token:

```python
pot=POTokenProvider().get(video_id='pnxL4OOzPEc', bypass_cache=True)
```

Disable local caching entirely:

```bash
export YTSP_POT_CACHE_HOURS='0'
```

Clear cache:

```python
provider=POTokenProvider()
provider.clear_cache()                         # all
provider.clear_cache('pnxL4OOzPEc')           # one binding
```

The cache is stored atomically and the adapter attempts to keep it owner-readable only (`0600`). Do not share cookie files or token cache files publicly.

## Script fallback

```bash
export YTSP_POT_SCRIPT='/path/to/generate_once.js'
```

Node is preferred when available; Deno is supported as a fallback for compatible scripts.
