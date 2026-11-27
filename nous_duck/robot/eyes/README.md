# 眼睛渲染程式（robot/eyes）

狀態：渲染程式**可用（單元測試＋預覽圖）**；GC9A01 驅動 `gc9a01.py` **實機點亮過（Pi 4，桌上，兩片，20 MHz）**，還沒裝上頭、沒和舵機一起測。duckd 用 `--eyes-hw` 接上這個驅動（2026-11-28，Pi 上實測，加速後對話中約 11 fps、idle 15 fps，見 [`eyes-duckd-2026-11-28.md`](../../docs/validation/eyes-duckd-2026-11-28.md)）。紀錄見 [`eyes-render-speed-2026-11-27.md`](../../docs/validation/eyes-render-speed-2026-11-27.md)。

在 **Raspberry Pi 4** 上執行（目前單板，[ADR-0008](../../docs/adr/ADR-0008-single-board-pi4.md)；畫眼睛屬於感知那一組服務）（[眼睛硬體設計 §3.1](../../hardware/expression_mods/gc9a01_eyes.md#31-為什麼由-pi-4-驅動)）。表情、使用情境、音效規格見 [`docs/eye_expressions.md`](../../docs/eye_expressions.md)。

## 職責

- 輸入：要顯示的表情（來自鴨子本機事件或 Nous 的要求）、真實感測輸入（注視目標、播放音量、電量）、裝置狀態（鏡頭是否串流、實體隱私開關、需要幫忙、夜間）。
- 輸出：每一幀兩張 240×240 RGB 影像（畫面左眼、畫面右眼），以及切換表情時要播的音效**代號**（播不播由之後的行為層決定）。
- 不負責：播放聲音、決定該用哪個表情（行為層，規劃中）。螢幕驅動在 `gc9a01.py`，只負責把畫好的影像送上螢幕。

## 結構

| 檔案 | 內容 |
|---|---|
| `duck_eyes/sdf.py` | 2D 有號距離場形狀（圓、橢圓、弧、多邊形、愛心、螺旋、水滴），numpy 向量化 |
| `duck_eyes/params.py` | 單眼參數 `EyeParams`、調色盤（青色保留）、插值 |
| `duck_eyes/expressions.py` | 25 個表情與音效代號 |
| `duck_eyes/animator.py` | 過場、自動眨眼、眼睛飄動、動作型表情（眨單眼） |
| `duck_eyes/status.py` | 狀態環：依實際裝置狀態決定顏色（ADR-0006 §4.2） |
| `duck_eyes/render.py` | 畫出表情層，再疊上狀態環（最上層）；每個形狀只算自己的範圍、`EyeRenderer` 沿用沒變的表情層 |
| `duck_eyes/policy.py` | 誠實規則：Nous 能叫哪些表情；鏡頭開著時不閉眼 |
| `duck_eyes/panel.py` | 轉 RGB565、算局部更新範圍（單一矩形 `dirty_rect`、格子 `dirty_spans`） |
| `duck_eyes/gc9a01.py` | 兩片 GC9A01 的 SPI 驅動（共用 SPI0、CE0／CE1；DC、RES、BLK 共用）、只送變動的格子、測試畫面與動畫的命令列 |
| `duck_eyes/preview.py` | 產生總覽圖、狀態環圖、動畫 GIF、量渲染時間 |

## 用法

```bash
cd nous_duck/robot/eyes
pip install -r requirements-dev.txt
python -m pytest tests -q
python -m duck_eyes.preview --out /tmp/eyes --bench
```

```python
from duck_eyes import DeviceState, EyeAnimator, Inputs, render_frame

anim = EyeAnimator("neutral")
anim.set_expression("happy", t=1.0)
frame = anim.frame(1.2, Inputs(gaze=(0.3, -0.1)))      # 注視目標要來自真實的人臉偵測
left, right = render_frame(frame, DeviceState(camera_streaming=True), 1.2)
```

## 在 Pi 上點亮螢幕

前提：`config.txt` 有 `dtparam=spi=on`（2026-11-27 已加）、使用者在 `spi`、`gpio` 群組。執行環境用系統 Python（apt 的 `python3-spidev`、`python3-libgpiod`）加 numpy：

```bash
cd ~/duck && ~/duck/uv-tool/bin/uv venv --python /usr/bin/python3 --system-site-packages eyes-venv
~/duck/uv-tool/bin/uv pip install --python eyes-venv/bin/python -r <repo>/nous_duck/robot/eyes/requirements.txt
cd <放 duck_eyes 的資料夾>
~/duck/eyes-venv/bin/python -m duck_eyes.gc9a01 pattern          # 左眼紅綠藍→十字、右眼藍
~/duck/eyes-venv/bin/python -m duck_eyes.gc9a01 demo --cycle --seconds 100
```

- 「左眼」是站在鴨子面前看到的左邊（CE0，鴨子自己的右眼）。裝反了加 `--swap`；螢幕轉了角度用 `--rotation 90/180/270`（只有 0 實機看過）。
- 預設 20 MHz。沒加 SCL 串聯電阻與 BLK 下拉；開機與程式結束後背光可能亮著，這是硬體的事。
- 面板沒有回讀：程式只知道資料送出去了，畫面對不對要人看。
- 不要和其他用 GPIO 5／6／26 或 SPI0 的程式同時跑（例如開了 `--eyes-hw` 的 duckd：先 `sudo systemctl stop duckd`）。

## 驗證

見 [`docs/validation/eyes-render-2026-11-18.md`](../../docs/validation/eyes-render-2026-11-18.md)。驗證層級：單元測試＋預覽圖（雲端容器）。2026-11-27 起另見 [`eyes-render-speed-2026-11-27.md`](../../docs/validation/eyes-render-speed-2026-11-27.md)：Pi 4 上兩眼一幀從 131 ms 降到約 27 ms（畫面逐像素比對相同）、兩片實體螢幕點亮（顏色順序、方向經使用者目視確認）。亮度、耗電、裝上頭後的表現還沒測。
