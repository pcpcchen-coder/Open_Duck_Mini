"""收音：用系統的 `arecord`（alsa-utils）從 ALSA 裝置讀 PCM，**只經過管線進記憶體，不寫檔**。

鴨子的麥克風（2026-11-26 在 Pi 上查）：reSpeaker XVF3800 4-Mic Array，ALSA 卡名 `Array`，
收音只有一種格式：S16_LE、2 聲道、16000 Hz。兩個聲道都是晶片處理後的輸出（波束、降噪、回音消除）；
哪個聲道適合喚醒詞見 `docs/validation/voice-duck-side-2026-11-26.md`。

隱私（ADR-0003 §6）：這個模組不提供任何存檔功能；讀到的音訊交給呼叫端，在記憶體裡用完就丟。
"""

from __future__ import annotations

import subprocess

import numpy as np

MIC_DEVICE = "plughw:CARD=Array,DEV=0"
MIC_RATE = 16000
MIC_CHANNELS = 2


class CaptureError(RuntimeError):
    pass


class ArecordSource:
    """`read()` 每次回傳一框（frames×channels 的 float32，−1～1）。裝置消失或 arecord 結束時丟 CaptureError。"""

    def __init__(self, device: str = MIC_DEVICE, rate: int = MIC_RATE, channels: int = MIC_CHANNELS, frame_ms: int = 20) -> None:
        self.device, self.rate, self.channels = device, rate, channels
        self.frame = rate * frame_ms // 1000
        self._bytes = self.frame * channels * 2
        try:
            self._proc = subprocess.Popen(
                ["arecord", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", str(channels),
                 "--buffer-time", "100000", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        except FileNotFoundError as e:
            raise CaptureError("找不到 arecord（需要 alsa-utils）") from e

    def read(self) -> np.ndarray:
        assert self._proc.stdout is not None
        buf = b""
        while len(buf) < self._bytes:
            chunk = self._proc.stdout.read(self._bytes - len(buf))
            if not chunk:
                err = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip() if self._proc.stderr else ""
                raise CaptureError(f"arecord 結束（{self.device}）：{err}")
            buf += chunk
        return np.frombuffer(buf, dtype="<i2").reshape(-1, self.channels).astype(np.float32) / 32768.0

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        for f in (self._proc.stdout, self._proc.stderr):
            if f is not None:
                f.close()
