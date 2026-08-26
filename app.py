"""Threads card service — converts a Threads URL into a shareable PNG."""

import html as html_module
import os
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from renderer import render_card
from scraper import ThreadsFetchError, fetch_threads_post


app = FastAPI(title="Threads Card")


async def _render_card_response(url: str) -> Response:
    try:
        post = await fetch_threads_post(url)
    except ThreadsFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not post.text and not post.display_name:
        raise HTTPException(status_code=422, detail="Could not extract post content")

    png = render_card(post)
    label = f"@{post.author} on Threads" if post.author else "Threads"
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="{label}"',
        },
    )


@app.get("/")
async def root(url: str | None = Query(default=None)):
    if url:
        return await _render_card_response(url)
    return JSONResponse(
        {
            "service": "threads-card",
            "usage": "/?url=https://www.threads.com/@user/post/abc123",
        }
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/meta")
async def meta(url: str = Query(...)):
    try:
        post = await fetch_threads_post(url)
    except ThreadsFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "author": post.author,
        "display_name": post.display_name,
        "text": post.text,
        "avatar_url": post.avatar_url,
    }


@app.get("/card")
@app.get("/card.png")
async def card(url: str = Query(..., description="Threads post URL")):
    return await _render_card_response(url)


@app.get("/s")
async def share_page(request: Request, url: str = Query(..., description="Threads post URL")):
    """HTML share page with og tags for iMessage link preview.

    Preview image = the card PNG. Body shows the card + a link to Threads source.
    """
    try:
        post = await fetch_threads_post(url)
    except ThreadsFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = str(request.base_url).rstrip("/")
    card_url = f"{base}/?url={quote(url, safe='')}"

    title = post.display_name or (f"@{post.author}" if post.author else "Threads")
    desc = (post.text or "").strip()
    if len(desc) > 200:
        desc = desc[:197] + "…"

    e_title = html_module.escape(title)
    e_desc = html_module.escape(desc)
    e_card = html_module.escape(card_url)
    e_url = html_module.escape(url)
    e_handle = html_module.escape(f"@{post.author}" if post.author else "")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e_title} on Threads</title>
<meta property="og:type" content="article">
<meta property="og:title" content="{e_title}">
<meta property="og:description" content="{e_desc}">
<meta property="og:image" content="{e_card}">
<meta property="og:image:width" content="1080">
<meta property="og:url" content="{e_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e_title}">
<meta name="twitter:description" content="{e_desc}">
<meta name="twitter:image" content="{e_card}">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #fafafa; margin: 0; padding: 24px; color: #111; }}
  main {{ max-width: 640px; margin: 0 auto; }}
  img.card {{ width: 100%; height: auto; border-radius: 16px; display: block; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  .source {{ margin-top: 20px; text-align: center; }}
  .source a {{ display: inline-block; padding: 12px 20px; background: #111; color: #fff; border-radius: 999px; text-decoration: none; font-weight: 600; }}
  .handle {{ text-align: center; color: #666; font-size: 14px; margin-top: 12px; }}
</style>
</head>
<body>
<main>
  <img class="card" src="{e_card}" alt="{e_title} on Threads">
  <div class="source"><a href="{e_url}">View on Threads</a></div>
  <div class="handle">{e_handle}</div>
</main>
</body>
</html>
"""
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "public, max-age=3600"},
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
