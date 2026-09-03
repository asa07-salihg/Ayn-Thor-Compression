"""The only place this app opens a network connection.

Why
    Two things reach the internet: the tool installer and the updater. Both
    fetch executables that are then run on the user's machine, so both need the
    same guarantees, and having one implementation is the only way to be sure
    they have them.

    What it enforces, and why each one is here rather than left to the default:

    * **HTTPS, including after a redirect.** urllib follows redirects happily
      and will follow one from https to http, at which point the download is
      whatever the network decided to hand back. A redirect that leaves HTTPS
      is refused.
    * **Certificate verification, explicitly.** It is the default, and stating
      it means a later refactor cannot quietly turn it off.
    * **A size cap.** A hostile or broken server can otherwise stream until the
      disk fills. Nothing here is larger than a few hundred megabytes.
    * **A timeout on every request.** Without one a stalled connection hangs
      the thread it is on for as long as the socket stays open.

    None of this replaces the checksums. Transport security says the bytes
    arrived unmodified from the host; the checksums in `core.tools.manifest`
    say they are the bytes we expected, which is the stronger claim and the one
    that matters if a release asset is ever replaced upstream.

    It uses urllib rather than requests so the application has one HTTP stack
    and one fewer dependency to keep current.

Used by
    `core.tools.manager` (downloading tools), `core.updates` (checking for and
    downloading a new build), `core.tools.versions` (reading upstream tags).

Reference
    https://docs.python.org/3/library/urllib.request.html
    https://docs.python.org/3/library/ssl.html#ssl-security
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aynthor import PROJECT_URL, __version__

# GitHub rejects requests with no user agent, and a request that says who it is
# is easier for a project to see in its own logs than an anonymous one.
USER_AGENT = f"AynThorCompression/{__version__} (+{PROJECT_URL})"

DEFAULT_TIMEOUT = 30
_CHUNK = 256 * 1024

# Nothing this app downloads is anywhere near this. It exists so a server that
# never stops sending cannot fill the disk.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


class NetworkError(RuntimeError):
    """A request that failed for a reason worth showing the user verbatim.

    `status` is the HTTP status when the server answered and the answer was the
    problem, and None when the request never got that far. Callers use it to say
    something more useful than the status line: `core.tools.versions` turns a
    403 from GitHub into an explanation of the hourly rate limit rather than
    leaving the user to guess what was forbidden.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never off HTTPS.

    Release assets on GitHub redirect to a CDN, so redirects have to be
    followed. A redirect to http would hand the rest of the download to
    whatever is on the network path.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise NetworkError(
                f"Refused a redirect that leaves HTTPS: {newurl.split('://')[0]}://...")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # create_default_context verifies certificates and checks the hostname.
    # Both are the default; saying so keeps them from being dropped by accident.
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _HttpsOnlyRedirects(),
    )


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    if not url.lower().startswith("https://"):
        raise NetworkError(f"Refusing a URL that is not HTTPS: {url}")
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def _describe(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"{exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return str(exc)


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET a small JSON document. Raises NetworkError on any failure."""
    try:
        with _opener().open(_request(url, "application/json"), timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024)
        return json.loads(body.decode("utf-8"))
    except NetworkError:
        raise
    except urllib.error.HTTPError as exc:
        raise NetworkError(f"{url} returned {exc.code} {exc.reason}.", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(f"Could not reach {url}: {_describe(exc)}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise NetworkError(f"{url} did not return readable JSON: {exc}") from exc


def download(
    url: str,
    destination: Path,
    on_progress: Callable[[int], None] | None = None,
    *,
    expected_size: int = 0,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Stream a URL to a file. Removes a partial file if anything goes wrong.

    `expected_size` only drives the progress callback; the size that is
    enforced is `max_bytes`. A partial download is deleted rather than left
    behind, because a truncated executable that looks present is worse than one
    that is missing.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with _opener().open(_request(url), timeout=timeout) as response, \
                destination.open("wb") as handle:
            declared = expected_size or int(response.headers.get("Content-Length") or 0)
            if declared and declared > max_bytes:
                raise NetworkError(
                    f"{url} says it is {declared / 1e6:.0f} MB, over the "
                    f"{max_bytes / 1e6:.0f} MB limit.")

            last_percent = -1
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise NetworkError(
                        f"{url} sent more than the {max_bytes / 1e6:.0f} MB limit.")
                handle.write(chunk)
                if on_progress and declared:
                    percent = min(99, int(written * 100 / declared))
                    if percent != last_percent:
                        last_percent = percent
                        on_progress(percent)
    except NetworkError:
        destination.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise NetworkError(f"{url} returned {exc.code} {exc.reason}.", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise NetworkError(f"Download failed: {_describe(exc)}") from exc

    if written == 0:
        destination.unlink(missing_ok=True)
        raise NetworkError(f"{url} returned an empty file.")
    if on_progress:
        on_progress(100)
    return destination
