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


def test_expiry_parser():
    assert _parse_expiry(None) is None
    assert _parse_expiry("invalid") is None
    assert _parse_expiry(1700000000) == 1700000000
