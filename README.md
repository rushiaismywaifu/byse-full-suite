# Byse.sx / Filemoon 完整 API 套件 - Byse Full Suite

![CI](https://github.com/rushiaismywaifu/byse-full-suite/actions/workflows/ci.yml/badge.svg)
![Health Check](https://github.com/rushiaismywaifu/byse-full-suite/actions/workflows/health-check.yml/badge.svg)
![GitHub Pages](https://img.shields.io/badge/Powered%20by-GitHub%20Pages-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB)


`byse.sx` 是 `filemoon.sx` 改名後的影片託管、分發、變現平台，提供 26 個 CDN 節點、上傳、轉碼、自訂網域、廣告分潤等功能。

本專案完整封裝 **12 群組 29+ 端點**，包含 SDK、CLI、網頁儀表板，避免把機敏資料 push 上去。

> ⚠️ 請勿在公開倉庫提交 API Key、Token、或影片檔案。本專案 `.gitignore` 已屏蔽 `repo.json`, `.env`, `*.key`, `*.mp4/mkv`。

## 功能

- ✅ `account/info`, `account/stats`
- ✅ `upload/server` + 本地 POST 上傳 (含進度條)
- ✅ `remote/add` / `remote/status` / `remote/remove` 遠端拉取
- ✅ `file/info`, `file/list`, `file/clone`, `file/edit` (改標題/公開/移動)
- ✅ `folder/list`, `folder/create`
- ✅ `files/deleted`, `files/dmca`
- ✅ `encoding/list`, `status`, `restart`, `delete`
- ✅ `images/thumb`, `splash`, `preview`
- ✅ 字幕/封面/Logo 產生器 `c1_file`, `poster`, `logo` (播放器端參數)
- ✅ `byse-progress` postMessage 監聽
- ✅ Iframe Embed Code 產生器

Base URL: `https://api.byse.sx` (舊版 `https://filemoonapi.com/api` 已 522)

官方文件: `https://byse.sx/api-docs`

## 結構

```
byse_full_suite/
├── sdk.py              # 完整 SDK
├── cli.py              # 互動式 CLI (rich)
├── dashboard.html      # Byse Studio 網頁工作空間
├── dashboard.css       # 響應式介面樣式
├── dashboard.js        # 互動、連線與上傳管理
├── server.py           # Flask 代理伺服器 (可選，解決 CORS)
└── README.md           # 詳細說明

byse_uploader.py        # 輕量版上傳小工具 (單檔)
README_byse.md          # 輕量版說明
```

## 快速開始

### 1. SDK

```python
from byse_full_suite.sdk import ByseSDK

sdk = ByseSDK(api_key="你的KEY")
print(sdk.account_info())

# 本地上傳
sdk.upload_file("video.mp4", folder_id=0)

# 遠端拉取
sdk.remote_upload("https://example.com/video.mp4")

# 產生 Embed
print(sdk.build_embed_with_extras("FILECODE", domain="你的專屬域名",
    subtitles=[{"file":"https://example.com/en.vtt","label":"English"}],
    poster="https://example.com/poster.jpg"))
```

### 2. CLI

```bash
pip install requests rich
export BYSE_API_KEY=你的KEY
python byse_full_suite/cli.py

# 非互動測試
python byse_full_suite/cli.py --non-interactive
```

### 3. Byse Studio 網頁工作空間

包含帳號摘要、觀看趨勢、影片搜尋與分頁、資料夾管理、拖曳上傳佇列，以及播放器產生器。桌面與手機皆可使用；未設定帳號時，可點「探索示範」查看範例資料。示範模式不會向真實帳號發送操作。

```bash
# 從專案根目錄安裝並啟動（推薦）
uv venv
uv pip install -r requirements.txt
export BYSE_API_KEY=你的KEY
uv run --no-project python byse_full_suite/server.py
# 打開 http://127.0.0.1:5000/
```

API Key 由代理伺服器保管。若設定了 `BYSE_PROXY_TOKEN`，請在網頁「連線設定」填入代理存取密碼。

```bash
# 靜態預覽（可使用示範資料；真實帳號須在連線設定選擇直接連線）
uv run --no-project python -m http.server 8000 --directory byse_full_suite
# 打開 http://localhost:8000/dashboard.html
```

直接連線需 Byse API 支援跨來源請求，API Key 會隨 API 網址傳送。網頁憑證僅存於目前分頁的 `sessionStorage`，不再長期儲存在 `localStorage`。部署靜態網站時，請將 HTML、CSS、JS 三個檔案放在同一目錄；既有 GitHub Pages 工作流程已包含這些資產。

server.py 安全設定 (環境變數):
- `BYSE_API_KEY` (必填): 由 server 注入, 前端永遠看不到
- `BYSE_PROXY_TOKEN` (可選): 啟用 Bearer token 認證
- `BYSE_CORS_ORIGINS` (可選): 限制跨網域白名單, 逗號分隔
- `BYSE_HOST` (預設 127.0.0.1): 綁定介面
- `BYSE_PORT` (預設 5000): 監聽 port
- `BYSE_DEBUG=1` (預設關): 開啟 Flask debug, 嚴禁生產環境使用

### 4. 輕量上傳

```bash
python byse_uploader.py --key 你的KEY -f video.mp4
```

## 安全提醒

- Byse 前身是 filemoon.sx，社群有拖欠分潤回報，僅建議測試/備份用途
- 自訂 embed domain 每帳號不同，需到後台 Settings -> Custom Domains 查看
- 不要把 `repo.json`, `.env`, API Key 推到 GitHub

## 授權

MIT

### 快速下載
- `python byse_full_suite/downloader.py https://bysedikamoum.com/download/CODE` 或加 `--use-ytdlp`
