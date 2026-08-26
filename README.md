# threads-card

Tiny HTTP service that turns a Threads post URL into a clean shareable PNG card.

## Why

Friends without Threads accounts can't open links you share — they get bounced to a login wall. This generates a standalone image of the post so you can share the content + link.

## API

```
GET /?url=https://www.threads.com/@username/post/abc123
→ image/png
```

Returns a 1080px-wide PNG with avatar, name, handle, post text, and footer.

`/card?url=...` and `/card.png?url=...` also work (kept for back-compat).

## How it works

1. Fetches the Threads page as Googlebot (public content, no auth needed)
2. Parses `text_fragments` (or `caption.text`) from the post JSON, keyed by URL slug
3. Renders with Pillow + Inter fonts; emoji via pilmoji/Twemoji

## Local dev

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
# then: open http://localhost:8000/?url=<threads-url>
```

## Deploy (Railway)

Live at: https://threads-card-production.up.railway.app

```bash
railway up
```

## Apple Shortcut

**"Share Thread as Image"** — share sheet action that turns a Threads URL into an image.

**Build it in the Shortcuts app (iOS or macOS):**

1. New Shortcut → name it **Share Thread as Image**
2. Tap the info icon → **Show in Share Sheet** ON → Accept: **URLs** only
3. Add action **Text** → `https://threads-card-production.up.railway.app/?url=` then insert the **Shortcut Input** magic variable inline right after the `=`
4. Add action **Get Contents of URL** → input: the Text from above
5. Add action **Get Images from Input** → input: Contents of URL
6. Add action **Share** → input: Images

Usage: in Threads, tap share → **Share Thread as Image** → pick a recipient in iMessage. The card image gets sent inline.

### On iMessage filename labels

iMessage infers a filename from the URL path basename when showing image attachments from files. Serving the endpoint from `/` (no path segment) + setting `Content-Disposition: inline; filename="Threads"` gives the cleanest result — worst case you see "Threads" as the label, which is contextual and unobtrusive.
