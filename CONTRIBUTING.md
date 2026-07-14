# 貢獻指南

感謝你對 Byse Full Suite 有興趣! 以下是參與開發的注意事項。

## 開發環境設定

```bash
# Clone
git clone https://github.com/rushiaismywaifu/byse-full-suite.git
cd byse-full-suite

# 安裝開發依賴 (含測試 + linter)
pip install -r requirements-dev.txt
```

## 提交前檢查 (必跑)

CI 會強制執行以下檢查, 建議本地先跑一次:

```bash
# 1. flake8 critical (必過)
flake8 byse_full_suite/ byse_uploader.py tests/ scripts/ \
  --count --select=E9,F63,F7,F82 --show-source --statistics

# 2. black 格式 (必過)
black --check byse_full_suite/ byse_uploader.py tests/ scripts/

# 若有格式問題, 自動修:
black byse_full_suite/ byse_uploader.py tests/ scripts/

# 3. 單元測試 (必過)
pytest tests/ -v --tb=short

# 4. 編譯檢查
python -m py_compile byse_full_suite/*.py byse_uploader.py scripts/health_check.py
```

## 測試原則

- **不要打真實 API**: 所有測試都應使用 `unittest.mock.patch` 或 `requests-mock`
  隔離網路層, CI 環境不一定有 `BYSE_API_KEY`
- **不要 commit 真實 API Key**: `.gitignore` 已屏蔽 `repo.json`, `.env`,
  `byse_key.txt`, 但 PR 自己也要注意不要把 key 寫進測試碼
- **新增功能時加測試**: 至少覆蓋 happy path 與一個錯誤路徑

## 提交訊息慣例

使用 Conventional Commits:

```
<type>(<scope>): <subject>

<body>
```

- `type`: `feat`, `fix`, `refactor`, `docs`, `chore`, `ci`, `test`, `perf`
- `scope`: 可選, 例如 `sdk`, `cli`, `dashboard`, `server`, `uploader`
- 範例:
  - `feat(sdk): add endpoint cache for fallback paths`
  - `fix(server): remove hardcoded debug=True`
  - `docs: update README with server.py security settings`

## 目錄結構

```
byse-full-suite/
├── byse_full_suite/        # 主要套件
│   ├── sdk.py              # 完整 SDK (29+ 端點)
│   ├── cli.py              # 互動式 CLI
│   ├── dashboard.html      # 網頁儀表板
│   ├── server.py           # Flask 代理伺服器
│   └── downloader.py       # 下載工具
├── byse_uploader.py        # 輕量上傳 CLI (委派 SDK)
├── tests/                  # 單元測試
│   ├── conftest.py
│   ├── test_sdk.py
│   ├── test_uploader.py
│   └── test_downloader.py
├── scripts/
│   └── health_check.py     # CI 健康檢查腳本
├── .github/workflows/      # CI/CD
├── pyproject.toml          # 套件定義 + linter 設定
├── requirements.txt        # 執行依賴
├── requirements-dev.txt    # 開發依賴
├── LICENSE                 # MIT
└── README.md
```

## 安全提醒

- ❌ 不要把 API Key, Token, `.env` 檔案 commit 上去
- ❌ 不要在 issue / PR 描述中貼上完整 API Key
- ✅ 使用 `BYSE_API_KEY` 環境變數
- ✅ 若懷疑已 commit 機敏資料, 立即 rotate key 並通知 maintainer

## 發版流程 (maintainer)

1. 更新 `pyproject.toml` 的 `version` 欄位
2. 更新 `README.md` 的版本徽章 (如有)
3. 建立 git tag: `git tag -a v2.1.1 -m "release v2.1.1"`
4. Push tag: `git push origin v2.1.1`
5. CI 會自動 build + 發 GitHub Release
