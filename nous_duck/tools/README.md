# 開發工具（tools）

| 檔案 | 用途 | 狀態 |
|---|---|---|
| [`check_upstream_untouched.sh`](check_upstream_untouched.sh) | 檢查與上游 `v2` 的差異只在 `nous_duck/`、`CLAUDE.md`、`.github/`；CI 會執行 | 可用 |
| [`chatgpt_share_to_md.py`](chatgpt_share_to_md.py) | 把 ChatGPT 分享頁 HTML 轉成 Markdown 對話紀錄（只用標準函式庫） | 可用 |
| [`extract_chatgpt_viewer_src.py`](extract_chatgpt_viewer_src.py) | 從 ChatGPT 對話紀錄抽出檢視器原始碼；就地修改的腳本只執行 sha256 白名單內的兩段（只用標準函式庫） | 可用 |
| [`mic_placement_cad.py`](mic_placement_cad.py) | 麥克風陣列放置的 CAD 檢查：脖子後方對頭部抬頭角度的影響、頭頂空間與天線距離、傾斜與視差誤差（需要 numpy，先跑 pipeline） | 可用 |
| [`compare_chatgpt_viewer.py`](compare_chatgpt_viewer.py) | 逐件比對 ChatGPT 版檢視器 HTML 與本 repo pipeline 的零件擺放、舵機 ID，列出左右腿膝踝舵機在內側或外側（需要 numpy） | 可用 |
| [`eye_display_fit.py`](eye_display_fit.py) | GC9A01 圓形螢幕當眼睛：從上游 `print/*.stl` 唯讀量眼孔、螺絲孔、頭殼內高，推算看得到的像素與 Pi 4 SPI 頻寬；[眼睛設計](../hardware/expression_mods/gc9a01_eyes.md)的數字來源（只用標準函式庫） | 可用（STL 量測＋推算，非實物量測） |
| [`stereo_geometry.py`](stereo_geometry.py) | AR0144 雙目鏡頭裝在鴨子頭上的名目幾何推算（深度解析度、低頭看得到的地面、看人臉的仰角、物體像素大小）；[雙目視覺規劃](../docs/stereo_vision_plan.md)的數字來源（只用標準函式庫） | 可用（推算，非量測） |
| [`follow_geometry.py`](follow_geometry.py) | 「跟著我來」的名目推算（人與鴨子的速度落差、多久跟丟、跟隨時看得到人的哪一段、抬頭時腳前看不到的地面）；[ADR-0007](../docs/adr/ADR-0007-follow-me-and-wait-here.md) 的數字來源（只用標準函式庫，沿用 `stereo_geometry.py` 的鏡頭幾何） | 可用（推算，非量測） |
| [`battery_budget.py`](battery_budget.py) | 低電量回充的名目推算（回家要多少電、L1～L4 電量等級的門檻、各等級站著還能撐多久）；[ADR-0012](../docs/adr/ADR-0012-low-battery-return-interaction.md) 的數字來源（只用標準函式庫） | 可用（推算，非量測） |
| [`servo_bench.py`](servo_bench.py) | 舵機工作台：STS3215 逐顆設定 ID 與零位（參數同上游 `configure_motor.py`）、掃描、14 軸檢查、限速回零位、放鬆、即時看位置；不用先裝 Runtime，Mac／Pi 都能跑（需要 pyserial；`selftest` 不需要） | 可用（模擬匯流排檢查通過；實機已設定 14 顆） |

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

# 舵機工作台（第一次用先裝 pyserial：python3 -m pip install --user pyserial）
python3 nous_duck/tools/servo_bench.py selftest   # 不接硬體的內建檢查
python3 nous_duck/tools/servo_bench.py ports      # 找舵機板序列埠
python3 nous_duck/tools/servo_bench.py wizard     # 14 顆逐顆設定，可中斷續做
python3 nous_duck/tools/servo_bench.py check --scan-extra   # 全部接上後檢查

# 麥克風陣列放置的 CAD 檢查（先跑 pipeline）
python3 -I nous_duck/tools/mic_placement_cad.py

# GC9A01 眼睛的尺寸核對與 SPI 頻寬（輸出 Markdown 表格；--check 只跑內建檢查）
python3 -I nous_duck/tools/eye_display_fit.py
```

### 舵機工作台說明

- `wizard` 依 ID 10→33 逐顆提示（提示音＋整行色塊）。每顆會先掃描 0–253，**匯流排上超過一顆就拒絕寫入**；寫入 mode／最大加速度／加速度／P／I／D＝0／0／0／32／0／0 並改 ID，回讀確認後開扭力轉到 2048（0 rad），舵機保持零位讓你裝舵盤。進度寫在 `servo_setup_log.json`，中斷後再跑會跳過已完成的顆。
- 和上游 `configure_motor.py` 只有一處不同：寫完 EEPROM 後把 lock 設回 1（Feetech 的解鎖→寫入→上鎖流程），上游停在 lock＝0。
- 電壓低於 6.0 V 拒絕設定；高於 7.4 V（C001 型號頁上限）只警告，依[繁中組裝指引第 5 步](../docs/build_log/Open_Duck_Mini_v2_Assembly_Guide_zh-TW.md#5-接線與分段上電)確認批次規格。
- `center` 用限速（預設 400 步／秒）移動，結束後把速度暫存器設回 0，不影響 Runtime。組裝後使用前先架空機體。
- 讀寫沒等到回應時自動重送 2 次（掃描的 ping 不重送）。實機上 Mac＋CH343 遇過一次寫入回應掉包。
- 驗證層級：
  - `selftest` 的模擬匯流排：含會回送封包的板子、回應掉包、兩顆同時接、低電壓、缺軸。
  - 實機（2026-11-21）：Waveshare Bus Servo Adapter (A) V1.1（CH343，跳線 B）接 Mac，1 顆 STS3215（型號代碼 777）由 ID 1 設成 10，回讀參數相符、lock＝1，零位 2049（誤差 +1 步），電壓 7.0 V。`scan`、`setup`、單顆 `check`、`center` 已在實機跑過；`wizard` 完成 14 顆（[設定紀錄](../docs/build_log/servo_setup_2026-11-21.md)）。`monitor`、`relax`、14 顆同時在線的 `check` 還沒在實機跑過。
