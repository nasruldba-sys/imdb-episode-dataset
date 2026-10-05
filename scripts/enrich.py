#!/usr/bin/env python3
"""
TVMaze enrichment for the IMDb Episode Dataset.

Reads data/meta.json (the shows build.py selected), walks TVMaze's bulk show index
(/shows?page=N, 250 shows per page, ~300 requests) and writes data/enrich.json:

    { "built": <meta.built>, "count": N,
      "shows": { "tt0903747": { n, g, t, l, pr, e, s, rt, o, p }, ... } }

Keys are short on purpose (file is loaded by the browser):
  n name | g genres[] | t type | l language | pr premiered | e ended | s status
  rt runtime | o officialSite | p poster path (after https://static.tvmaze.com/uploads/images/)

Uses only the standard library. Safe to fail: if TVMaze is unreachable or matches
too few shows, the previous data/enrich.json is left untouched and the script exits 1.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
API = "https://api.tvmaze.com/shows?page={}"
IMG_PREFIX = "https://static.tvmaze.com/uploads/images/"
PAGE_DELAY = 0.7          # TVMaze allows ~20 requests / 10 s; stay well under
MIN_MATCH_RATIO = 0.5     # refuse to overwrite enrich.json with a clearly broken result
MAX_PAGES = 2000          # hard stop, just in case


def log(msg):
    print(f"[enrich] {msg}", flush=True)


def get_page(page, tries=6):
    """Return the list of shows for a page, or None when the page does not exist (end)."""
    url = API.format(page)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "imdb-episode-dataset-enrich/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def compact(show):
    img = show.get("image") or {}
    poster = img.get("medium") or img.get("original") or ""
    if poster.startswith(IMG_PREFIX):
        poster = poster[len(IMG_PREFIX):]
    rec = {
        "n": show.get("name") or "",
        "g": show.get("genres") or [],
        "t": show.get("type") or "",
        "l": show.get("language") or "",
        "pr": show.get("premiered") or "",
        "e": show.get("ended") or "",
        "s": show.get("status") or "",
        "rt": show.get("averageRuntime") or show.get("runtime") or 0,
        "o": show.get("officialSite") or "",
        "p": poster,
    }
    return {k: v for k, v in rec.items() if v not in ("", [], 0, None)}


def main():
    t0 = time.time()
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    wanted = {s["id"] for s in meta["shows"]}
    log(f"{len(wanted):,} shows to match against TVMaze")

    found = {}
    page = 0
    while page < MAX_PAGES:
        shows = get_page(page)
        if not shows:
            break
        for sh in shows:
            imdb = (sh.get("externals") or {}).get("imdb")
            if imdb in wanted and imdb not in found:
                found[imdb] = compact(sh)
        page += 1
        if page % 25 == 0:
            log(f"page {page}, {len(found):,} matched")
        time.sleep(PAGE_DELAY)

    ratio = len(found) / max(1, len(wanted))
    log(f"{page} pages read, {len(found):,}/{len(wanted):,} matched ({ratio:.0%})")
    if ratio < MIN_MATCH_RATIO:
        log("match ratio too low - keeping the previous enrich.json")
        return 1

    out = {"built": meta.get("built"), "count": len(found), "shows": found}
    tmp = DATA / "enrich.json.tmp"
    tmp.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA / "enrich.json")
    log(f"enrich.json written in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
