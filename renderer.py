"""Render a Threads post as a clean shareable PNG card."""

import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import Twemoji

from scraper import ThreadsPost


FONTS_DIR = Path(__file__).parent / "fonts"

CARD_WIDTH = 1080
PADDING = 80
AVATAR_SIZE = 96
AVATAR_GAP = 28
HEADER_TO_TEXT_GAP = 52
TEXT_TO_FOOTER_GAP = 64
MIN_HEIGHT = 520

BG_COLOR = (255, 255, 255)
TEXT_COLOR = (17, 17, 17)
MUTED_COLOR = (107, 107, 107)
BORDER_COLOR = (232, 232, 232)
AVATAR_FALLBACK_BG = (230, 230, 230)

NAME_SIZE = 40
HANDLE_SIZE = 28
BODY_SIZE = 46
FOOTER_SIZE = 26

BODY_LINE_HEIGHT = 1.35

IMAGE_RADIUS = 24
IMAGE_GAP = 16
TEXT_TO_IMAGES_GAP = 40
MAX_IMAGES = 4


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / f"Inter-{weight}.ttf"
    return ImageFont.truetype(str(path), size)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if font.getlength(candidate) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                if font.getlength(word) > max_width:
                    chunk = ""
                    for ch in word:
                        if font.getlength(chunk + ch) <= max_width:
                            chunk += ch
                        else:
                            lines.append(chunk)
                            chunk = ch
                    current = chunk
                else:
                    current = word
        if current:
            lines.append(current)
    return lines


def _download_image(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _download_avatar(url: str) -> Image.Image | None:
    img = _download_image(url)
    if img is None:
        return None
    img = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=255)
    circular = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    circular.paste(img, (0, 0), mask)
    return circular


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _compose_image_grid(urls: list[str], total_width: int) -> Image.Image | None:
    """Download up to MAX_IMAGES and lay them out as a grid fitting total_width.

    - 1 image: full width, cover-cropped to 4:3 max.
    - 2 images: side-by-side, 1:1.
    - 3+ images: 2x2 grid (4 cells), 1:1 each; 3rd image spans both cells if exactly 3.
    """
    imgs = [img for img in (_download_image(u) for u in urls[:MAX_IMAGES]) if img is not None]
    if not imgs:
        return None

    count = len(imgs)
    if count == 1:
        src = imgs[0]
        target_w = total_width
        target_h = int(target_w * min(src.height / src.width, 4 / 3))
        cell = _cover_crop(src, (target_w, target_h))
        canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        canvas.paste(cell, (0, 0), _rounded_mask((target_w, target_h), IMAGE_RADIUS))
        return canvas

    if count == 2:
        cell_w = (total_width - IMAGE_GAP) // 2
        cell_h = cell_w
        canvas = Image.new("RGBA", (total_width, cell_h), (0, 0, 0, 0))
        for i, src in enumerate(imgs):
            cell = _cover_crop(src, (cell_w, cell_h))
            x = i * (cell_w + IMAGE_GAP)
            canvas.paste(cell, (x, 0), _rounded_mask((cell_w, cell_h), IMAGE_RADIUS))
        return canvas

    # 3 or 4 images: 2x2 grid
    cell_w = (total_width - IMAGE_GAP) // 2
    cell_h = cell_w
    rows = 2
    total_h = rows * cell_h + IMAGE_GAP
    canvas = Image.new("RGBA", (total_width, total_h), (0, 0, 0, 0))
    positions = [(0, 0), (cell_w + IMAGE_GAP, 0), (0, cell_h + IMAGE_GAP), (cell_w + IMAGE_GAP, cell_h + IMAGE_GAP)]
    if count == 3:
        # first full-width top, remaining two bottom
        top = _cover_crop(imgs[0], (total_width, cell_h))
        canvas.paste(top, (0, 0), _rounded_mask((total_width, cell_h), IMAGE_RADIUS))
        for i, src in enumerate(imgs[1:3]):
            cell = _cover_crop(src, (cell_w, cell_h))
            x = i * (cell_w + IMAGE_GAP)
            canvas.paste(cell, (x, cell_h + IMAGE_GAP), _rounded_mask((cell_w, cell_h), IMAGE_RADIUS))
        return canvas

    for src, (x, y) in zip(imgs[:4], positions):
        cell = _cover_crop(src, (cell_w, cell_h))
        canvas.paste(cell, (x, y), _rounded_mask((cell_w, cell_h), IMAGE_RADIUS))
    return canvas


def _cover_crop(src: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_ratio = src.width / src.height
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / src_ratio)
    resized = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _fallback_avatar(initial: str) -> Image.Image:
    img = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=AVATAR_FALLBACK_BG)
    font = _font("SemiBold", 42)
    letter = (initial or "?")[0].upper()
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((AVATAR_SIZE - w) / 2 - bbox[0], (AVATAR_SIZE - h) / 2 - bbox[1]),
        letter,
        fill=(120, 120, 120),
        font=font,
    )
    return img


def render_card(post: ThreadsPost) -> bytes:
    body_font = _font("Regular", BODY_SIZE)
    name_font = _font("SemiBold", NAME_SIZE)
    handle_font = _font("Regular", HANDLE_SIZE)
    footer_font = _font("Regular", FOOTER_SIZE)

    content_width = CARD_WIDTH - PADDING * 2
    text_width = content_width

    body_lines = _wrap_text(post.text or "", body_font, text_width) if post.text else []
    line_step = int(BODY_SIZE * BODY_LINE_HEIGHT)
    body_height = max(line_step * len(body_lines), 0)

    header_height = AVATAR_SIZE
    footer_height = FOOTER_SIZE + 8

    image_grid = _compose_image_grid(post.image_urls or [], content_width)
    images_block_height = (image_grid.height + TEXT_TO_IMAGES_GAP) if image_grid else 0

    total_height = (
        PADDING
        + header_height
        + HEADER_TO_TEXT_GAP
        + body_height
        + images_block_height
        + TEXT_TO_FOOTER_GAP
        + footer_height
        + PADDING
    )
    total_height = max(total_height, MIN_HEIGHT)

    img = Image.new("RGB", (CARD_WIDTH, total_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Subtle outer border (inset 1px)
    draw.rectangle(
        (0, 0, CARD_WIDTH - 1, total_height - 1),
        outline=BORDER_COLOR,
        width=1,
    )

    # Header: avatar + name/handle
    avatar = _download_avatar(post.avatar_url) or _fallback_avatar(
        post.display_name or post.author
    )
    img.paste(avatar, (PADDING, PADDING), avatar)

    name_x = PADDING + AVATAR_SIZE + AVATAR_GAP
    name_y = PADDING + 8
    draw.text((name_x, name_y), post.display_name, fill=TEXT_COLOR, font=name_font)

    handle_y = name_y + NAME_SIZE + 6
    handle_text = f"@{post.author}" if post.author else ""
    if handle_text:
        draw.text((name_x, handle_y), handle_text, fill=MUTED_COLOR, font=handle_font)

    # Body text with emoji support
    body_y = PADDING + header_height + HEADER_TO_TEXT_GAP
    with Pilmoji(img, source=Twemoji) as pilmoji:
        for i, line in enumerate(body_lines):
            pilmoji.text(
                (PADDING, body_y + i * line_step),
                line,
                fill=TEXT_COLOR,
                font=body_font,
                emoji_scale_factor=1.0,
                emoji_position_offset=(0, int(BODY_SIZE * 0.08)),
            )

    # Post images (if any)
    if image_grid:
        images_y = body_y + body_height + TEXT_TO_IMAGES_GAP
        img.paste(image_grid, (PADDING, images_y), image_grid)

    # Footer
    footer_y = total_height - PADDING - FOOTER_SIZE
    footer_text = f"threads.com/@{post.author}" if post.author else "threads.com"
    draw.text((PADDING, footer_y), footer_text, fill=MUTED_COLOR, font=footer_font)

    # Threads wordmark on the right
    brand_font = _font("SemiBold", FOOTER_SIZE)
    brand_text = "Threads"
    brand_w = draw.textlength(brand_text, font=brand_font)
    draw.text(
        (CARD_WIDTH - PADDING - brand_w, footer_y),
        brand_text,
        fill=TEXT_COLOR,
        font=brand_font,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
