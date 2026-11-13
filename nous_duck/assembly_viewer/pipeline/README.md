# assembly_viewer/pipeline

狀態：**已實作**（2026-11-13）。驗證層級：單元測試＋MuJoCo 交叉驗證＋無頭瀏覽器目視檢查，見[驗證紀錄](../../docs/validation/viewer-pipeline-2026-11-13.md)。

## 職責

把上游 CAD 轉成前端可以直接載入的場景資料：每個零件是什麼、放在哪裡、爆炸時往哪裡移，以及壓縮後的網格。上游檔案一律唯讀。

## 使用方式

```bash
cd nous_duck/assembly_viewer/pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # 只建置不測試的話用 requirements.txt
python -m viewer_pipeline               # 輸出到 ../dist/build/（不進版控）
python -m pytest ../tests/pipeline      # 72 項測試
```

建置約 2 秒，會印出零件數量、高度、BOM、各步驟裝上的零件數，以及 14 顆舵機的對應結果。任何檢查沒通過時會直接失敗，不會產生半套的輸出。

## 輸入

| 檔案 | 用途 |
|---|---|
| 上游 `mini_bdx/robots/open_duck_mini_v2/robot.xml` 與同目錄 STL | 運動樹、零件位置、網格（單位：公尺） |
| 上游 `print/*.stl` | CAD 沒有擺放位置的 7 件列印件（單位：毫米） |
| 上游 `docs/configure_motors.md` | 舵機 ID 表（直接讀原文，不另抄一份） |
| 上游 `docs/print_guide.md` | 列印件種類與數量，用來核對 |
| [`../data/cad_parts.yaml`](../data/cad_parts.yaml) | 每個 CAD 網格的類別、列印檔、中英文名稱 |
| [`../data/bom.yaml`](../data/bom.yaml) | 採購件、耗材與工具（列印件自動產生） |
| [`../data/steps.yaml`](../data/steps.yaml) | 組裝步驟 |

## 輸出：`dist/build/scene.json`＋`dist/build/meshes.bin`

座標系：**+X 左、+Y 上、+Z 前**（three.js 慣用的 Y 朝上），單位毫米。Y = 0 是腳底最低點，X、Z 以整機外框中心為 0。姿態是所有關節 0 度，也就是上游 CAD 的零位。

`scene.json`（schema `nous-duck/viewer-scene@1`）的主要欄位：

| 欄位 | 內容 |
|---|---|
| `sources` | 輸入檔的 sha256（換 commit 但上游檔案沒變時，輸出完全相同） |
| `summary` | 高度、外框、零件數量（依類別）、網格數量、三角形數、量化誤差上限、`meshes.bin` 大小 |
| `meshes` | 每種網格在 `meshes.bin` 裡的位置、頂點數、索引型別、還原參數、來源檔與 sha256 |
| `parts` | 138 個零件實例：`id`、`mesh`、`body`、`kind`、中英文名稱、`print_stl`、`servo_id`、`placement`（`cad` 或 `print_frame`）、`identification`（推定依據）、顏色、`position_mm`、`quaternion_xyzw`（three.js 順序）、`center_mm`、`explode_mm`、`bom_id`、`step`（在第幾步裝上，從 0 起算） |
| `servos` | 14 顆 STS3215：ID、關節、左右、5 個組成零件，以及舵盤到轉軸和關節點的距離 |
| `joints` | 16 個關節（含 2 個天線關節）：位置、轉軸、範圍、對應的舵機 ID |
| `bodies` | body 樹（父子關係與關節） |
| `bom` | 71 項 BOM（列印件 36 種，加上 `bom.yaml` 的 35 項）；每項的 `parts` 是它在 3D 中的零件 id，3D 中沒有的零件附 `scene_note_zh` |
| `cad_without_bom` | CAD 有、但上游 BOM 和列印清單都沒有的零件（目前只有天線）與原因 |
| `steps` | 17 個組裝步驟：`adds`（這一步裝上的零件 id）、`focus`、`bom`、中英文操作與檢查、上游連結與參考圖網址 |

`meshes.bin`：每種網格依序存「頂點區」和「索引區」，每區起點對齊 4 bytes，全部 little-endian。

- **頂點區**：uint16 × 3 × 頂點數，在網格自己的外框內量化成 65535 階。還原方式：`位置 = bbox_min_mm + q × step_mm`。
- **索引區**：頂點數不超過 65535 時用 uint16，否則用 uint32。
- **法向量**：不存，前端用平面著色（flat shading）。

## 作法

1. **運動樹**（`kinematics.py`）：遞迴累加 body 的 `pos` 和 `quat`，算出每個 geom 的世界座標。只支援上游實際用到的寫法，遇到 `euler`、網格 `scale` 等其他寫法會直接報錯，不會默默算錯。
2. **舵機**（`servos.py`）：先把每顆 STS3215 的 5 個網格組成一個單位，再對到關節。條件是主動舵盤中心必須在關節轉軸上（≤ 0.1 mm），而且離關節點夠近（≤ 10 mm）。左右腿的髖俯仰、膝、踝轉軸剛好共線，只看「在轉軸上」會分不出左右，所以兩個條件都要。每個關節必須剛好一顆候選，否則失敗。
3. **零件目錄**（`catalog.py`）：`cad_parts.yaml` 必須涵蓋每個 CAD 網格，列印件必須指向存在的列印檔。
4. **列印件數量**：模型裡的列印件依檔名計數，必須和 `print_guide.md` 完全相同（36 種、51 件），否則失敗。
5. **CAD 沒有位置的 7 件**（眼睛、燈、喇叭相關）：上游 `print/` 的 STL 和 CAD 網格匯出在同一座標系，所以套用頭殼的變換來擺放，並標成 `placement: print_frame`。
6. **BOM**（`bom.py`）：讀 `bom.yaml`，自動加上 36 種列印件，檢查每個 3D 零件剛好屬於一個 BOM 項目。
7. **組裝步驟**（`steps.py`）：讀 `steps.yaml`，把選擇器（`selectors.py`）展開成零件 id，檢查每個 3D 零件剛好在一步裡裝上。
8. **網格**（`meshes.py`）：量化、去除重複頂點、打包。同一種網格只存一份。
9. **爆炸向量**（`explode.py`）：每個有關節的子組件沿「離開上一層中心」的方向移 40 mm，並沿運動樹往下累加；組件內的零件再沿「離開組件中心」的方向移 25 mm。同一顆舵機的 5 個網格一起移動。

## 已知限制

- **零件不完整**：CAD 沒有足底開關、喇叭、LED、線材、螺絲與熱熔螺帽。它們列在 BOM，並寫明 3D 中為什麼沒有；目前沒有畫示意形狀，以免猜錯位置。
- **爆炸距離待調**：目前是固定值，沿腿累加後，腳底板會移得比較遠。前端可以依比例調整，實際效果在前端批次再調。
- **只有零位姿態**：檢視器目前只顯示零位。
- **網格大小**：`meshes.bin` 約 3.7 MB。最大的是 STS3215 下殼，約 10 萬個三角形、占 25%；其次是 STS3215 上殼，占 10%。要不要簡化網格，在前端批次依單一 HTML 的檔案大小再決定。
