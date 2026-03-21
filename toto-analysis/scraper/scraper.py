"""
TOTO Singapore Scraper
======================
Scrapes draw results directly from Singapore Pools official website
using Playwright (headless browser) to handle JavaScript rendering.

Draw URL format:
  https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx
  ?sppl=base64("DrawNumber=XXXX")

Usage:
  python scraper.py           # incremental (latest draws only)
  python scraper.py --full    # full refresh from 2015 onwards (~draw #2900)
"""

import base64
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR  = Path(__file__).parent.parent / "data"
RESULTS_F = DATA_DIR / "results.json"
META_F    = DATA_DIR / "meta.json"

BASE_URL  = "https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx"

# Earliest draw to fetch in full-refresh mode (~Jan 2015)
FULL_REFRESH_FROM = 2900


# ── URL helpers ─────────────────────────────────────────────────────────────

def draw_url(draw_no: int) -> str:
    encoded = base64.b64encode(f"DrawNumber={draw_no}".encode()).decode()
    return f"{BASE_URL}?sppl={encoded}"


# ── Date parsing ─────────────────────────────────────────────────────────────

def parse_date(raw: str) -> str | None:
    """Return YYYY-MM-DD or None."""
    formats = [
        "%a, %d %b %Y",   # Thu, 05 Mar 2026
        "%A, %d %B %Y",   # Thursday, 05 March 2026
        "%d %b %Y",        # 05 Mar 2026
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%d %B %Y",
    ]
    raw = raw.strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Data model ───────────────────────────────────────────────────────────────

def make_draw(draw_number: int, draw_date: str,
              nums: list[int], additional: int) -> dict:
    nums_sorted = sorted(nums)
    return {
        "draw_number":    draw_number,
        "draw_date":      draw_date,
        "num1":           nums_sorted[0],
        "num2":           nums_sorted[1],
        "num3":           nums_sorted[2],
        "num4":           nums_sorted[3],
        "num5":           nums_sorted[4],
        "num6":           nums_sorted[5],
        "additional_num": additional,
    }


# ── Page text parser ──────────────────────────────────────────────────────────

def parse_draw_from_text(text: str, draw_no: int) -> dict | None:
    """Extract draw result from rendered page text."""
    tu = text.upper()

    # ── Validate draw number on page matches requested ──
    page_no_match = re.search(r'Draw\s*No\.?\s*(\d+)', text, re.I)
    if page_no_match:
        page_no = int(page_no_match.group(1))
        if page_no != draw_no:
            log.debug(f"#{draw_no}: page shows draw #{page_no}, skipping")
            return None

    # ── Date ──
    date_match = (
        re.search(r'(\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4})', text) or
        re.search(r'(\w+day,\s+\d{1,2}\s+\w+\s+\d{4})', text) or
        re.search(r'(\d{1,2}\s+\w+\s+\d{4})', text)
    )
    if not date_match:
        log.debug(f"#{draw_no}: no date found")
        return None
    draw_date = parse_date(date_match.group(1))
    if not draw_date:
        log.debug(f"#{draw_no}: unparseable date '{date_match.group(1)}'")
        return None

    # ── Winning numbers + additional ──
    win_match = re.search(r'WINNING\s+NUMBERS?', tu)
    add_match = re.search(r'ADDITIONAL\s+NUMBERS?', tu)

    if not win_match or not add_match or win_match.start() >= add_match.start():
        log.debug(f"#{draw_no}: can't locate number sections")
        return None

    win_idx = win_match.start()
    add_idx = add_match.start()

    win_section = text[win_idx:add_idx]
    add_section = text[add_idx: add_idx + 80]

    def extract_valid_nums(s: str) -> list[int]:
        return [int(x) for x in re.findall(r'\b(\d{1,2})\b', s)
                if 1 <= int(x) <= 49]

    win_nums = extract_valid_nums(win_section)
    add_nums = extract_valid_nums(add_section)

    if len(win_nums) < 6 or not add_nums:
        log.debug(f"#{draw_no}: not enough numbers (win={win_nums}, add={add_nums})")
        return None

    return make_draw(draw_no, draw_date, win_nums[:6], add_nums[0])


# ── Main scraper ──────────────────────────────────────────────────────────────

def scrape_draws(draw_numbers: list[int]) -> list[dict]:
    """Fetch a list of draw numbers from Singapore Pools using Playwright."""
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        for draw_no in draw_numbers:
            url = draw_url(draw_no)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Try to wait for a known element; fall back to network idle
                # if the selector no longer exists (website layout changes).
                try:
                    page.wait_for_selector(
                        ".drawNumber, #drawNumber, .result-container, table",
                        timeout=10_000,
                    )
                except PlaywrightTimeout:
                    log.debug(f"#{draw_no}: selector not found, waiting for networkidle")
                    page.wait_for_load_state("networkidle", timeout=20_000)

                text = page.inner_text("body")
                draw = parse_draw_from_text(text, draw_no)

                if draw:
                    results.append(draw)
                    log.info(f"✓ #{draw_no} {draw['draw_date']}  "
                             f"{draw['num1']},{draw['num2']},{draw['num3']},"
                             f"{draw['num4']},{draw['num5']},{draw['num6']}  "
                             f"+{draw['additional_num']}")
                else:
                    log.warning(f"✗ #{draw_no}: parsed nothing — page snippet: "
                                f"{text[:300].replace(chr(10), ' ')!r}")

            except PlaywrightTimeout:
                log.warning(f"✗ #{draw_no}: timeout (draw may not exist)")
            except Exception as e:
                log.warning(f"✗ #{draw_no}: {e}")

            time.sleep(random.uniform(1.0, 2.0))

        browser.close()

    return results


# ── Persistence ───────────────────────────────────────────────────────────────

def load_existing() -> list[dict]:
    DATA_DIR.mkdir(exist_ok=True)
    if RESULTS_F.exists():
        with open(RESULTS_F, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(draws: list[dict]):
    draws_sorted = sorted(draws, key=lambda d: d["draw_number"], reverse=True)
    with open(RESULTS_F, "w", encoding="utf-8") as f:
        json.dump(draws_sorted, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(draws_sorted)} draws → {RESULTS_F}")


def save_meta(draws: list[dict]):
    if not draws:
        return
    freq = {i: 0 for i in range(1, 50)}
    for d in draws:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6", "additional_num"]:
            n = d.get(k)
            if n and 1 <= n <= 49:
                freq[n] += 1

    sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    draws_sorted = sorted(draws, key=lambda d: d["draw_number"], reverse=True)

    meta = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_draws":  len(draws),
        "latest_draw":  draws_sorted[0]["draw_number"],
        "latest_date":  draws_sorted[0]["draw_date"],
        "oldest_draw":  draws_sorted[-1]["draw_number"],
        "oldest_date":  draws_sorted[-1]["draw_date"],
        "hot_numbers":  [{"num": n, "count": c} for n, c in sorted_freq[:10]],
        "cold_numbers": [{"num": n, "count": c} for n, c in sorted_freq[-10:]],
        "frequency":    {str(n): c for n, c in freq.items()},
    }
    with open(META_F, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info(f"Updated meta.json (latest: #{meta['latest_draw']})")


def merge_draws(existing: list[dict], new_draws: list[dict]) -> tuple[list[dict], int]:
    existing_map = {d["draw_number"]: d for d in existing}
    added = 0
    for d in new_draws:
        if d["draw_number"] not in existing_map:
            existing_map[d["draw_number"]] = d
            added += 1
    return list(existing_map.values()), added


# ── Entry point ───────────────────────────────────────────────────────────────

def run_scraper(full_refresh: bool = False):
    log.info("═══ TOTO Scraper Start ═══")

    existing  = load_existing()
    known_nos = {d["draw_number"] for d in existing}
    latest_no = max(known_nos, default=0)
    log.info(f"Existing data: {len(existing)} draws, latest #{latest_no}")

    if full_refresh:
        # Fetch everything from FULL_REFRESH_FROM up to latest+5
        target_from = FULL_REFRESH_FROM
        target_to   = max(latest_no + 5, target_from + 5)
        draw_numbers = [n for n in range(target_to, target_from - 1, -1)
                        if n not in known_nos]
        log.info(f"Full refresh: {len(draw_numbers)} draws to fetch "
                 f"(#{target_from}–#{target_to})")
    else:
        # Incremental: try the 20 draws after the latest known
        target_from = latest_no + 1 if latest_no else 4150
        target_to   = target_from + 19
        draw_numbers = list(range(target_to, target_from - 1, -1))
        log.info(f"Incremental: checking #{target_from}–#{target_to}")

    new_draws = scrape_draws(draw_numbers)
    merged, added = merge_draws(existing, new_draws)
    log.info(f"Added {added} new draws, total {len(merged)}")

    if added > 0 or not existing:
        save_results(merged)
        save_meta(merged)
        log.info("✓ Data updated")
    else:
        log.info("No new data")

    log.info("═══ Done ═══")
    return added


if __name__ == "__main__":
    full = "--full" in sys.argv
    run_scraper(full_refresh=full)
