"""The rules every download in this app goes through.

This is the code that fetches executables which are then run on the user's
machine. Transport is the weaker half of the guarantee (the checksums in the
tool manifest are the stronger half), but it is the half that decides whether
the bytes came from the host we asked, so each rule is tested here.

No test opens a socket: the opener is replaced with a fake, which is what lets
these run in CI with no network and no server.
"""

from __future__ import annotations

import io
import urllib.error

import pytest

from aynthor.core import net


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, headers: dict | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    def __init__(self, response) -> None:
        self._response = response
        self.requested: list[str] = []

    def open(self, request, timeout=None):
        self.requested.append(request.full_url)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture()
def serve(monkeypatch):
    def _serve(payload: bytes | Exception, headers: dict | None = None) -> FakeOpener:
        response = payload if isinstance(payload, Exception) else FakeResponse(payload, headers)
        opener = FakeOpener(response)
        monkeypatch.setattr(net, "_opener", lambda: opener)
        return opener

    return _serve


# ------------------------------------------------------------------- https

@pytest.mark.parametrize("url", [
    "http://example.invalid/tool.exe",
    "ftp://example.invalid/tool.exe",
    "file:///etc/passwd",
    "HTTP://example.invalid/tool.exe",
])
def test_a_url_that_is_not_https_is_refused_before_connecting(url, tmp_path):
    with pytest.raises(net.NetworkError, match="not HTTPS"):
        net.download(url, tmp_path / "out.bin")


def test_a_redirect_that_leaves_https_is_refused():
    """GitHub redirects release assets to a CDN, so redirects must be followed;
    one that drops to http would hand the rest of the download to the network."""
    handler = net._HttpsOnlyRedirects()
    with pytest.raises(net.NetworkError, match="leaves HTTPS"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://elsewhere.invalid/x")


def test_a_redirect_that_stays_on_https_is_allowed(monkeypatch):
    handler = net._HttpsOnlyRedirects()
    seen = {}

    def parent(fp, code, msg, headers, newurl):
        seen["url"] = newurl
        return "request"

    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, "redirect_request",
                        lambda self, req, fp, code, msg, headers, newurl: parent(
                            fp, code, msg, headers, newurl))
    handler.redirect_request(None, None, 302, "Found", {}, "https://cdn.invalid/x")
    assert seen["url"] == "https://cdn.invalid/x"


def test_certificates_are_verified():
    """It is the default; asserting it stops a refactor from turning it off."""
    import ssl

    context = ssl.create_default_context()
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED


def test_the_user_agent_says_who_is_asking():
    assert "AynThorCompression" in net.USER_AGENT
    assert net.USER_AGENT.startswith("AynThorCompression/")


# -------------------------------------------------------------- size limits

def test_a_download_larger_than_the_cap_is_refused(serve, tmp_path):
    serve(b"x" * 2048, headers={})  # no Content-Length, so it streams past the cap
    with pytest.raises(net.NetworkError, match="limit"):
        net.download("https://example.invalid/big", tmp_path / "out.bin", max_bytes=1024)


def test_a_declared_size_over_the_cap_is_refused_before_reading(serve, tmp_path):
    serve(b"x" * 10, headers={"Content-Length": str(10 * 1024 * 1024)})
    with pytest.raises(net.NetworkError, match="over the"):
        net.download("https://example.invalid/big", tmp_path / "out.bin", max_bytes=1024)


def test_a_refused_download_leaves_no_partial_file(serve, tmp_path):
    """A truncated executable that looks present is worse than a missing one."""
    serve(b"x" * 4096, headers={})
    target = tmp_path / "out.bin"
    with pytest.raises(net.NetworkError):
        net.download("https://example.invalid/big", target, max_bytes=512)
    assert not target.exists()


def test_an_empty_response_is_an_error(serve, tmp_path):
    serve(b"")
    with pytest.raises(net.NetworkError, match="empty"):
        net.download("https://example.invalid/nothing", tmp_path / "out.bin")


def test_a_failed_download_leaves_no_partial_file(serve, tmp_path):
    serve(urllib.error.URLError("connection reset"))
    target = tmp_path / "out.bin"
    with pytest.raises(net.NetworkError, match="Download failed"):
        net.download("https://example.invalid/x", target)
    assert not target.exists()


# ---------------------------------------------------------------- behaviour

def test_a_download_writes_exactly_what_was_sent(serve, tmp_path):
    payload = bytes(range(256)) * 40
    serve(payload)
    written = net.download("https://example.invalid/tool.exe", tmp_path / "tool.exe")
    assert written.read_bytes() == payload


def test_progress_is_reported_and_ends_at_100(serve, tmp_path):
    serve(b"y" * (600 * 1024))
    seen: list[int] = []
    net.download("https://example.invalid/x", tmp_path / "x.bin", seen.append)
    assert seen[-1] == 100
    assert all(0 <= value <= 100 for value in seen)


def test_the_parent_directory_is_created(serve, tmp_path):
    serve(b"data")
    target = tmp_path / "nested" / "deeper" / "x.bin"
    net.download("https://example.invalid/x", target)
    assert target.is_file()


def test_json_is_parsed(serve):
    serve(b'{"tag_name": "v2.0.0"}')
    assert net.fetch_json("https://example.invalid/api")["tag_name"] == "v2.0.0"


def test_json_that_is_not_json_is_an_error(serve):
    serve(b"<html>rate limited</html>")
    with pytest.raises(net.NetworkError, match="readable JSON"):
        net.fetch_json("https://example.invalid/api")


def test_an_http_error_carries_its_status(serve):
    """The number, not only the sentence: `core.tools.versions` reads it to tell
    a rate limit apart from a repository that has moved."""
    serve(urllib.error.HTTPError("https://example.invalid/api", 404, "Not Found", {}, None))
    with pytest.raises(net.NetworkError, match="404") as caught:
        net.fetch_json("https://example.invalid/api")
    assert caught.value.status == 404


def test_a_failed_download_carries_its_status_too(serve, tmp_path):
    serve(urllib.error.HTTPError("https://example.invalid/x", 403, "Forbidden", {}, None))
    with pytest.raises(net.NetworkError) as caught:
        net.download("https://example.invalid/x", tmp_path / "out.bin")
    assert caught.value.status == 403
    assert not (tmp_path / "out.bin").exists()


def test_an_error_that_never_reached_a_server_has_no_status():
    assert net.NetworkError("offline").status is None


def test_fetch_json_also_refuses_plain_http():
    with pytest.raises(net.NetworkError, match="not HTTPS"):
        net.fetch_json("http://example.invalid/api")


def test_the_default_cap_is_generous_but_finite():
    assert 100 * 1024 * 1024 < net.MAX_DOWNLOAD_BYTES < 2 * 1024 * 1024 * 1024
