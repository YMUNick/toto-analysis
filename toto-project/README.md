# 🎱 TOTO Singapore 分析系統

自動爬取、分析、預測新加坡 TOTO 開獎號碼。  
**完全免費**，基於 GitHub Actions + GitHub Pages，零伺服器費用。

---

## 架構概覽

```
每週一/四開獎後
      ↓
GitHub Actions 自動執行爬蟲
      ↓
更新 data/results.json & data/meta.json
      ↓
commit push 回 repo
      ↓
觸發 GitHub Pages 重新部署
      ↓
前端自動顯示最新資料
```

---

## 📁 專案結構

```
toto-project/
├── .github/
│   └── workflows/
│       ├── scrape.yml      # 定時爬蟲 workflow
│       └── deploy.yml      # 部署到 GitHub Pages
├── scraper/
│   ├── scraper.py          # 爬蟲主程式
│   └── requirements.txt    # Python 依賴
├── data/
│   ├── results.json        # 完整開獎資料（由爬蟲維護）
│   └── meta.json           # 統計摘要、熱冷門號碼
└── docs/                   # GitHub Pages 根目錄
    ├── index.html          # 前端（自動讀取 data/）
    └── data/
        ├── results.json    # 由 deploy workflow 複製
        └── meta.json
```

---

## 🚀 部署步驟

### 第一步：Fork / 建立 Repo

1. 把此專案 push 到你的 GitHub repo
2. Repo 名稱建議：`toto-analysis`

### 第二步：啟用 GitHub Pages

1. 進入 repo → **Settings** → **Pages**
2. Source 選 **GitHub Actions**
3. 儲存

### 第三步：首次執行爬蟲（全量抓取）

1. 進入 repo → **Actions** → **🎱 TOTO Scraper**
2. 點右上角 **Run workflow**
3. 勾選 `全量重新爬取` → **Run workflow**
4. 等待完成（約 3–5 分鐘）

### 第四步：確認部署

1. Actions → **🚀 Deploy to GitHub Pages** 應自動觸發
2. 完成後訪問：`https://你的帳號.github.io/toto-analysis/`

---

## ⏰ 自動更新排程

| 時間（UTC） | 新加坡時間 | 說明 |
|------------|-----------|------|
| 每週一 14:30 | 週一 22:30 | 週一開獎後更新 |
| 每週四 14:30 | 週四 22:30 | 週四開獎後更新 |

---

## 🕷️ 爬蟲邏輯

```
來源 1：lottery.sg        ← 主要，結構最清晰
    ↓ 失敗
來源 2：singaporetoto.net ← 備援
    ↓ 失敗  
來源 3：Singapore Pools API ← 最後手段（只補最新幾期）
```

增量更新：每次只抓最新幾頁，不重複爬舊資料。

---

## 🔧 本機測試

```bash
# 安裝依賴
cd scraper
pip install -r requirements.txt

# 增量更新（只抓新資料）
python scraper.py

# 全量重新爬取
python scraper.py --full
```

---

## ❗ 注意事項

- **反爬蟲**：若某來源開始封鎖，在 `scraper.py` 中調整 `HEADERS` 或增加延遲
- **資料版權**：開獎結果為公開資訊，僅供個人分析使用
- **免責聲明**：預測號碼為統計分析，TOTO 為隨機事件，不保證中獎
