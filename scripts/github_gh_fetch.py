"""Pure ``gh api`` Fetch adapter for the live reconcile capture (#402).

OC-P0-01: ``reconcile_live`` (#397) takes an injected ``Fetch``
(``fetch(path) -> Response(status, body, link)``) but nothing produced one, so each
runner would hand-roll status and ``Link`` parsing. This module builds that ``Fetch``
from an injected ``runner(argv) -> (returncode, stdout_text)``.

Rules, all fail closed:

* GET only: the argv is one fixed ``gh api -i -X GET`` command plus the validated path;
* the path must be an absolute ``/repos/<owner>/<repo>/...`` API path with no scheme,
  host, fragment, ``.``/``..`` segment, empty segment or character outside a small
  allow-list, so a caller cannot point a credentialed ``gh`` elsewhere;
* output is bounded by ``max_bytes``; a runner exception, oversize output, a malformed
  header block, a duplicate ``Link`` header, a non-zero exit with a 200 status or a 200
  body that is not JSON raises ``CaptureError`` with a fixed message, never response
  content;
* non-200 statuses are returned as ``Response(status, None, None)`` so that
  ``collect_pages`` refuses them naming status and page only.

Nothing here reads a token, an environment variable or the clock, and no request is
made unless the injected runner makes one.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from github_page_capture import CaptureError, Fetch, Response

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
Runner = Callable[[list[str]], "tuple[int, str]"]

_PATH = re.compile(
    r"/repos/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}(?:/[A-Za-z0-9_.%~-]+)*"
    r"(?:\?[A-Za-z0-9_.%~=&,+:-]*)?")
_STATUS = re.compile(r"HTTP/\d(?:\.\d)? (\d{3})(?: [^\r\n]*)?")
_HEADER = re.compile(r"([!#$%&'*+.^_`|~0-9A-Za-z-]+):[ \t]*([^\r\n]*)")
_BLANK = re.compile(r"\r?\n\r?\n")
_ARGV = ["gh", "api", "-i", "-X", "GET", "-H", "Accept: application/vnd.github+json"]


def _checked_path(path: object) -> str:
    if type(path) is not str or not _PATH.fullmatch(path):
        raise CaptureError("invalid path")
    segments = path.split("?", 1)[0].split("/")[1:]
    if any(segment in ("", ".", "..") for segment in segments):
        raise CaptureError("invalid path")
    return path


def make_gh_fetch(runner: Runner, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Fetch:
    """Return a ``Fetch`` that serves GET requests through ``runner``."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise CaptureError("invalid max_bytes")

    def fetch(path: str) -> Response:
        argv = [*_ARGV, _checked_path(path)]
        try:
            result = runner(argv)
            code, out = result
        except (OSError, TimeoutError, TypeError, ValueError):
            raise CaptureError("transport failed") from None
        if type(code) is not int or type(out) is not str:
            raise CaptureError("transport failed")
        if len(out.encode("utf-8", "replace")) > max_bytes:
            raise CaptureError("response too large")
        split = _BLANK.search(out)
        head, body = (out[:split.start()], out[split.end():]) if split else (out, "")
        lines = head.splitlines()
        match = _STATUS.fullmatch(lines[0]) if lines else None
        if match is None:
            raise CaptureError("malformed response")
        status = int(match.group(1))
        links: list[str] = []
        for line in lines[1:]:
            header = _HEADER.fullmatch(line)
            if header is None:
                raise CaptureError("malformed response")
            if header.group(1).lower() == "link":
                links.append(header.group(2))
        if status != 200:
            return Response(status, None, None)
        if code != 0 or split is None or len(links) > 1:
            raise CaptureError("malformed response")
        try:
            decoded = json.loads(body)
        except ValueError:
            raise CaptureError("malformed body") from None
        return Response(status, decoded, links[0] if links else None)

    return fetch
