# robot/perception：鏡頭、人臉方位、視覺連動、雙目估距

狀態：**程式與測試完成到「硬體一到就能接」的程度；沒有鏡頭，全部只用合成資料驗證**（2026-11-25，D 線 D1～D4）。
驗證層級：單元測試（67 項）＋合成資料模擬＋Pi 4 上的運算量測（輸入是合成畫面）。**未實機**。
紀錄：[`docs/validation/perception-2026-11-25.md`](../../docs/validation/perception-2026-11-25.md)。

## 職責

在鴨子的 Pi 4 上，把鏡頭畫面變成「人在哪個方向、多遠」，餵給頭部與走路的控制器。

- 只輸出**方位、距離、信心**；不輸出影像、不算臉部特徵、不做身分辨識（找誰是誰由 Nous 做，ADR-0003）。
- 影像只在記憶體裡處理，**不寫檔、不進 log、不外傳**（`tests/test_camera_synthetic.py` 會檢查原始碼沒有寫影像檔的呼叫）。
- 感知結果只送到本機 loopback。

## 結構

| 檔案 | 內容 | Step |
|---|---|---|
| `duck_perception/camera.py` | `CameraModel`（內參）、`StereoRig`（外參）、`Frame`、`FrameSource` 介面；AR0144 名目值（未校準） | D1 |
| `duck_perception/synthetic.py` | **mock**：`SyntheticStereoSource`（程式畫的示意臉＋已知真值的校正後雙目畫面）、`TruthDetector`（真值加雜訊當偵測） | D1 |
| `duck_perception/face_detect.py` | YuNet（OpenCV `FaceDetectorYN`）包裝；缺模型時丟 `ModelMissing`，不造假 | D2 |
| `duck_perception/target.py` | 像素→方位、選人（最大／最近中心／最接近聲源）、黏著、平滑、遺失處理 | D2 |
| `duck_perception/link.py` | 與 A 線約定的 UDP 介面（`127.0.0.1:8793`）：編碼、檢查、傳送 | D2 |
| `duck_perception/pipeline.py` | 每張影像：偵測→方位（＋雙目距離）→選人→送 `face` | D2 |
| `duck_perception/closed_loop.py` | **模擬**：合成畫面→偵測→[`behaviors/look_at.py`](../behaviors/look_at.py)→一階延遲的頭 | D2 |
| `duck_perception/follow.py` | 視覺連動走路控制器：轉身面向、走近到指定距離 | D3 |
| `duck_perception/follow_sim.py` | **純運動學模擬**（差速模型，不是步態模擬） | D3 |
| `duck_perception/stereo_depth.py` | 臉部區塊的雙目視差→距離；量不到回 `None` 與原因 | D4 |
| `tools/fetch_models.py` | 下載 YuNet 並核對 SHA-256 | D2 |
| `tools/bench_detector.py` | 量偵測與整條處理的時間、CPU、記憶體（合成畫面） | D2 |
| `tools/stereo_error_table.py` | 合成雙目估距誤差表 | D4 |

## 怎麼跑

```bash
cd nous_duck/robot/perception
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python tools/fetch_models.py     # 沒有它會略過 2 項 YuNet 測試
.venv/bin/python -m pytest tests -q         # 67 passed
.venv/bin/python tools/stereo_error_table.py
```

Pi 4（不動 `~/duck/runtime-venv`；D 線的檔案都在 `~/duck/d-line/`）：

```bash
rsync -a --delete --exclude .venv --exclude models --exclude __pycache__ --exclude .pytest_cache nous_duck/robot/perception/ duck-pi4:duck/d-line/perception/
rsync -a --delete --exclude __pycache__ nous_duck/robot/behaviors/ duck-pi4:duck/d-line/behaviors/
ssh duck-pi4 bash -s < nous_duck/robot/deploy/pi4/setup_perception.sh
ssh duck-pi4 'cd ~/duck/d-line/perception && ~/duck/perception-venv/bin/python tools/bench_detector.py --threads 1'
```

Python：numpy 2.5.x 需要 3.12 以上；Pi 4（Debian 13）是 3.13.5，Mac 開發用 uv 的 3.13。程式本身沒有用 3.11 之後才有的語法。

## 介面

### 影像來源（D1）

`FrameSource.read() -> Frame | None`。`Frame`：`seq`、`t_capture`（秒，單調時鐘）、`left`／`right`（BGR uint8；單眼時 `right=None`）、`mock`。鏡頭壞掉要丟例外，不能回傳舊畫面。

### 給 duckd 的 UDP（D2；A 線約定）

`127.0.0.1:8793`，一個 datagram 一則 JSON：

```json
{"v":1,"kind":"face","bearing_yaw_rad":0.12,"bearing_pitch_rad":-0.05,"distance_m":1.48,"confidence":0.91,"t_ms":123456,"mock":true}
```

- `face` 的方位相對**鏡頭光軸**，左為正、上為正；`distance_m` 是到鏡頭的直線距離，量不到是 `null`（**不用臉寬猜**，除非明確開 `allow_mono_distance`）。
- 沒有目標時**不送**；接收端看 `t_ms` 判斷過期（D3 預設 0.5 秒）。
- `t_ms` 是拍攝時間（來源的單調時鐘，毫秒）。接收端若要換算延遲，雙方要用同一個時鐘（實機來源會用 `time.monotonic()`）。
- 合成來源一律 `mock:true`。

### 視覺連動走路（D3）

```python
from duck_perception.follow import FollowController, FollowMode, FollowObservation
ctrl = FollowController(mode=FollowMode.FACE)      # FACE＝只原地轉身（ADR-0007 F1）；APPROACH＝走近到 1.0 m
ctrl.activate()
cmd = ctrl.step(t, FollowObservation(t_capture, bearing_yaw, bearing_pitch, distance_m, confidence), head_yaw, head_pitch)
# cmd.vx（m/s）、cmd.yaw_rate（rad/s，左為正）、cmd.head_yaw_target、cmd.head_pitch_target、cmd.state、cmd.reason
```

- 每個控制週期呼叫一次（50 Hz）；`obs` 給最近一次的觀測（可以重複給同一筆，控制器看時間戳）；`head_yaw` 是頭部目前相對身體的角度。
- 遺失／過期／信心低 → 立刻 0；距離未知或超過 3 m → 不前進；預設不後退；沒面向人之前不前進。
- 輸出是**請求**：A 線的 safety 仍要夾限。這個控制器不看障礙、落差、禁區，**不能單獨拿來讓鴨子走路**；C 線導航要在外面包一層。
- `yaw_rate` 正值＝往左轉；上游 runtime 的 `ang_vel` 正負號還沒實機確認（`look_at.py` 也有同樣的註記）。

## 等硬體

| 等什麼 | 到貨後要做 |
|---|---|
| AR0144 雙目鏡頭 | 寫 `Ar0144Source`（UVC、2560×720 MJPG 左右併排切割、`time.monotonic()` 時間戳）；量擷取與解碼的 CPU；雙目校正（V1）取代名目內參；用真人量 YuNet 在 320×180／640×360 的偵測距離；重量估距誤差 |
| 鏡頭裝上頭 | 光軸相對頭部關節的偏移；舵機回讀當 `gaze_at_capture`；頭轉動時的模糊 |
| 麥克風陣列（XVF3800） | `sound` 訊息（DOA）；`SelectPolicy.SOUND` 實測 |
| 實機走路（足底開關、IMU 校準、使用者在場） | D3 的增益、上限與正負號；走路時頭晃對偵測的影響 |

## 第三方

| 項目 | 授權 | 取得方式 |
|---|---|---|
| YuNet `face_detection_yunet_2023mar.onnx`（OpenCV Zoo） | MIT | `tools/fetch_models.py`（釘 Hugging Face revision＋SHA-256，與 AIOS 相同）；不進版控 |
| opencv-python-headless 5.1.0.95 | Apache-2.0 | PyPI |
| numpy 2.5.3 | BSD-3-Clause | PyPI |

測試影像全部是程式畫的示意臉（`synthetic.draw_face`），沒有任何真人影像。
