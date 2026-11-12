# 開發工具（tools）

| 檔案 | 用途 | 狀態 |
|---|---|---|
| [`check_upstream_untouched.sh`](check_upstream_untouched.sh) | 檢查與上游 `v2` 的差異只在 `nous_duck/`、`CLAUDE.md`、`.github/`；CI 會執行 | 可用 |
| [`chatgpt_share_to_md.py`](chatgpt_share_to_md.py) | 把 ChatGPT 分享頁 HTML 轉成 Markdown 對話紀錄（只用標準函式庫） | 可用 |

## 用法

```bash
# 檢查上游檔案未被修改（需要 upstream remote）
git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git   # 第一次
git fetch upstream v2
bash nous_duck/tools/check_upstream_untouched.sh upstream/v2

# ChatGPT 分享頁轉 Markdown（見 docs/handoff/README.md）
python3 -I nous_duck/tools/chatgpt_share_to_md.py share.html out.md --url <分享連結>
```
