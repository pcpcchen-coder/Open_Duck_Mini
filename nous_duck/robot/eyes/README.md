# 眼睛渲染程式（robot/eyes）

狀態：**可用（單元測試＋預覽圖）**；**未上螢幕、未實機**。GC9A01 的 SPI 驅動還沒寫（等螢幕到貨、E1 實測），這裡不放假的驅動程式。

在 **Raspberry Pi 4** 上執行（目前單板，[ADR-0008](../../docs/adr/ADR-0008-single-board-pi4.md)；畫眼睛屬於感知那一組服務）（[眼睛硬體設計 §3.1](../../hardware/expression_mods/gc9a01_eyes.md#31-為什麼由-pi-4-驅動)）。表情、使用情境、音效規格見 [`docs/eye_expressions.md`](../../docs/eye_expressions.md)。

## 職責

- 輸入：要顯示的表情（來自鴨子本機事件或 Nous 的要求）、真實感測輸入（注視目標、播放音量、電量）、裝置狀態（鏡頭是否串流、實體隱私開關、需要幫忙、夜間）。
- 輸出：每一幀兩張 240×240 RGB 影像（畫面左眼、畫面右眼），以及切換表情時要播的音效**代號**（播不播由之後的行為層決定）。
- 不負責：螢幕驅動、播放聲音、決定該用哪個表情（行為層，規劃中）。

## 結構

| 檔案 | 內容 |
|---|---|
| `duck_eyes/sdf.py` | 2D 有號距離場形狀（圓、橢圓、弧、多邊形、愛心、螺旋、水滴），numpy 向量化 |
| `duck_eyes/params.py` | 單眼參數 `EyeParams`、調色盤（青色保留）、插值 |
| `duck_eyes/expressions.py` | 25 個表情與音效代號 |
| `duck_eyes/animator.py` | 過場、自動眨眼、眼睛飄動、動作型表情（眨單眼） |
| `duck_eyes/status.py` | 狀態環：依實際裝置狀態決定顏色（ADR-0006 §4.2） |
| `duck_eyes/render.py` | 畫出表情層，再疊上狀態環（最上層） |
| `duck_eyes/policy.py` | 誠實規則：Nous 能叫哪些表情；鏡頭開著時不閉眼 |
| `duck_eyes/panel.py` | 轉 RGB565、算局部更新範圍（給之後的 SPI 驅動用） |
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

## 驗證

見 [`docs/validation/eyes-render-2026-11-18.md`](../../docs/validation/eyes-render-2026-11-18.md)。驗證層級：單元測試＋預覽圖（雲端容器）。Pi 4 上的速度、真實螢幕的顏色與亮度都還沒測。
