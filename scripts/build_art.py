#!/usr/bin/env python3
"""Build weekly painting sets for each TV from the Met Open Access API.

Reads themes.json, picks `count` public domain paintings per feed with a
seed that changes every ISO week, renders each one onto a 1920x1080 mat so
LtvLauncher's BoxFit.cover shows the whole painting, and writes:

  site/index.json
  site/<feed>/feed.json
  site/<feed>/NN.jpg
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


def get(url, binary=False, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data)
        except Exception as e:
            if attempt == tries - 1 or getattr(e, "code", None) == 404:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def search(query):
    ids, offset = [], 0
    while True:
        params = {"q": query["q"], "hasImages": "true", "limit": 200, "offset": offset}
        if query.get("tags"):
            params["tags"] = "true"
        if query.get("departmentId"):
            params["departmentId"] = query["departmentId"]
        d = get(f"{SEARCH_API}?{urllib.parse.urlencode(params)}")
        batch = d.get("objectIDs") or []
        ids += batch
        offset += len(batch)
        if not batch or offset >= d.get("total", 0):
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
    for query in feed["queries"]:
        ids.update(search(query))
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


def caption_font():
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, CAPTION_SIZE)
    return ImageFont.load_default(size=CAPTION_SIZE)


def render(obj):
    art = Image.open(io.BytesIO(get(obj["primaryImage"], binary=True)))
    art = ImageOps.exif_transpose(art).convert("RGB")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--themes", default="themes.json")
    ap.add_argument("--out", default="site")
    ap.add_argument("--base-url", default="https://crankymagician.github.io/tv-art")
    ap.add_argument("--count", type=int, help="override themes.json count (for local tests)")
    args = ap.parse_args()

    themes = json.loads(Path(args.themes).read_text())
    count = args.count or themes["count"]
    year, week, _ = datetime.date.today().isocalendar()
    updated = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out = Path(args.out)
    index = {"updated": updated, "feeds": []}

    for key, feed in themes["feeds"].items():
        rng = random.Random(f"{key}-{year}-{week}")
        folder = out / key
        folder.mkdir(parents=True, exist_ok=True)
        images = []
        for obj in pick(feed, count, rng):
            name = f"{len(images) + 1:02d}.jpg"
            try:
                render(obj).save(folder / name, "JPEG", quality=88, optimize=True, progressive=True)
            except Exception as e:
                print(f"render failed {obj.get('objectID')}: {e}", file=sys.stderr)
                continue
            images.append({
                "url": f"{args.base_url}/{key}/{name}",
                "title": obj.get("title", ""),
                "artist": obj.get("artistDisplayName", ""),
                "date": obj.get("objectDate", ""),
                "source": obj.get("objectURL", ""),
            })
            print(f"{key} {name}: {caption(obj)}")
        if not images:
            sys.exit(f"no images for {key}")
        feed_url = f"{args.base_url}/{key}/feed.json"
        (folder / "feed.json").write_text(json.dumps({"name": feed["name"], "updated": updated, "images": images}, indent=2))
        index["feeds"].append({"id": key, "name": feed["name"], "url": feed_url})

    (out / "index.json").write_text(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
