# 交接資料

從前一個雲端對話與 ChatGPT 對話交接過來的原始資料與整理。

| 檔案 | 內容 | 性質 |
|---|---|---|
| [`handoff_summary.md`](handoff_summary.md) | 已確定的事（舵機、ID、列印進度、CAD 缺口、檢視器需求與 ChatGPT 版作法） | 整理，**先讀這份** |
| [`environment_survey.md`](environment_survey.md) | 雲端容器的網路、瀏覽器、WebGL 調查 | 整理 |
| [`chatgpt_conversation_2026-11.md`](chatgpt_conversation_2026-11.md) | ChatGPT 對話完整紀錄（13 則使用者訊息、63 則回覆，含它執行過的程式碼） | 原始資料，以腳本解出、未改寫 |
| [`chatgpt_viewer_src/`](chatgpt_viewer_src/README.md) | ChatGPT 寫的 3D 組裝檢視器原始碼（10 個檔案），從對話紀錄抽出 | 原始資料，以腳本抽出、未改寫、未驗證 |
| [`chatgpt_viewer_html/`](chatgpt_viewer_html/README.md) | ChatGPT 版檢視器的 HTML 成品（使用者 2026-11-14 上傳，備用） | 原始資料，未改寫；只確認可離線開啟，內容未驗證 |
| [`upstream_bom.csv`](upstream_bom.csv) | 原作者 BOM（Google Sheets 匯出，2026-11-12） | 原始資料，未改寫 |

## 重新產生原始資料

```bash
# ChatGPT 對話紀錄
curl -sSL -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36" \
  -o /tmp/share.html https://chatgpt.com/share/6af53edc-6230-83ee-968e-225375fc4c71
python3 -I nous_duck/tools/chatgpt_share_to_md.py /tmp/share.html \
  nous_duck/docs/handoff/chatgpt_conversation_2026-11.md \
  --url https://chatgpt.com/share/6af53edc-6230-83ee-968e-225375fc4c71

# ChatGPT 的檢視器原始碼（從上面的對話紀錄抽出）
python3 -I nous_duck/tools/extract_chatgpt_viewer_src.py \
  nous_duck/docs/handoff/chatgpt_conversation_2026-11.md \
  nous_duck/docs/handoff/chatgpt_viewer_src

# 上游 BOM
curl -sSL -o nous_duck/docs/handoff/upstream_bom.csv \
  "https://docs.google.com/spreadsheets/d/1gq4iWWHEJVgAA_eemkTEsshXqrYlFxXAPwO515KpCJc/export?format=csv"
```

## 注意

- ChatGPT 對話裡的連結 `sandbox:/mnt/data/...` 指向 ChatGPT 的沙箱，**檔案已經拿不到**。例外：檢視器 HTML 成品已由使用者在 2026-11-14 上傳，存在 [`chatgpt_viewer_html/`](chatgpt_viewer_html/README.md)。
- 對話中的程式碼與結論是 ChatGPT 的產出，沒有在本 repo 驗證過；引用前要重新核對上游檔案。
- 上游 BOM 的價格是原作者以歐元、法國通路估的，不代表台灣價格。
