# 開發工具（tools）

| 檔案 | 用途 | 狀態 |
|---|---|---|
| [`check_upstream_untouched.sh`](check_upstream_untouched.sh) | 檢查與上游 `v2` 的差異只在 `nous_duck/`、`CLAUDE.md`、`.github/`；CI 會執行 | 可用 |
| [`chatgpt_share_to_md.py`](chatgpt_share_to_md.py) | 把 ChatGPT 分享頁 HTML 轉成 Markdown 對話紀錄（只用標準函式庫） | 可用 |
| [`extract_chatgpt_viewer_src.py`](extract_chatgpt_viewer_src.py) | 從 ChatGPT 對話紀錄抽出檢視器原始碼；就地修改的腳本只執行 sha256 白名單內的兩段（只用標準函式庫） | 可用 |
| [`compare_chatgpt_viewer.py`](compare_chatgpt_viewer.py) | 逐件比對 ChatGPT 版檢視器 HTML 與本 repo pipeline 的零件擺放、舵機 ID，列出左右腿膝踝舵機在內側或外側（需要 numpy） | 可用 |
| [`stereo_geometry.py`](stereo_geometry.py) | AR0144 雙目鏡頭裝在鴨子頭上的名目幾何推算（深度解析度、低頭看得到的地面、看人臉的仰角、物體像素大小）；[雙目視覺規劃](../docs/stereo_vision_plan.md)的數字來源（只用標準函式庫） | 可用（推算，非量測） |
| [`follow_geometry.py`](follow_geometry.py) | 「跟著我來」的名目推算（人與鴨子的速度落差、多久跟丟、跟隨時看得到人的哪一段、抬頭時腳前看不到的地面）；[ADR-0007](../docs/adr/ADR-0007-follow-me-and-wait-here.md) 的數字來源（只用標準函式庫，沿用 `stereo_geometry.py` 的鏡頭幾何） | 可用（推算，非量測） |

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

# AR0144 幾何推算（輸出 Markdown 表格；--check 只跑內建檢查）
python3 -I nous_duck/tools/stereo_geometry.py

# 「跟著我來」的速度落差與視野推算（--check 只跑內建檢查）
python3 -I nous_duck/tools/follow_geometry.py
```
