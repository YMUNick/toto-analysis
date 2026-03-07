"""
TOTO Singapore Scraper
======================
目標：爬取第三方彙整網站的 TOTO 開獎結果
優先來源：
  1. https://www.lottery.sg/toto/results   (結構清晰)
  2. https://singaporetoto.net             (備援)
  3. https://www.toto.com.sg              (備援)

流程：
  1. 讀取現有 data/results.json
  2. 找出最新已有期數
  3. 爬取新資料並補齊
  4. 存回 data/results.json
  5. 更新 data/meta.json (更新時間、統計摘要)
"""

import json
import time
import random
import logging
import re
from datetime import datetime, date
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── 設定 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR   = Path(__file__).parent.parent / "data"
RESULTS_F  = DATA_DIR / "results.json"
META_F     = DATA_DIR / "meta.json"

# 模擬真實瀏覽器 headers（降低被擋機率）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ── 資料模型 ─────────────────────────────────────────
def make_draw(draw_number: int, draw_date: str,
              nums: list[int], additional: int) -> dict:
    nums_sorted = sorted(nums)
    return {
        "draw_number":     draw_number,
        "draw_date":       draw_date,       # "YYYY-MM-DD"
        "num1":            nums_sorted[0],
        "num2":            nums_sorted[1],
        "num3":            nums_sorted[2],
        "num4":            nums_sorted[3],
        "num5":            nums_sorted[4],
        "num6":            nums_sorted[5],
        "additional_num":  additional,
    }

# ── 工具函式 ─────────────────────────────────────────
def sleep_random(lo=1.5, hi=3.5):
    """禮貌性延遲，避免對伺服器造成壓力"""
    time.sleep(random.uniform(lo, hi))

def safe_get(url: str, timeout=15) -> requests.Response | None:
    try:
        resp = SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        log.warning(f"GET {url} 失敗: {e}")
        return None

def parse_date(raw: str) -> str | None:
    """嘗試多種日期格式，回傳 YYYY-MM-DD"""
    formats = [
        "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d",
        "%d-%m-%Y", "%B %d, %Y", "%d %B %Y",
    ]
    raw = raw.strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

# ══════════════════════════════════════════════════════
# 來源 1：lottery.sg
# ══════════════════════════════════════════════════════
def scrape_lottery_sg(max_pages=10) -> list[dict]:
    """
    lottery.sg 分頁結構：
    https://www.lottery.sg/toto/results?page=1
    每頁約 10 筆，表格 <table class="result-table">
    """
    results = []
    base_url = "https://www.lottery.sg/toto/results"

    for page in range(1, max_pages + 1):
        url = f"{base_url}?page={page}"
        log.info(f"[lottery.sg] 抓取第 {page} 頁：{url}")
        resp = safe_get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # 找結果表格
        table = soup.find("table", {"class": re.compile(r"result", re.I)})
        if not table:
            # 嘗試通用 table
            table = soup.find("table")
        if not table:
            log.warning(f"[lottery.sg] 第 {page} 頁找不到表格，停止")
            break

        rows = table.find_all("tr")[1:]  # 跳過 header
        if not rows:
            log.info(f"[lottery.sg] 第 {page} 頁無資料，結束")
            break

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            try:
                draw_no   = int(re.sub(r"\D", "", cells[0].get_text()))
                draw_date = parse_date(cells[1].get_text(strip=True))
                # 號碼通常在同一格，以空格或逗號分隔
                num_text  = cells[2].get_text(separator=" ", strip=True)
                all_nums  = [int(x) for x in re.findall(r"\b([1-9]|[1-3][0-9]|4[0-9])\b", num_text)]
                add_text  = cells[3].get_text(strip=True)
                add_num   = int(re.sub(r"\D", "", add_text))

                if len(all_nums) < 6 or not draw_date:
                    continue

                results.append(make_draw(draw_no, draw_date, all_nums[:6], add_num))
            except (ValueError, IndexError) as e:
                log.debug(f"[lottery.sg] 解析列失敗: {e}")
                continue

        sleep_random()

        # 偵測是否有下一頁
        next_btn = soup.find("a", string=re.compile(r"next|›|»", re.I))
        if not next_btn:
            log.info("[lottery.sg] 已達最後一頁")
            break

    log.info(f"[lottery.sg] 共抓到 {len(results)} 筆")
    return results


# ══════════════════════════════════════════════════════
# 來源 2：singaporetoto.net（備援）
# ══════════════════════════════════════════════════════
def scrape_singaporetoto_net(max_pages=10) -> list[dict]:
    """
    singaporetoto.net 結構：
    https://www.singaporetoto.net/results/page/1/
    <div class="toto-result"> 內有期數、日期、號碼
    """
    results = []
    base_url = "https://www.singaporetoto.net/results/page"

    for page in range(1, max_pages + 1):
        url = f"{base_url}/{page}/"
        log.info(f"[singaporetoto.net] 抓取第 {page} 頁")
        resp = safe_get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "lxml")
        blocks = soup.find_all("div", {"class": re.compile(r"toto.?result|result.?block", re.I)})

        if not blocks:
            # 嘗試 article 標籤
            blocks = soup.find_all("article")

        if not blocks:
            log.warning(f"[singaporetoto.net] 第 {page} 頁找不到資料區塊")
            break

        for block in blocks:
            try:
                text = block.get_text(separator="\n")
                # 抓期數
                m_no = re.search(r"Draw\s*[:#]?\s*(\d{4,5})", text, re.I)
                # 抓日期
                m_date = re.search(
                    r"(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
                    text
                )
                # 抓號碼（6 個主號碼 + 1 個特別號）
                all_nums = [int(x) for x in re.findall(r"\b([1-9]|[1-3][0-9]|4[0-9])\b", text)]

                if not m_no or not m_date or len(all_nums) < 7:
                    continue

                draw_no   = int(m_no.group(1))
                draw_date = parse_date(m_date.group(1))
                if not draw_date:
                    continue

                results.append(make_draw(draw_no, draw_date, all_nums[:6], all_nums[6]))
            except Exception as e:
                log.debug(f"[singaporetoto.net] 解析區塊失敗: {e}")

        sleep_random()

        if not soup.find("a", string=re.compile(r"next|older|»", re.I)):
            break

    log.info(f"[singaporetoto.net] 共抓到 {len(results)} 筆")
    return results


# ══════════════════════════════════════════════════════
# 來源 3：Singapore Pools 官方 JSON API（最穩定）
# ══════════════════════════════════════════════════════
def scrape_pools_api(draw_from: int = None, draw_to: int = None) -> list[dict]:
    """
    Singapore Pools 有非官方的 JSON endpoint，有時可直接存取：
    https://www.singaporepools.com.sg/DataFileArchive/Lottery/Output/toto_Result_draw_[DRAWNO].json
    
    另一個較穩定的端點：
    https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx
    
    這裡嘗試非官方 JSON endpoint
    """
    results = []
    if not draw_from:
        return results

    for draw_no in range(draw_from, (draw_to or draw_from) + 1):
        url = (
            f"https://www.singaporepools.com.sg/DataFileArchive/Lottery/"
            f"Output/toto_Result_draw_{draw_no}.json"
        )
        resp = safe_get(url)
        if not resp:
            continue

        try:
            data = resp.json()
            # 官方 JSON 結構（如存在）：
            # { "DrawNumber": 4229, "DrawDate": "26 Feb 2026",
            #   "WinningNumbers": [14,15,21,24,25,35], "AdditionalNumber": 41 }
            draw_date = parse_date(data.get("DrawDate", ""))
            nums      = data.get("WinningNumbers", [])
            add       = data.get("AdditionalNumber", 0)

            if draw_date and len(nums) == 6 and add:
                results.append(make_draw(draw_no, draw_date, nums, add))
                log.info(f"[pools_api] 取得 #{draw_no}")
        except Exception as e:
            log.debug(f"[pools_api] #{draw_no} 解析失敗: {e}")

        sleep_random(0.5, 1.2)

    return results


# ══════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════
def load_existing() -> list[dict]:
    DATA_DIR.mkdir(exist_ok=True)
    if RESULTS_F.exists():
        with open(RESULTS_F, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_results(draws: list[dict]):
    draws_sorted = sorted(draws, key=lambda d: d["draw_number"], reverse=True)
    with open(RESULTS_F, "w", encoding="utf-8") as f:
        json.dump(draws_sorted, f, ensure_ascii=False, indent=2)
    log.info(f"已儲存 {len(draws_sorted)} 筆到 {RESULTS_F}")

def save_meta(draws: list[dict]):
    if not draws:
        return

    # 計算頻率
    freq = {i: 0 for i in range(1, 50)}
    for d in draws:
        for k in ["num1","num2","num3","num4","num5","num6","additional_num"]:
            n = d.get(k)
            if n and 1 <= n <= 49:
                freq[n] += 1

    sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    draws_sorted = sorted(draws, key=lambda d: d["draw_number"], reverse=True)

    meta = {
        "last_updated":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_draws":    len(draws),
        "latest_draw":    draws_sorted[0]["draw_number"],
        "latest_date":    draws_sorted[0]["draw_date"],
        "oldest_draw":    draws_sorted[-1]["draw_number"],
        "oldest_date":    draws_sorted[-1]["draw_date"],
        "hot_numbers":    [{"num": n, "count": c} for n, c in sorted_freq[:10]],
        "cold_numbers":   [{"num": n, "count": c} for n, c in sorted_freq[-10:]],
        "frequency":      {str(n): c for n, c in freq.items()},
    }
    with open(META_F, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info(f"已更新 meta.json（最新期：#{meta['latest_draw']}）")

def merge_draws(existing: list[dict], new_draws: list[dict]) -> tuple[list[dict], int]:
    """合併，去除重複，回傳合併後列表與新增筆數"""
    existing_map = {d["draw_number"]: d for d in existing}
    added = 0
    for d in new_draws:
        if d["draw_number"] not in existing_map:
            existing_map[d["draw_number"]] = d
            added += 1
    return list(existing_map.values()), added

def run_scraper(full_refresh: bool = False):
    log.info("═══ TOTO Scraper 啟動 ═══")

    existing = load_existing()
    latest_no = max((d["draw_number"] for d in existing), default=0) if existing else 0
    log.info(f"現有資料：{len(existing)} 筆，最新期數：#{latest_no}")

    all_new: list[dict] = []

    # ── 策略：優先爬第三方網站，只抓比現有新的資料 ──
    # 若是全量刷新（首次執行）就多抓幾頁
    pages = 50 if full_refresh else 3

    log.info("── 嘗試來源 1：lottery.sg ──")
    src1 = scrape_lottery_sg(max_pages=pages)
    if src1:
        all_new.extend(src1)
        log.info(f"來源1 取得 {len(src1)} 筆")
    else:
        log.warning("來源1 失敗，嘗試備援...")
        sleep_random(2, 4)

        log.info("── 嘗試來源 2：singaporetoto.net ──")
        src2 = scrape_singaporetoto_net(max_pages=pages)
        if src2:
            all_new.extend(src2)
            log.info(f"來源2 取得 {len(src2)} 筆")
        else:
            log.warning("來源2 也失敗，嘗試官方 API...")

            # 推測最近幾期號碼
            if latest_no > 0:
                log.info(f"── 嘗試來源 3：官方 API（#{latest_no+1} 起）──")
                src3 = scrape_pools_api(latest_no + 1, latest_no + 10)
                all_new.extend(src3)

    # ── 合併去重 ──
    merged, added = merge_draws(existing, all_new)
    log.info(f"新增 {added} 筆，總計 {len(merged)} 筆")

    if added > 0 or not existing:
        save_results(merged)
        save_meta(merged)
        log.info("✓ 資料已更新")
    else:
        log.info("資料已是最新，無需更新")

    log.info("═══ 完成 ═══")
    return added


if __name__ == "__main__":
    import sys
    full = "--full" in sys.argv
    run_scraper(full_refresh=full)
