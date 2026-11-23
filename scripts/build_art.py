#!/usr/bin/env python3
"""Build weekly painting sets for each TV from the Met Open Access API.

Reads themes.json, picks `count` public domain paintings per feed with a
seed that changes every ISO week, renders each one onto a 1920x1080 mat so
LtvLauncher's BoxFit.cover shows the whole painting, and writes:

  site/index.json
  site/<feed>/feed.json
  site/<feed>/NN.jpg

A feed with a "frame" in themes.json is drawn for a picture frame instead of
a TV: the painting on plain black, no larger than the frame's size, with the
caption centered underneath.
"""

import argparse
import datetime
import io
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat

# Search moved to v1.1 in October 2026; object records are still served from v1.
SEARCH_API = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
OBJECT_API = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
UA = {"User-Agent": "tv-art/1.0 (+https://github.com/crankyMagician/tv-art)"}
W, H = 1920, 1080
# Room around the painting so it reads as a framed print.
MAX_W, MAX_H = 1560, 880
CAPTION_SIZE = 22
# Pillow's built-in font has no accented letters, so prefer a system font.
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # GitHub's Ubuntu runners
    "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
]


# The Met turns requests away (403) when they come too fast, so every request
# waits its turn, and a refusal is followed by a much longer wait.
MIN_GAP = 0.25
REFUSED = (403, 429)
_last_request = [0.0]


def get(url, binary=False, tries=4):
    for attempt in range(tries):
        wait = MIN_GAP - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data)
        except Exception as e:
            code = getattr(e, "code", None)
            if attempt == tries - 1 or code == 404:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
            time.sleep(15 * (attempt + 1) if code in REFUSED else 2 * (attempt + 1))


PAGE = 200
# The search API serves no results past this offset.
SEARCH_WINDOW = 10000


def search_page(query, offset):
    params = {"q": query["q"], "hasImages": "true", "limit": PAGE, "offset": offset}
    if query.get("tags"):
        params["tags"] = "true"
    if query.get("departmentId"):
        params["departmentId"] = query["departmentId"]
    d = get(f"{SEARCH_API}?{urllib.parse.urlencode(params)}")
    return d.get("objectIDs") or [], d.get("total", 0)


def search(query):
    """Returns every object ID that matches the query."""
    ids, offset = [], 0
    while True:
        batch, total = search_page(query, offset)
        ids += batch
        offset += len(batch)
        if not batch or offset >= total:
            return ids


def search_sample(query, pages, rng):
    """Returns the IDs on the first page and on a few pages picked at random.

    A broad query such as "painting" matches thousands of objects. Reading
    every page costs dozens of requests for a feed that needs a few dozen
    paintings, and is what gets a build turned away.
    """
    ids, total = search_page(query, 0)
    offsets = list(range(PAGE, min(total, SEARCH_WINDOW), PAGE))
    rng.shuffle(offsets)
    for offset in offsets[:pages]:
        try:
            ids += search_page(query, offset)[0]
        except Exception as e:
            print(f"skip search page {query['q']} at {offset}: {e}", file=sys.stderr)
    return ids


def is_usable(obj, feed):
    if not (
        obj.get("isPublicDomain")
        and obj.get("primaryImage")
        and obj.get("classification", "").lower().startswith("painting")
    ):
        return False
    if feed.get("requireTags"):
        tags = {t.get("term") for t in obj.get("tags") or []}
        if not tags.intersection(feed["requireTags"]):
            return False
    if feed.get("artists"):
        artist = obj.get("artistDisplayName", "").lower()
        if not any(name.lower() in artist for name in feed["artists"]):
            return False
    return True


def pick(feed, count, rng):
    ids = set()
    pages = feed.get("searchPages")
    for query in feed["queries"]:
        ids.update(search_sample(query, pages, rng) if pages else search(query))
    candidates = sorted(ids)
    rng.shuffle(candidates)
    chosen = []
    for object_id in candidates:
        try:
            obj = get(f"{OBJECT_API}/{object_id}")
        except Exception as e:
            print(f"skip {object_id}: {e}", file=sys.stderr)
            continue
        if is_usable(obj, feed):
            chosen.append(obj)
            if len(chosen) == count:
                break
    return chosen


def caption(obj):
    parts = [obj.get("title", "").strip()]
    artist = obj.get("artistDisplayName", "").strip()
    if artist:
        parts.append(artist)
    date = obj.get("objectDate", "").strip()
    if date:
        parts.append(date)
    return ", ".join(p for p in parts if p)


def caption_font(size=CAPTION_SIZE):
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def fit_text(draw, text, font, max_width):
    """Shortens text with an ellipsis until it fits the width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip(" ,") + "…"


def load_art(obj):
    art = Image.open(io.BytesIO(get(obj["primaryImage"], binary=True)))
    return ImageOps.exif_transpose(art).convert("RGB")


def render_framed(obj, frame):
    """Draws the painting for a picture frame: black around it, caption below.

    Black shows as nothing on a mirror or an OLED panel, so the painting
    appears to hang on its own.
    """
    width, height = frame["width"], frame["height"]
    size = frame.get("captionSize", 34)
    strip = size * 2
    art = load_art(obj)
    art.thumbnail((width, height - strip), Image.LANCZOS)

    # The picture is only as tall as the painting needs, so a wide painting
    # does not carry empty bands above and below it.
    canvas = Image.new("RGB", (width, art.height + strip), (0, 0, 0))
    top = 0
    canvas.paste(art, ((width - art.width) // 2, top))

    text = caption(obj)
    if text:
        font = caption_font(size)
        draw = ImageDraw.Draw(canvas)
        text = fit_text(draw, text, font, width - 2 * size)
        tw = draw.textlength(text, font=font)
        draw.text(((width - tw) // 2, top + art.height + size // 2), text, font=font, fill=(205, 205, 205))
    return canvas


def render(obj, frame=None):
    if frame:
        return render_framed(obj, frame)
    art = load_art(obj)
    art.thumbnail((MAX_W, MAX_H), Image.LANCZOS)

    # Mat color: the painting's average, pulled toward black so the
    # launcher's tiles stay readable on top of it.
    r, g, b = (int(c * 0.35) for c in ImageStat.Stat(art).mean)
    canvas = Image.new("RGB", (W, H), (r, g, b))
    x, y = (W - art.width) // 2, (H - art.height) // 2
    # Thin light edge around the painting, like a print mount.
    edge = Image.new("RGB", (art.width + 8, art.height + 8), (min(r + 40, 255), min(g + 40, 255), min(b + 40, 255)))
    canvas.paste(edge, (x - 4, y - 4))
    canvas.paste(art, (x, y))

    text = caption(obj)
    if text:
        font = caption_font()
        draw = ImageDraw.Draw(canvas)
        tw = draw.textlength(text, font=font)
        draw.text((W - tw - 40, H - CAPTION_SIZE - 28), text, font=font, fill=(205, 205, 205))
    return canvas


def build_feed(key, feed, count, rng, folder, base_url):
    images = []
    for obj in pick(feed, count, rng):
        name = f"{len(images) + 1:02d}.jpg"
        try:
            render(obj, feed.get("frame")).save(folder / name, "JPEG", quality=88, optimize=True, progressive=True)
        except Exception as e:
            print(f"render failed {obj.get('objectID')}: {e}", file=sys.stderr)
            continue
        images.append({
            "url": f"{base_url}/{key}/{name}",
            "title": obj.get("title", ""),
            "artist": obj.get("artistDisplayName", ""),
            "date": obj.get("objectDate", ""),
            "source": obj.get("objectURL", ""),
        })
        print(f"{key} {name}: {caption(obj)}")
    if not images:
        raise RuntimeError("no usable paintings found")
    return images


def carry_over(key, folder, base_url):
    """Copies the feed that is published now, so a failed build keeps last week's set.

    A Pages deployment replaces the whole site. Without this, one feed that
    cannot be built would either take the other feeds down with it or vanish.
    """
    for old in folder.glob("*.jpg"):
        old.unlink()
    published = get(f"{base_url}/{key}/feed.json")
    prefix = f"{base_url}/{key}/"
    for image in published["images"]:
        if not image["url"].startswith(prefix):
            raise RuntimeError(f"unexpected image address {image['url']}")
        name = Path(urllib.parse.urlparse(image["url"]).path).name
        (folder / name).write_bytes(get(image["url"], binary=True))
    return published


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--themes", default="themes.json")
    ap.add_argument("--out", default="site")
    ap.add_argument("--base-url", default="https://crankymagician.github.io/tv-art")
    ap.add_argument("--count", type=int, help="override every feed's count (for local tests)")
    args = ap.parse_args()

    themes = json.loads(Path(args.themes).read_text())
    year, week, _ = datetime.date.today().isocalendar()
    updated = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out = Path(args.out)
    index = {"updated": updated, "feeds": []}

    carried = []
    for key, feed in themes["feeds"].items():
        rng = random.Random(f"{key}-{year}-{week}")
        folder = out / key
        folder.mkdir(parents=True, exist_ok=True)
        # A feed may ask for its own number of paintings.
        count = args.count or feed.get("count") or themes["count"]
        try:
            images = build_feed(key, feed, count, rng, folder, args.base_url)
            published = {"name": feed["name"], "updated": updated, "images": images}
        except Exception as e:
            print(f"::warning::{key} could not be built ({e}). Keeping the set that is published now.")
            try:
                published = carry_over(key, folder, args.base_url)
            except Exception as again:
                sys.exit(f"{key} could not be built ({e}) and has no published set to keep ({again})")
            carried.append(key)
        (folder / "feed.json").write_text(json.dumps(published, indent=2))
        index["feeds"].append({"id": key, "name": feed["name"], "url": f"{args.base_url}/{key}/feed.json"})

    if len(carried) == len(themes["feeds"]):
        sys.exit("no feed could be built, so there is nothing new to publish")
    (out / "index.json").write_text(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
