# Byse Uploader 使用說明

這個工具支援 新版 `api.byse.sx` 與舊版 `filemoonapi.com/api`，已自動相容。

## 安裝

```bash
pip install requests tqdm
# tqdm 可選，用來顯示上傳進度條
```

## 取得 API Key

1. 登入 https://byse.sx
2. Settings -> API / Security
3. 複製 API Key

## 配置 API Key (三選一)

```bash
# 1. 命令行
python byse_uploader.py --key YOUR_KEY ...

# 2. 環境變數 (推薦)
export BYSE_API_KEY=YOUR_KEY
python byse_uploader.py -f video.mp4

# 3. 配置檔
mkdir -p ~/.byse
echo '{"api_key":"YOUR_KEY"}' > ~/.byse/config.json
```

## 常用指令

```bash
# 1. 查帳號額度
python byse_uploader.py info

# 2. 上傳本地檔案
python byse_uploader.py -f /path/to/video.mp4

# 3. 多檔上傳到指定資料夾
python byse_uploader.py -f a.mp4 b.mkv c.avi --folder-id 15

# 4. 遠端 URL 拉取 (Remote Upload)
python byse_uploader.py --url https://example.com/video.mp4
python byse_uploader.py --url https://example.com/1.mp4 https://example.com/2.mp4

# 5. 同時本機 + 遠端
python byse_uploader.py -f local.mp4 --url https://example.com/remote.mp4 --folder-id 0

# 6. 列出檔案
python byse_uploader.py list --per-page 20 --page 1
python byse_uploader.py list --title "Iron man"

# 7. 查單檔資訊
python byse_uploader.py fileinfo gi4o0tlro01u
python byse_uploader.py fileinfo code1,code2,code3

# 8. 查編碼佇列 / 狀態
python byse_uploader.py encoding
python byse_uploader.py enc-status gi4o0tlro01u

# 9. 查遠端上傳進度
python byse_uploader.py remote-status jthi5jdsu8t9

# 10. 查 embed domain (每個帳號的播放域名不同)
python byse_uploader.py domains
```

## 輸出範例

上傳成功後會顯示：

```
[+] 上傳伺服器: https://s1.byse.sx/upload/01
[+] 準備上傳: video.mp4 (120.50 MB)
video.mp4: 100%|████████| 120M/120M [00:15<00:00, 8.2MB/s]
[+] 上傳回應: { "files": [{"filecode":"tnklyibwwpsh", "filename":"video.mp4", "status":"OK"}] }
  -> filecode: tnklyibwwpsh
     檔名: video.mp4
     官方播放頁 (通用): https://byse.sx/e/tnklyibwwpsh
     直鏈 (需 premium): https://byse.sx/d/tnklyibwwpsh
```

你需要去後台 Settings -> Custom Domains 看你的專屬域名，才能拼出最終 embed link：`https://你的專屬域名/e/tnklyibwwpsh`

## 若遇到 `Page not found – The requested page doesn't exist in the renewed frontend`

這是 byse 官方在 2025年12月切換 DNS 時的已知 bug，工具會自動 fallback 到 `filemoonapi.com/api`。若一直失敗，可手動指定：

```bash
python byse_uploader.py --base https://filemoonapi.com/api -f video.mp4
```

## 安全提醒

byse.sx 前身是 filemoon.sx，社群有拖欠分潤的投訴。請勿上傳侵權或敏感內容，建議僅作測試或備份用途。
