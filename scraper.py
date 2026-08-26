"""Fetch Threads post data by scraping the public page as Googlebot."""

import html as html_module
import json
import re
from dataclasses import dataclass

import httpx


GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


@dataclass
class ThreadsPost:
    url: str
    author: str
    display_name: str
    text: str
    avatar_url: str
    image_urls: list[str]


class ThreadsFetchError(Exception):
    pass


async def fetch_threads_post(url: str) -> ThreadsPost:
    if "threads.com" not in url and "threads.net" not in url:
        raise ThreadsFetchError("Not a Threads URL")

    author_match = re.search(r"/@([^/?]+)", url)
    author = author_match.group(1) if author_match else ""

    code_match = re.search(r"/post/([A-Za-z0-9_-]+)", url)
    post_code = code_match.group(1) if code_match else ""

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": GOOGLEBOT_UA})
        if resp.status_code != 200:
            raise ThreadsFetchError(f"Threads returned {resp.status_code}")
        final_url = str(resp.url)
        if "error=invalid_post" in final_url or "/login" in final_url:
            raise ThreadsFetchError("Post not accessible (deleted, private, or login-gated)")
        html = resp.text

    if post_code and f'"code":"{post_code}"' not in html:
        raise ThreadsFetchError("Post not found on Threads (may be deleted or private)")

    text = _extract_post_text(html, post_code)
    display_name = _extract_display_name(html)
    avatar_url = _extract_avatar_url(html, post_code)
    image_urls = _extract_post_images(html, post_code)

    return ThreadsPost(
        url=url,
        author=author,
        display_name=display_name or author,
        text=text,
        avatar_url=avatar_url,
        image_urls=image_urls,
    )


def _extract_post_text(html: str, post_code: str) -> str:
    """Extract post text by locating the target post and parsing its text_fragments.

    Falls back to caption.text near the target post, then to a loose regex.
    """
    fragments = _find_text_fragments_near_code(html, post_code)
    if fragments:
        return "".join(f.get("plaintext", "") for f in fragments)

    caption = _find_caption_text_near_code(html, post_code)
    if caption:
        return caption

    # Last resort: longest "text":"..." match
    matches = re.findall(r'"text":"((?:[^"\\]|\\.)*)"', html)
    if matches:
        return _unescape_json(max(matches, key=len))
    return ""


def _find_text_fragments_near_code(html: str, post_code: str) -> list[dict] | None:
    if not post_code:
        return None
    marker = f'"code":"{post_code}"'
    idx = html.find(marker)
    if idx == -1:
        return None
    window_start = max(0, idx - 40000)
    window = html[window_start:idx]
    frag_start = window.rfind('"text_fragments":{"fragments":[')
    if frag_start == -1:
        return None
    array_start = window.find("[", frag_start)
    array_end = _find_matching_bracket(window, array_start)
    if array_end == -1:
        return None
    try:
        return json.loads(window[array_start:array_end + 1])
    except json.JSONDecodeError:
        return None


def _find_caption_text_near_code(html: str, post_code: str) -> str | None:
    if not post_code:
        return None
    marker = f'"code":"{post_code}"'
    idx = html.find(marker)
    if idx == -1:
        return None
    window_start = max(0, idx - 40000)
    window = html[window_start:idx]
    cap_start = window.rfind('"caption":{"text":"')
    if cap_start == -1:
        return None
    text_start = cap_start + len('"caption":{"text":"')
    # Find the closing quote, respecting escapes
    i = text_start
    while i < len(window):
        if window[i] == "\\":
            i += 2
            continue
        if window[i] == '"':
            break
        i += 1
    return _unescape_json(window[text_start:i])


def _find_matching_bracket(s: str, start: int) -> int:
    """Find the index of the `]` matching the `[` at `start`, respecting strings/escapes."""
    if start < 0 or start >= len(s) or s[start] != "[":
        return -1
    depth = 0
    in_string = False
    i = start
    while i < len(s):
        c = s[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _extract_display_name(html: str) -> str:
    match = re.search(r'og:title["\']?\s*content=["\']([^"\']*)["\']', html)
    if not match:
        return ""
    raw = html_module.unescape(match.group(1))
    if raw.strip().lower().startswith("threads"):
        return ""
    paren = re.search(r"^(.+?)\s*\(", raw)
    return paren.group(1).strip() if paren else raw.strip()


def _extract_avatar_url(html: str, post_code: str) -> str:
    if post_code:
        marker = f'"code":"{post_code}"'
        idx = html.find(marker)
        if idx != -1:
            window = html[max(0, idx - 40000):idx]
            for pattern in (
                r'"profile_pic_url":"([^"]+)"',
                r'"profile_picture_url":"([^"]+)"',
            ):
                matches = re.findall(pattern, window)
                if matches:
                    return _unescape_json(matches[-1])
    for pattern in (
        r'"profile_pic_url":"([^"]+)"',
        r'"profile_picture_url":"([^"]+)"',
        r'og:image["\']?\s*content=["\']([^"\']+)["\']',
    ):
        match = re.search(pattern, html)
        if match:
            return _unescape_json(match.group(1))
    return ""


def _extract_post_images(html: str, post_code: str) -> list[str]:
    """Find attached post media (t51.82787-15 is post images; -19 is profile pics).

    Scopes to a window around the target post code and dedupes by CDN asset id.
    """
    if not post_code:
        return []
    marker = f'"code":"{post_code}"'
    idx = html.find(marker)
    if idx == -1:
        return []
    window = html[max(0, idx - 5000):idx + 200000]
    raw = re.findall(r'"url":"(https:\\/\\/[^"]*t51\.82787-15[^"]+)"', window)
    seen: set[str] = set()
    urls: list[str] = []
    for u in raw:
        decoded = _unescape_json(u)
        key_match = re.search(r"t51\.82787-15/([^/?]+)", decoded)
        key = key_match.group(1) if key_match else decoded[:80]
        if key in seen:
            continue
        seen.add(key)
        urls.append(decoded)
    return urls


def _unescape_json(s: str) -> str:
    s = (
        s.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\/", "/")
        .replace("\\\\", "\\")
    )
    out = []
    i = 0
    while i < len(s):
        if s[i:i + 2] == "\\u" and i + 5 < len(s):
            hex_str = s[i + 2:i + 6]
            if all(c in "0123456789abcdefABCDEF" for c in hex_str):
                code = int(hex_str, 16)
                if 0xD800 <= code <= 0xDBFF and s[i + 6:i + 8] == "\\u":
                    low_hex = s[i + 8:i + 12]
                    if all(c in "0123456789abcdefABCDEF" for c in low_hex):
                        low = int(low_hex, 16)
                        if 0xDC00 <= low <= 0xDFFF:
                            out.append(chr(0x10000 + (code - 0xD800) * 0x400 + (low - 0xDC00)))
                            i += 12
                            continue
                if 0xD800 <= code <= 0xDFFF:
                    i += 6
                    continue
                out.append(chr(code))
                i += 6
                continue
        out.append(s[i])
        i += 1
    return "".join(out)
