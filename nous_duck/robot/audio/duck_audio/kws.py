"""D7 喚醒詞（spike）：sherpa-onnx KWS 的包裝，關鍵詞由設定檔決定，含自我觸發防護的掛點。

- 引擎與版本線沿用 AIOS：sherpa-onnx v2.0.1（Apache-2.0）、zipformer KWS 模型 zh-en-3M。
  模型用 `tools/fetch_models.py` 下載，不進版控（授權狀況見該檔）。
- **喚醒詞還沒決定**：關鍵詞、提升分數、門檻都從 JSON 設定讀（`config/wake_keywords.candidates.json`
  是量測用的候選，不是產品設定）。
- 音訊只在記憶體裡經過：這個模組不寫檔、不留緩衝、不送出音訊；輸出只有「哪個關鍵詞、在第幾秒」。
- 自我觸發防護（ADR-0010 §4）：鴨子自己在出聲時（`set_playing(True)`）與之後一小段時間內，
  偵測到的關鍵詞不算喚醒（計入 `suppressed`）。**沒有麥克風，這段只有單元測試**；
  實際要搭配 XVF3800 的回音消除，到貨後再量。

驗證層級：檔案輸入（合成語音）的運算量測。**沒有麥克風；喚醒率與誤喚醒率沒有量，也不能宣稱。**
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

AUDIO_ROOT = Path(__file__).resolve().parents[1]
KWS_RATE = 16000
MODEL_DIRS = {
    "kws-zh-en": ("sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20", "encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx", "decoder-epoch-13-avg-2-chunk-16-left-64.onnx", "joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx"),
    "kws-wenetspeech": ("sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01", "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx", "decoder-epoch-12-avg-2-chunk-16-left-64.onnx", "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
}


class WakeRuntimeMissing(RuntimeError):
    """沒有 sherpa-onnx 或模型檔：照實報錯（對應 AIOS 的 `runtime_missing`），不假裝在聽。"""


@dataclass(frozen=True)
class WakeConfig:
    model: str
    keywords_score: float
    keywords_threshold: float
    num_threads: int
    entries: tuple[dict[str, Any], ...]
    status: str = "unconfigured"

    @classmethod
    def load(cls, path: Path | str) -> "WakeConfig":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = tuple(d["entries"])
        ids = [e["id"] for e in entries]
        if not entries or len(set(ids)) != len(ids):
            raise ValueError("關鍵詞清單是空的或 id 重複")
        for e in entries:
            if not e["id"].replace("_", "").isalnum() or not e["tokens"].strip():
                raise ValueError(f"關鍵詞格式不對：{e}")
        if d["model"] not in MODEL_DIRS:
            raise ValueError(f"不認得的模型：{d['model']}")
        return cls(d["model"], float(d["keywords_score"]), float(d["keywords_threshold"]), int(d.get("num_threads", 1)), entries, d.get("status", "unconfigured"))

    def keywords_text(self) -> str:
        """sherpa-onnx 的關鍵詞檔：`tokens [:提升分數] [#門檻] @ID`，一行一個。"""
        lines = []
        for e in self.entries:
            line = e["tokens"].strip()
            if e.get("boost") is not None:
                line += f" :{e['boost']}"
            if e.get("threshold") is not None:
                line += f" #{e['threshold']}"
            lines.append(f"{line} @{e['id']}")
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class WakeEvent:
    keyword_id: str
    #: 偵測回報時，已經送進引擎的音訊長度（秒）。
    t_stream_s: float


def build_spotter(cfg: WakeConfig, models_dir: Path | None = None):
    try:
        import sherpa_onnx
    except ImportError as e:
        raise WakeRuntimeMissing("沒有安裝 sherpa-onnx（requirements-kws.txt）") from e
    name, enc, dec, joi = MODEL_DIRS[cfg.model]
    d = (models_dir or AUDIO_ROOT / "models") / name
    for f in (enc, dec, joi, "tokens.txt"):
        if not (d / f).exists():
            raise WakeRuntimeMissing(f"找不到 {d / f}；先執行 tools/fetch_models.py {cfg.model}")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as kf:
        kf.write(cfg.keywords_text())
    try:
        return sherpa_onnx.KeywordSpotter(
            tokens=str(d / "tokens.txt"),
            encoder=str(d / enc),
            decoder=str(d / dec),
            joiner=str(d / joi),
            keywords_file=kf.name,
            num_threads=cfg.num_threads,
            keywords_score=cfg.keywords_score,
            keywords_threshold=cfg.keywords_threshold,
            provider="cpu",
        )
    finally:
        Path(kf.name).unlink(missing_ok=True)


class WakeEngine:
    """串流喚醒詞偵測。`spotter` 可以注入（測試用假物件）；預設用 sherpa-onnx。"""

    def __init__(self, cfg: WakeConfig, spotter=None, holdoff_s: float = 0.5, reset_on_silence_s: float | None = 0.7, silence_rms: float = 3e-3) -> None:
        self.cfg = cfg
        self._kws = spotter if spotter is not None else build_spotter(cfg)
        self._stream = self._kws.create_stream()
        self._samples = 0
        #: 鴨子停止出聲後，還要再壓住偵測多久（喇叭餘音、緩衝裡還沒處理完的聲音）。未校準。
        self.holdoff_s = holdoff_s
        self._playing = False
        self._quiet_since_s: float | None = 0.0
        self.suppressed = 0
        #: 連續安靜這麼久就重置解碼串流。原因（2026-11-25 用合成語音量到）：串流一直不重置時，
        #: 前面有別的句子，接著說的關鍵詞容易漏（17 句只回報 7 句；重置後 13 句）。
        #: 安靜的判斷是每塊的 RMS 低於 silence_rms：**未校準**，真的麥克風要依底噪重新定，或改用 VAD。
        self.reset_on_silence_s = reset_on_silence_s
        self.silence_rms = silence_rms
        self._quiet_s = 0.0
        self._reset_done = True
        self.silence_resets = 0

    def set_playing(self, playing: bool) -> None:
        """由播放端告知鴨子是否正在出聲（`DuckAudioOut.is_playing`）。"""
        if self._playing and not playing:
            self._quiet_since_s = self._samples / KWS_RATE
        self._playing = playing

    @property
    def stream_time_s(self) -> float:
        return self._samples / KWS_RATE

    def _guarded(self) -> bool:
        if self._playing:
            return True
        return self._quiet_since_s is not None and self.stream_time_s - self._quiet_since_s < self.holdoff_s and self._quiet_since_s > 0

    def accept(self, samples_16k: np.ndarray) -> list[WakeEvent]:
        """送進一段 16 kHz 單聲道 float 音訊，回傳這段時間內的喚醒事件（可能是空的）。"""
        self._stream.accept_waveform(KWS_RATE, np.asarray(samples_16k, dtype=np.float32))
        self._samples += len(samples_16k)
        events: list[WakeEvent] = []
        if self.reset_on_silence_s is not None and len(samples_16k):
            x = np.asarray(samples_16k, dtype=np.float32)
            if float(np.sqrt(np.mean(x * x))) < self.silence_rms:
                self._quiet_s += len(x) / KWS_RATE
            else:
                self._quiet_s = 0.0
                self._reset_done = False
        pending_reset = self.reset_on_silence_s is not None and not self._reset_done and self._quiet_s >= self.reset_on_silence_s
        while self._kws.is_ready(self._stream):
            self._kws.decode_stream(self._stream)
            result = self._kws.get_result(self._stream)
            if result:
                self._kws.reset_stream(self._stream)
                if self._guarded():
                    self.suppressed += 1
                else:
                    events.append(WakeEvent(result, self.stream_time_s))
        if pending_reset:
            # 先把這一塊解完（關鍵詞常在尾端的靜音裡才被回報），再重置
            self._kws.reset_stream(self._stream)
            self._reset_done = True
            self.silence_resets += 1
        return events
