# ChatGPT 版 3D 組裝檢視器原始碼（參考用）

ChatGPT 在 2026-11-12 做出 `Open_Duck_Mini_v2_Assembly_Viewer.html`，當時以為成品只存在 ChatGPT 的沙箱（`/mnt/data`）、拿不到；2026-11-14 使用者上傳了成品，存在 [`../chatgpt_viewer_html/`](../chatgpt_viewer_html/README.md)。這個資料夾放的是它在對話中寫出的產生程式。內容用 [`../../../tools/extract_chatgpt_viewer_src.py`](../../../tools/extract_chatgpt_viewer_src.py) 從 [`../chatgpt_conversation_2026-11.md`](../chatgpt_conversation_2026-11.md) 抽出，**沒有人工改寫**。

> ⚠️ **這是參考資料，不是本 repo 的實作。** 它沒有在本 repo 執行或驗證過，路徑也寫死在 ChatGPT 的沙箱。真正的實作在 [`../../../assembly_viewer/`](../../../assembly_viewer/README.md)，要重新寫並驗證。

## 檔案

| 檔案 | 用途 | 語言 |
|---|---|---|
| `model.py` | 解析上游 `robot.xml` 的運動樹，算出每個網格的世界座標；把 14 組舵機網格對到關節和 ID（匈牙利演算法） | Python（numpy、scipy） |
| `build.py` | 把 STL 量化成 int16、gzip 後轉 base64，加上 BOM（75 類）、照片、接線圖，填進 `index.template`，產生單一 HTML | Python（numpy） |
| `guide.js` | 14 個組裝步驟：工作項目、驗收條件、參考照片、原文連結 | JavaScript |
| `index.template` | 頁面骨架：步驟欄、3D 工作區、BOM 欄 | HTML |
| `viewer.css` | 頁面樣式（深色） | CSS |
| `viewer.js` | three.js 檢視器：組裝、爆炸、透視三種模式，零件點選、單獨查看、BOM 搜尋、進度記錄 | JavaScript |
| `photos.py` | 下載上游組裝指南的照片並縮圖 | Python（Pillow） |
| `render_overview.py` | 用 Blender 算一張靜態組裝預覽圖，給不能跑 WebGL 的瀏覽器使用 | Blender Python |
| `verify.py` | Playwright 瀏覽器測試（ChatGPT 的環境沒跑成功） | Python |
| `verify_node.cjs` | 用假的 DOM 在 Node 裡測 BOM 篩選、步驟切換等邏輯 | Node.js |

## 抽取方式

1. 對話紀錄裡，ChatGPT 用 `cat > 檔名 <<'TAG'` 寫出檔案。工具依出現順序寫出，後出現的覆蓋先出現的。
2. ChatGPT 之後又用兩段 Python 就地修改檔案。這兩段只在 sha256 符合白名單時才執行：
   - `model.py`：舵機分組改成每個主動舵盤一組，舵機殼件歸給同一 body 內最近的舵盤。
   - `index.template`、`viewer.js`、`viewer.css`：WebGL 無法使用時改顯示靜態預覽圖。
3. 2026-11-13 用兩種方式各抽一次，結果逐位元組相同：一次從 ChatGPT 分享頁的原始 HTML 抽，一次從 repo 裡的對話紀錄抽。全部檔案都通過語法檢查（`python -m py_compile`、`node --check`）。

重新產生：

```bash
python3 -I nous_duck/tools/extract_chatgpt_viewer_src.py \
  nous_duck/docs/handoff/chatgpt_conversation_2026-11.md \
  nous_duck/docs/handoff/chatgpt_viewer_src
```

## 為什麼不能直接跑

- 路徑寫死成 ChatGPT 沙箱的 `/tmp/duck-viewer` 和 `/mnt/data`。
- 缺少它另外下載的檔案：`three.min.js`（0.160.1）、`fflate`（0.8.2），以及 `photos/` 底下的組裝照片。
- 組裝照片來自 GitHub 附件（user-attachments），在本專案的雲端環境會回 403。
- `render_overview.py` 需要 Blender，本專案的雲端環境沒有安裝。
- 還有一些 ChatGPT 在終端機裡直接下的指令沒有寫成檔案（例如下載上游 zip），只留在對話紀錄裡。

## 可以沿用的部分

- `model.py` 的座標換算和舵機 ID 對應邏輯。
- `guide.js` 的 14 步組裝順序和每步的驗收條件。
- `build.py` 的 BOM 清單（零件、數量、精度標示、來源連結）。
- `viewer.js` 的互動設計：三種模式、單獨查看、BOM 與步驟連動。

沿用前請對照上游檔案重新核對，並依根目錄 `CLAUDE.md` 的誠實規則，把 CAD 裡沒有的零件標成「示意」。
