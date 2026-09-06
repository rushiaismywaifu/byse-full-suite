# Byse Full Suite - 完整 API 利用程式

這是一套完整涵蓋 `byse.sx / filemoon` 12 群組 29+ 端點的開發套件，包含 SDK、CLI、網頁儀表板。

## 檔案結構

```
byse_full_suite/
├── sdk.py              # 完整 SDK，封裝所有端點，含 fallback
├── cli.py              # 互動式 CLI (支援 rich)
├── dashboard.html      # Byse Studio 工作空間
├── dashboard.css       # 響應式樣式
├── dashboard.js        # 連線、資料呈現與上傳佇列
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

## 3. Byse Studio (dashboard.html)

從專案根目錄啟動靜態預覽，不需要 API Key 即可探索示範資料：

```bash
uv run --no-project python -m http.server 8000 --directory byse_full_suite
# 然後打開 http://localhost:8000/dashboard.html
```

真實帳號建議透過下節的 Flask 代理連線。靜態模式可在「連線設定」選擇直接連線，但須服務支援跨來源請求；憑證僅保留在目前分頁的工作階段。

工作空間包含 6 個頁面：

- **工作台** - 帳號摘要、近期影片、近 7 天觀看趨勢；未知資料不會被當成 0 或虛構圖表。
- **影片資料庫** - 標題搜尋、分頁、選取後改名、複製、公開設定、縮圖與嵌入碼。
- **資料夾** - 資料夾卡片、子目錄、建立與快速查看影片。
- **上傳中心** - 拖曳選檔、移除佇列、傳送進度、失敗重試與遠端網址匯入。傳到代理後仍需等待伺服器確認完成。
- **轉碼佇列** - 狀態查詢、重新轉碼；刪除任務前會要求確認。
- **播放器與工具** - 字幕／封面／Logo 嵌入碼、複製、手動播放預覽、刪除與版權通知記錄，以及可展開的連線診斷／HLS 工具。

示範模式僅供瀏覽，寫入操作與實際播放器預覽會停用。HTML、CSS、JS 須放在同一目錄，無需前端建置工具或外部字型／圖示服務。

### byse-progress 事件

Byse 播放器在 iframe 內會 `window.postMessage({type:"byse-progress", file_code, progress, timestamp, duration})`。
Dashboard 僅接受目前預覽 iframe 與其來源網域的進度事件，並顯示在進階工具中。產生嵌入碼不會自動載入播放器。

## 4. (可選) Flask 代理 server.py

從專案根目錄安裝依賴並啟動代理：

```bash
uv venv
uv pip install -r requirements.txt
export BYSE_API_KEY=你的KEY
uv run --no-project python byse_full_suite/server.py
# 打開 http://localhost:5000
```

server.py 會：
- 代理 /api/* 到 https://api.byse.sx/*
- 處理 /upload (本地檔案轉發到 byse upload server)
- 提供 dashboard.html、dashboard.css、dashboard.js
- 以 `/health` 回報連線設定狀態，不呼叫上游或回傳金鑰

若設定 `BYSE_PROXY_TOKEN`，在網頁的「連線設定」填入相同的代理存取密碼即可。

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
