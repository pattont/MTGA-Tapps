"""Local validation/normalization of configurable YouTube channel references."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def channel_videos_url(reference: str) -> str:
    reference = reference.strip()
    if reference.startswith("@"):
        reference = "https://www.youtube.com/" + reference
    elif re.fullmatch(r"UC[A-Za-z0-9_-]{22}", reference):
        reference = "https://www.youtube.com/channel/" + reference
    elif reference.startswith(("www.youtube.com/", "youtube.com/")):
        reference = "https://" + reference
    parsed = urlparse(reference)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() not in {"youtube.com", "www.youtube.com"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a YouTube @handle or an https://www.youtube.com/channel/… URL.")
    path = parsed.path.rstrip("/")
    if path.endswith("/videos"):
        path = path[:-7]
    if not (
        re.fullmatch(r"/@[\w.\-\u0080-\uffff]+", path)
        or re.fullmatch(r"/channel/UC[A-Za-z0-9_-]{22}", path)
    ):
        raise ValueError("Use a YouTube channel URL or @handle, rather than a video/playlist URL.")
    return "https://www.youtube.com" + path + "/videos"
