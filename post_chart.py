#!/usr/bin/env python3
"""
Posts the Wikipedia/Wikimedia Commons UK opinion-polling chart to Bluesky
whenever the underlying SVG changes.

How it works
------------
1. Ask the Wikimedia Commons API for the file's current SHA-1 (to detect a
   change), a Wikimedia-rendered PNG of the SVG (so this script never has to
   convert SVG itself), and the file's live licence/author metadata.
2. If the SHA-1 matches what we posted last time, do nothing.
3. Otherwise download the PNG, make sure it fits Bluesky's 1,000,000-byte image
   limit, build an attributed + accessible post, and publish it.
4. Record the new SHA-1 so we don't post the same version twice.

Attribution and the CC BY-SA licence are read live from the file's own
metadata, so the credit stays correct even if the author or licence changes.

Everything is configured through environment variables (see README.md). The
only required ones are BSKY_HANDLE and BSKY_PASSWORD.
"""

from __future__ import annotations

import html
import io
import os
import re
import sys
from datetime import date

import requests
from PIL import Image

from atproto import Client, client_utils, models


# --------------------------------------------------------------------------- #
# Configuration (overridable via environment variables)
# --------------------------------------------------------------------------- #

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

FILE_TITLE = os.environ.get(
    "FILE_TITLE",
    "File:Opinion polling graph for the next United Kingdom general election (post-2024).svg",
)

# Width, in pixels, of the PNG we ask Wikimedia to render for us.
THUMB_WIDTH = int(os.environ.get("THUMB_WIDTH", "2000"))

# Bluesky's hard limit is 1,000,000 bytes per image. Stay safely under it.
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", "950000"))

# Where we remember the last-posted version.
STATE_FILE = os.environ.get("STATE_FILE", "state/last_sha1.txt")

BSKY_SERVICE = os.environ.get("BSKY_SERVICE", "https://bsky.social")
BSKY_HANDLE = os.environ.get("BSKY_HANDLE", "").strip()
BSKY_PASSWORD = os.environ.get("BSKY_PASSWORD", "").strip()

# "1"/"true" to post even if the chart hasn't changed (used for the first post).
FORCE_POST = os.environ.get("FORCE_POST", "").lower() in ("1", "true", "yes")

# On the very first run (no stored state) we record the current version but do
# NOT post, so installing the bot doesn't fire off a post for an "update" that
# already happened. Set to "true" to post on first run instead.
POST_ON_FIRST_RUN = os.environ.get("POST_ON_FIRST_RUN", "").lower() in ("1", "true", "yes")

# A descriptive User-Agent is required by Wikimedia's API policy.
_repo = os.environ.get("GITHUB_REPOSITORY", "")
_repo_url = f"https://github.com/{_repo}" if _repo else "https://github.com/"
USER_AGENT = os.environ.get(
    "USER_AGENT",
    f"UKPollChartBlueskyBot/1.0 (+{_repo_url})",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(msg, flush=True)


def strip_html(value: str) -> str:
    """Commons metadata fields can contain HTML; reduce them to plain text."""
    if not value:
        return ""
    # Replace <a ...>text</a> and other tags with their text content.
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_file_info() -> dict:
    """Return sha1, rendered PNG url, file-page url and attribution fields."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "imageinfo",
        "titles": FILE_TITLE,
        "iiprop": "timestamp|sha1|url|size|mediatype|extmetadata",
        "iiurlwidth": str(THUMB_WIDTH),
    }
    resp = requests.get(
        COMMONS_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        raise RuntimeError("Commons API returned no pages for the file.")
    page = pages[0]
    if page.get("missing"):
        raise RuntimeError(f"File not found on Commons: {FILE_TITLE!r}")

    info_list = page.get("imageinfo")
    if not info_list:
        raise RuntimeError("Commons API returned no imageinfo for the file.")
    info = info_list[0]

    em = info.get("extmetadata", {})

    def meta(key: str) -> str:
        return strip_html((em.get(key) or {}).get("value", ""))

    licence_short = meta("LicenseShortName") or "CC BY-SA 4.0"
    licence_url = meta("LicenseUrl")
    if not licence_url:
        # Fall back to a sensible CC BY-SA deed if the field is absent.
        slug = "by-sa/4.0"
        m = re.search(r"by-sa[\s-]?(\d\.\d)", licence_short, re.IGNORECASE)
        if m:
            slug = f"by-sa/{m.group(1)}"
        licence_url = f"https://creativecommons.org/licenses/{slug}/"

    return {
        "sha1": info.get("sha1", ""),
        "timestamp": info.get("timestamp", ""),
        "thumburl": info.get("thumburl"),
        "thumbwidth": info.get("thumbwidth"),
        "thumbheight": info.get("thumbheight"),
        "descriptionurl": info.get("descriptionurl")
        or f"https://commons.wikimedia.org/wiki/{FILE_TITLE.replace(' ', '_')}",
        "title": meta("ObjectName") or "Opinion polling graph for the next UK general election",
        "author": meta("Artist") or "Wikipedia contributors",
        "credit": meta("Credit"),
        "licence_short": licence_short,
        "licence_url": licence_url.rstrip("/") + "/",
    }


def download_png(info: dict) -> tuple[bytes, int, int]:
    """Download the Wikimedia-rendered PNG and squeeze it under the size limit."""
    url = info.get("thumburl")
    if not url:
        raise RuntimeError("Commons did not return a rendered PNG (thumburl).")

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    resp.raise_for_status()
    raw = resp.content

    img = Image.open(io.BytesIO(raw)).convert("RGB")

    def encode(image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    data = encode(img)
    # If it's too big (unlikely for a line chart), scale down until it fits.
    while len(data) > MAX_IMAGE_BYTES and img.width > 600:
        new_w = int(img.width * 0.85)
        new_h = int(img.height * 0.85)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        data = encode(img)

    # Last resort: fall back to JPEG if PNG still won't fit.
    if len(data) > MAX_IMAGE_BYTES:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = buf.getvalue()

    log(f"Prepared image: {img.width}x{img.height}, {len(data)} bytes")
    return data, img.width, img.height


def read_state() -> str:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return ""


def write_state(sha1: str) -> None:
    directory = os.path.dirname(STATE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        fh.write(sha1 + "\n")


def build_post_text(info: dict) -> client_utils.TextBuilder:
    """Short post body with a clickable link to the source + licence."""
    today = date.today().strftime("%-d %B %Y")
    tb = client_utils.TextBuilder()
    tb.text(f"📊 UK general election voting-intention poll tracker — updated {today}.\n\n")
    tb.text(f"Chart ({info['licence_short']}) from ")
    tb.link("Wikimedia Commons", info["descriptionurl"])
    tb.text(". Full credit in the image description (alt text).")
    return tb


def build_alt_text(info: dict) -> str:
    """Accessible description followed by full CC BY-SA attribution."""
    description = (
        f"{info['title']}. A line chart showing UK Westminster voting-intention "
        "opinion polls since the July 2024 general election, with a trend line "
        "for each major party."
    )
    attribution = (
        "\n\n— Attribution —\n"
        f"Title: {info['title']}\n"
        f"Author: {info['author']}\n"
        f"Source: {info['descriptionurl']}\n"
        f"Licence: {info['licence_short']} — {info['licence_url']}\n"
        "Changes: rendered from the original SVG to PNG for posting.\n"
        f"This image is shared under {info['licence_short']}."
    )
    alt = description + attribution
    # Bluesky allows generous alt text; keep well within bounds just in case.
    return alt[:1900]


def post_to_bluesky(image: bytes, width: int, height: int, info: dict) -> None:
    if not BSKY_HANDLE or not BSKY_PASSWORD:
        raise RuntimeError("BSKY_HANDLE and BSKY_PASSWORD must be set.")

    client = Client(base_url=BSKY_SERVICE)
    client.login(BSKY_HANDLE, BSKY_PASSWORD)

    aspect = None
    try:
        aspect = models.AppBskyEmbedDefs.AspectRatio(width=width, height=height)
    except Exception:  # pragma: no cover - older library versions
        aspect = None

    client.send_image(
        text=build_post_text(info),
        image=image,
        image_alt=build_alt_text(info),
        langs=["en-GB"],
        image_aspect_ratio=aspect,
    )
    log("Posted to Bluesky.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    log(f"Checking {FILE_TITLE!r} on Wikimedia Commons…")
    info = fetch_file_info()
    current = info["sha1"]
    if not current:
        raise RuntimeError("Commons API did not return a SHA-1 for the file.")
    log(f"Current version SHA-1: {current} (revised {info['timestamp']})")

    previous = read_state()
    first_run = previous == ""

    should_post = FORCE_POST or (current != previous and (not first_run or POST_ON_FIRST_RUN))

    if not should_post:
        if first_run:
            log("First run: recording current version without posting "
                "(set POST_ON_FIRST_RUN=true or run with FORCE_POST=1 to post now).")
            write_state(current)
        else:
            log("Chart unchanged since last post. Nothing to do.")
        return 0

    log("Posting a new chart…")
    image, width, height = download_png(info)
    post_to_bluesky(image, width, height, info)
    write_state(current)
    log("Done. State updated.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        sys.exit(1)
