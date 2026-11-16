# 開發工具（tools）

| 檔案 | 用途 | 狀態 |
|---|---|---|
| [`check_upstream_untouched.sh`](check_upstream_untouched.sh) | 檢查與上游 `v2` 的差異只在 `nous_duck/`、`CLAUDE.md`、`.github/`；CI 會執行 | 可用 |
| [`chatgpt_share_to_md.py`](chatgpt_share_to_md.py) | 把 ChatGPT 分享頁 HTML 轉成 Markdown 對話紀錄（只用標準函式庫） | 可用 |
| [`extract_chatgpt_viewer_src.py`](extract_chatgpt_viewer_src.py) | 從 ChatGPT 對話紀錄抽出檢視器原始碼；就地修改的腳本只執行 sha256 白名單內的兩段（只用標準函式庫） | 可用 |
| [`mic_placement_cad.py`](mic_placement_cad.py) | 麥克風陣列放置的 CAD 檢查：脖子後方對頭部抬頭角度的影響、頭頂空間與天線距離、傾斜與視差誤差（需要 numpy，先跑 pipeline） | 可用 |
| [`compare_chatgpt_viewer.py`](compare_chatgpt_viewer.py) | 逐件比對 ChatGPT 版檢視器 HTML 與本 repo pipeline 的零件擺放、舵機 ID，列出左右腿膝踝舵機在內側或外側（需要 numpy） | 可用 |

## 用法

```bash
# 檢查上游檔案未被修改（需要 upstream remote）
git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git   # 第一次
git fetch upstream v2
bash nous_duck/tools/check_upstream_untouched.sh upstream/v2

# ChatGPT 分享頁轉 Markdown（見 docs/handoff/README.md）
python3 -I nous_duck/tools/chatgpt_share_to_md.py share.html out.md --url <分享連結>

# 從對話紀錄抽出 ChatGPT 的檢視器原始碼
python3 -I nous_duck/tools/extract_chatgpt_viewer_src.py \
  nous_duck/docs/handoff/chatgpt_conversation_2026-11.md \
  nous_duck/docs/handoff/chatgpt_viewer_src

# 比對 ChatGPT 版檢視器與本 repo 的零件擺放（先跑 pipeline）
python3 -I nous_duck/tools/compare_chatgpt_viewer.py

# 麥克風陣列放置的 CAD 檢查（先跑 pipeline）
python3 -I nous_duck/tools/mic_placement_cad.py
```
