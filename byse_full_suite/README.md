# Byse Full Suite - 完整 API 利用程式

這是一套完整涵蓋 `byse.sx / filemoon` 12 群組 29+ 端點的開發套件，包含 SDK、CLI、網頁儀表板。

## 檔案結構

```
byse_full_suite/
├── sdk.py              # 完整 SDK，封裝所有端點，含 fallback
├── cli.py              # 互動式 CLI (支援 rich)
├── dashboard.html      # 單檔網頁儀表板，無需後端即可直接呼叫 API
├── server.py           # 可選 Flask 代理伺服器 (避免 CORS，處理本地上傳)
└── README.md
```

## 已驗證可用端點 (實測於 2026-07-12)

| 群組 | 端點 | 狀態 |
|---|---|---|
| Account | account/info | ✅ |
|  | account/stats | ✅ |
| Upload | upload/server | ✅ |
|  | POST upload server | ✅ (本地上傳) |
|  | remote/add (舊) | ✅ (遠端上傳) |
|  | upload/url (新) | ❌ Invalid operation (已 fallback) |
|  | remote/status, remote/remove | ✅ |
| File | file/info, file/list, file/clone, file/edit | ✅ |
|  | file/set_folder 實際用 file/edit[fld_id] | ✅ |
| Folder | folder/list, folder/create | ✅ |
| Deleted/DMCA | files/deleted, files/dmca | ✅ |
| Encoding | encoding/list, status, restart, delete | ✅ |
| Images | images/thumb, splash, preview | ✅ |
| 補助 | poster, logo, subtitle 透過 URL 參數 c1_file / poster / logo | ✅ (player 端) |
| HLS | file/hls 等 | ❌ 需 premium 或端點已移除 |

> `filemoonapi.com/api` 目前 Cloudflare 522 超時，請使用 `https://api.byse.sx`

## 1. SDK 用法

```python
from sdk import ByseSDK

sdk = ByseSDK(api_key="你的KEY")

print(sdk.account_info())
print(sdk.account_stats())

server = sdk.upload_server()
sdk.upload_file("video.mp4", folder_id=0)

sdk.remote_upload("https://example.com/video.mp4")
sdk.file_list(per_page=20, page=1, title="Iron")
sdk.file_info("1vtkmhfb44rj")
sdk.file_clone("1vtkmhfb44rj")
sdk.file_edit("1vtkmhfb44rj", title="新標題", public=1)

sdk.folder_list()
sdk.folder_create("My Folder", parent_id=0)

sdk.encoding_list()
sdk.thumb("1vtkmhfb44rj")

# 產生 Embed
url = sdk.build_embed_with_extras("1vtkmhfb44rj", domain="你的專屬域名",
    subtitles=[{"file":"https://example.com/en.vtt","label":"English"}],
    poster="https://example.com/poster.jpg")
print(url)
print(sdk.iframe_code("1vtkmhfb44rj"))
```

## 2. CLI 用法

```bash
pip install requests rich

# 互動式
python cli.py --key YOUR_KEY

# 非互動測試所有端點
python cli.py --key YOUR_KEY --non-interactive

# 用環境變數
export BYSE_API_KEY=YOUR_KEY
python cli.py
```

功能選單：
- 1 帳號總覽 (info, stats, embed domains)
- 2 檔案管理 (list, search, info, clone, edit, thumb/splash/preview, embed code)
- 3 資料夾 (list, create, tree)
- 4 上傳中心 (本地/批次/遠端/查進度/移除)
- 5 編碼監控
- 6 工具箱 (test_all, deleted, dmca, premium HLS, 字幕產生器)

## 3. Web Dashboard (dashboard.html)

直接用瀏覽器打開即可，無需安裝：

```bash
# 方法1: 直接打開檔案
open dashboard.html

# 方法2: 啟動簡易 HTTP
cd byse_full_suite
python -m http.server 8000
# 然後打開 http://localhost:8000/dashboard.html
```

Dashboard 包含 6 個分頁：

- **帳號總覽** - info, stats, test_all
- **檔案管理** - 分頁列表、搜尋、詳情、克隆、改標題/公開、縮圖、產生 embed
- **資料夾** - 列表、建立
- **上傳中心** - 拖曳本地上傳 (顯示進度)、遠端 URL 拉取
- **編碼監控** - encoding/list, status, restart, delete
- **工具箱** - deleted/dmca、進階 embed URL 產生器 (c1_file, poster, logo)、Premium HLS 實驗、即時監聽 byse-progress 事件 (postMessage)

### byse-progress 事件

Byse 播放器在 iframe 內會 `window.postMessage({type:"byse-progress", file_code, progress, timestamp, duration})`。
Dashboard 會即時 log，方便你做觀看進度追蹤。

## 4. (可選) Flask 代理 server.py

若遇到 CORS 問題，可用 server.py 代理：

```bash
pip install flask flask-cors requests
python server.py
# 打開 http://localhost:5000
```

server.py 會：
- 代理 /api/* 到 https://api.byse.sx/*
- 處理 /upload (本地檔案轉發到 byse upload server)
- 提供 dashboard.html

## 快速測試 (你之前的 Key)

實測範例：
- upload_file 成功 -> filecode `1vtkmhfb44rj` (164MB 12秒)
- file/info -> canplay 從 0 變 1 (轉碼完成)
- file/clone -> 8l55dj93gj5r
- file/edit 改標題成功
- folder/create -> 384164

**請記得重置 API Key！**

## 注意事項

- Byse 前身 filemoon.sx，社群有拖欠分潤投訴，請勿上傳侵權內容。
- 自訂 embed domain 每個帳號不同，需到後台 Settings -> Custom Domains 查看，否則用 filemoon.to / byse.sx 通用域名會被系統偵測後提示 embedding blocked。
- 上傳伺服器 URL 每次呼叫 upload/server 都可能不同 (如 upload-edge2-waw.r66nv9ed.com)。
