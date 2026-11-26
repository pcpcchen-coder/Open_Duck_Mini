"""設定的 schema：每一項的型別、預設值、範圍、誰讀它、怎麼生效、目前做到哪。

這個檔案是**唯一**定義設定項目的地方（ADR-0019 §2.1）。只用標準函式庫，鴨子上每個服務都能匯入。

- `status`：`implemented`＝有執行中的程式會讀這一項；`planned`＝還沒有程式讀（頁面顯示但停用）；
  `hardware_missing`＝硬體還沒到（頁面顯示但停用）。後兩種**任何來源都不能寫**，避免做出假開關。
- `apply`：`live`＝服務約 1 秒內自己重新讀取；`restart`＝要重啟 `consumer` 那個服務才生效。
- `kind`：`preference`＝使用者偏好（存 `settings.json`）；`measurement`＝機體量測值（存 `calibration.json`，
  「回復預設」不會動它）。
- `tighten`：只有隱私設定有。由寬到嚴的值的順序；網頁與模型只能往後（更嚴）改（ADR-0006 §3）。

不在這裡、也不能加進來的東西見 `FORBIDDEN_KEY_PARTS`（ADR-0019 §2.6）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

STATUSES = ("implemented", "planned", "hardware_missing")
STATUS_LABEL = {"implemented": "已實作", "planned": "規劃中", "hardware_missing": "硬體未到"}

#: 設定的 key 不能含這些字（安全保護、安全上限、腿、扭力、緊急停止不上設定頁）。`tests/test_schema.py` 會檢查。
FORBIDDEN_KEY_PARTS = (
    "safety", "estop", "torque", "leg", "kp", "offset", "temp", "volt", "lease", "fall", "limit_", "hard_cap", "walk", "gait",
)

#: 眼睛表情代號（`duck_eyes.EXPRESSIONS`）。duck_eyes 需要 numpy，這裡不匯入；測試會核對兩邊一致。
EXPRESSIONS = (
    "neutral", "happy", "joy", "love", "sad", "sorry", "grumpy", "surprised", "scared", "sleepy", "sleeping", "waking",
    "curious", "confused", "thinking", "listening", "speaking", "focused", "dizzy", "proud", "worried", "low_battery",
    "charging", "greeting", "wink",
)
#: Nous 可以叫的表情（`duck_eyes.policy.NOUS_ALLOWED`）：社交回應，不代表鴨子的實際狀態。
SOCIAL_EXPRESSIONS = (
    "neutral", "happy", "joy", "love", "sad", "sorry", "grumpy", "surprised", "curious", "confused", "thinking", "proud",
    "greeting", "wink", "sleepy",
)
#: presence 狀態 → 預設表情（`duckd.presence.EXPRESSION`）；測試會核對兩邊一致。
PRESENCE_DEFAULT_EXPRESSION = {
    "idle": "neutral", "wake": "surprised", "listening": "listening", "thinking": "thinking", "speaking": "speaking",
    "working": "focused", "error": "confused", "sleeping": "sleeping",
}
PRESENCE_LABEL = {
    "idle": "待機", "wake": "被叫醒", "listening": "聽你說話", "thinking": "思考中", "speaking": "說話中", "working": "處理中",
    "error": "出錯", "sleeping": "睡覺",
}

SECTIONS = (
    ("features", "功能開關", "打開或關掉鴨子的各項行為。"),
    ("audio", "語音與聲音", "音量上限、夜間時段、變聲、喚醒詞。喇叭播放還沒接成常駐服務，這一區目前只能看。"),
    ("hearing", "聽聲轉頭門檻", "多大聲才算有人說話、轉頭前要等多久、多久沒聲音就回正。"),
    ("head", "頭部動作", "頭轉多快、可以轉多遠、對話時小動作的幅度。"),
    ("eyes", "眼睛表情", "各個對話狀態用哪個表情。螢幕還沒到貨，現在只有虛擬面板（PNG）。"),
    ("privacy", "隱私", "在這一頁只能收緊。放寬要在鴨子本機用指令（ADR-0006 §3、ADR-0019 §2.5）。"),
    ("calibration", "機體量測值", "跟這隻鴨子的組裝有關的量測結果，不是偏好。「回復預設」不會動到這一區。"),
)


class SettingError(ValueError):
    """一個值不合格。訊息是給使用者看的中文。"""


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    label: str
    type: str  # bool | number | int | enum | time
    default: Any
    description: str
    status: str = "implemented"
    #: 哪個服務讀它（systemd 單元名稱）。`planned`／`hardware_missing` 的是 None。
    consumer: str | None = None
    apply: str = "live"  # live | restart
    kind: str = "preference"  # preference | measurement
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    choices: tuple[tuple[str, str], ...] = ()  # (值, 顯示名稱)
    #: 為什麼還不能用（`planned`／`hardware_missing` 必填）。
    blocked_by: str = ""
    #: 隱私設定：由寬到嚴的值。空的＝不是隱私設定。
    tighten: tuple[Any, ...] = ()
    advanced: bool = False
    #: 預設值、範圍的依據（驗證紀錄或 ADR）。
    basis: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def writable(self) -> bool:
        return self.status == "implemented"

    def validate(self, value: Any) -> Any:
        """檢查並回傳正規化後的值；不合格丟 SettingError。**不夾限**：超出範圍就是錯，不偷偷改掉。"""
        t = self.type
        if t == "bool":
            if not isinstance(value, bool):
                raise SettingError(f"{self.label}：要是開或關")
            return value
        if t in ("number", "int"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise SettingError(f"{self.label}：要是數字")
            if t == "int":
                if float(value) != int(value):
                    raise SettingError(f"{self.label}：要是整數")
                value = int(value)
            else:
                value = float(value)
            if (self.min is not None and value < self.min) or (self.max is not None and value > self.max):
                raise SettingError(f"{self.label}：{value:g} 超出範圍 {self.min:g}～{self.max:g}{self.unit}")
            return value
        if t == "enum":
            allowed = [c[0] for c in self.choices]
            if value not in allowed:
                raise SettingError(f"{self.label}：{value!r} 不在可選的值裡（{'、'.join(map(str, allowed))}）")
            return value
        if t == "time":
            if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
                raise SettingError(f"{self.label}：時間格式要是 HH:MM")
            return value
        raise SettingError(f"{self.label}：不認得的型別 {t}")

    def clamp(self, value: Any) -> Any:
        """把數字夾進範圍（只給服務端「檔案裡的值不合格時退回安全值」用；儲存時不用它）。"""
        if self.type in ("number", "int") and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            lo = self.min if self.min is not None else value
            hi = self.max if self.max is not None else value
            v = min(max(value, lo), hi)
            return int(v) if self.type == "int" else float(v)
        return self.default

    def is_looser(self, old: Any, new: Any) -> bool:
        """隱私設定：new 比 old 寬鬆嗎？（不是隱私設定一律 False）"""
        if not self.tighten or old not in self.tighten or new not in self.tighten:
            return False
        return self.tighten.index(new) < self.tighten.index(old)

    def public(self) -> dict:
        d = {
            "key": self.key, "section": self.section, "label": self.label, "type": self.type, "default": self.default,
            "description": self.description, "status": self.status, "status_label": STATUS_LABEL[self.status],
            "consumer": self.consumer, "apply": self.apply, "kind": self.kind, "unit": self.unit, "writable": self.writable,
            "blocked_by": self.blocked_by, "privacy": bool(self.tighten), "advanced": self.advanced, "basis": self.basis,
        }
        if self.type in ("number", "int"):
            d.update(min=self.min, max=self.max, step=self.step)
        if self.choices:
            d["choices"] = [{"value": v, "label": lab} for v, lab in self.choices]
        if self.tighten:
            d["tighten"] = list(self.tighten)
        if self.extra:
            d["extra"] = self.extra
        return d


DUCKD, DOA, VOICE = "duckd", "duck-doa", "duck-voice"
_VOICE_TEST = "2026-11-26 語音服務實機紀錄（docs/validation/voice-duck-side-2026-11-26.md）"
_HW_TEST = "2026-11-26 實機頭部與聽聲轉頭測試（docs/validation/duckd-head-hardware-2026-11-26.md）"


def _expr_choices(state: str) -> tuple[tuple[str, str], ...]:
    """這個 presence 狀態可以選的表情：社交表情＋它自己的預設。

    代表鴨子實際狀態的表情（沒電、充電、聽、說…）不能指給別的狀態，否則會顯示沒發生的事（誠實規則）。
    """
    names = list(SOCIAL_EXPRESSIONS)
    default = PRESENCE_DEFAULT_EXPRESSION[state]
    if default not in names:
        names.insert(0, default)
    return tuple((n, n) for n in names)


def _build() -> tuple[Setting, ...]:
    s: list[Setting] = []
    add = s.append

    # ------------------------------------------------------------ 功能開關
    add(Setting("features.track_sound", "features", "聽聲轉頭", "bool", True,
                "有人說話時把頭轉向聲音。關掉後 Nous 要求聽聲轉頭會被拒絕，正在進行的也會停。",
                consumer=DUCKD, basis=_HW_TEST))
    add(Setting("features.gestures", "features", "具名動作（點頭、搖頭、歪頭、張望）", "bool", True,
                "Nous 可以要求鴨子做動作庫裡的動作。關掉後一律拒絕。", consumer=DUCKD))
    add(Setting("features.presence_head_motion", "features", "對話時的頭部小動作", "bool", True,
                "被叫醒抬頭、聽的時候歪頭、思考時慢慢左右擺、出錯時搖一下、睡覺時低頭。關掉後這些狀態下頭回正不動，眼睛表情照常。",
                consumer=DUCKD))
    add(Setting("features.speaking_bob", "features", "說話時跟著音量點頭", "bool", True,
                "鴨子說話時頭隨著實際播出的音量小幅點動。關掉後說話時頭不動。", consumer=DUCKD))
    add(Setting("features.track_face", "features", "看著說話的人", "bool", True,
                "用鏡頭找到人臉，頭跟著轉。", status="hardware_missing", blocked_by="雙目鏡頭還沒裝；人臉追蹤只在合成資料上測過"))
    add(Setting("features.wake_word", "features", "喚醒詞", "bool", True,
                "聽到喚醒詞才開始對話。關掉後語音服務不開麥克風，叫不醒鴨子。", consumer=VOICE, basis=_VOICE_TEST))
    add(Setting("features.sound_effects", "features", "對話提示音", "bool", True,
                "被叫醒時的「開始聽」、沒聽到人說話的「聽完了」、連不上 Nous 的提示音。目前只有語音服務會播；表情切換的音效還沒接。",
                consumer=VOICE, basis=_VOICE_TEST))

    # ------------------------------------------------------------ 語音與聲音（duck-voice 服務）
    add(Setting("audio.volume", "audio", "音量", "number", 0.2,
                "鴨子出聲的音量（線性增益）。實際音量不會超過下面的上限。", consumer=VOICE, min=0.0, max=1.0, step=0.05,
                basis="保守初值；沒有量過聲壓。" + _VOICE_TEST))
    add(Setting("audio.volume_cap_day", "audio", "白天音量上限", "number", 0.5,
                "鴨子出聲的線性增益上限。Nous 只能在這個上限以內調音量。", consumer=VOICE,
                min=0.0, max=0.5, step=0.05, basis="ADR-0010 §7；duck_audio.playback.GateConfig 的初始值，未校準"))
    add(Setting("audio.volume_cap_night", "audio", "夜間音量上限", "number", 0.15,
                "夜間時段的音量上限。", status="planned", blocked_by="夜間模式的排程還沒做（ADR-0006 待決第 4 項），目前一律用白天上限",
                min=0.0, max=0.15, step=0.05, basis="ADR-0010 §7；初始值，未校準"))
    add(Setting("audio.night_start", "audio", "夜間開始", "time", "22:00", "夜間模式開始的時間。", status="planned",
                blocked_by="夜間模式的排程還沒做（ADR-0006 待決第 4 項）"))
    add(Setting("audio.night_end", "audio", "夜間結束", "time", "07:00", "夜間模式結束的時間。", status="planned",
                blocked_by="夜間模式的排程還沒做（ADR-0006 待決第 4 項）"))
    add(Setting("audio.mute", "audio", "本機靜音", "bool", False, "擋下鴨子的所有聲音（回話與提示音）。", consumer=VOICE))
    add(Setting("audio.voice_changer", "audio", "變聲方式", "enum", "phase_vocoder",
                "把 Nous 的聲音變成鴨子的聲音的演算法。下一句回話開始套用。", consumer=VOICE,
                choices=(("delay_line", "延遲線（省運算，延遲 20 ms）"), ("phase_vocoder", "相位聲碼器（可控共振峰，延遲 53 ms）")),
                basis="audio-2026-11-25 驗證紀錄；使用者還沒試聽定案"))
    add(Setting("audio.voice_semitones", "audio", "音高平移", "number", 5.0, "聲音升高幾個半音。0＝不升。候選是 +3、+5、+7。",
                consumer=VOICE, min=0.0, max=7.0, step=1.0, unit=" 半音", basis="ADR-0010 §4 的候選值；使用者還沒試聽定案"))
    add(Setting("audio.voice_formant_ratio", "audio", "共振峰比例", "number", 1.12, "1.0＝保留原本的共振峰；大於 1 聽起來身體比較小。只對相位聲碼器有用。",
                consumer=VOICE, min=1.0, max=1.2, step=0.01, basis="audio-2026-11-25 驗證紀錄建議的起點；使用者還沒試聽定案"))
    add(Setting("audio.wake_keyword", "audio", "喚醒詞", "enum", "HEY_YAZI", "用哪一句叫醒鴨子。改了之後幾秒內生效。",
                consumer=VOICE, basis="ADR-0003 §3：預設「Hey 鴨子」，可以改。清單在 robot/audio/config/wake_keywords.json；" + _VOICE_TEST,
                choices=(("HEY_YAZI", "Hey 鴨子"), ("HEI_YAZI", "嘿鴨子"), ("HEY_DUCK", "Hey Duck"), ("HELLO_DUCK", "Hello Duck"),
                         ("XIAOYA_XIAOYA", "小鴨小鴨"), ("HEY_NOUS", "Hey Nous（和 Nous 其他終端相同）"), ("HELLO_NOUS", "Hello Nous（和 Nous 其他終端相同）"))))
    add(Setting("audio.wake_sensitivity", "audio", "喚醒門檻倍數", "number", 1.0,
                "把喚醒詞的門檻乘上這個倍數。調高比較不會誤喚醒、但比較難叫醒；調低相反。", consumer=VOICE, min=0.5, max=3.0, step=0.1,
                basis="門檻本身沿用 AIOS 的值，在鴨子的麥克風上沒有用真人聲音校準"))
    add(Setting("audio.listen_no_speech_s", "audio", "叫醒後沒人說話，等多久", "number", 8.0,
                "被叫醒後一直沒聽到說話，過這麼久就結束這一輪、關掉上行。", consumer=VOICE, min=3.0, max=20.0, step=1.0, unit=" 秒"))
    add(Setting("audio.listen_end_silence_s", "audio", "說完後安靜多久算說完", "number", 1.5,
                "鴨子自己判斷「說完了」的安靜時間。Nous 通常會更早通知說完了。", consumer=VOICE, min=0.5, max=5.0, step=0.1, unit=" 秒", advanced=True))
    add(Setting("audio.listen_max_s", "audio", "單輪最長收音", "number", 30.0,
                "一輪最多送這麼久的聲音給 Nous，時間到自動停。", consumer=VOICE, min=5.0, max=60.0, step=5.0, unit=" 秒"))
    add(Setting("audio.reply_timeout_s", "audio", "等回話的上限", "number", 15.0,
                "說完後等 Nous 回話，超過就放棄並播提示音。", consumer=VOICE, min=5.0, max=60.0, step=5.0, unit=" 秒", advanced=True))
    add(Setting("audio.aec_reference", "audio", "把播出的聲音送給麥克風當回音消除的參考", "bool", True,
                "打開時，鴨子播的聲音同時送進麥克風陣列，讓它把喇叭的聲音從收音裡消掉。", consumer=VOICE, advanced=True,
                basis="2026-11-26 實機：處理後聲道在播放時的音量從 −19 dBFS 降到 −52～−58 dBFS。" + _VOICE_TEST))
    add(Setting("audio.barge_in", "audio", "鴨子說話時可以用喚醒詞打斷", "bool", False,
                "關掉時（預設）鴨子說話期間不聽喚醒詞。打開前要先確認鴨子自己的聲音不會誤觸發。", consumer=VOICE, advanced=True,
                basis="還沒有用真人聲音量過說話中的喚醒率與自我觸發"))

    # ------------------------------------------------------------ 聽聲轉頭門檻
    add(Setting("hearing.min_speech_energy", "hearing", "語音能量門檻", "number", 200000.0,
                "麥克風陣列回報的語音能量要超過這個值才算有人說話。調高可以濾掉遠處或小聲的聲音；0＝晶片認為有語音就算。",
                consumer=DOA, min=0.0, max=5000000.0, step=10000.0, basis=_HW_TEST + "：依一場錄到的資料選 2e5，這個值本身還沒有在實機上驗證過"))
    add(Setting("hearing.settle_s", "hearing", "頭停穩後等多久才再聽", "number", 1.0,
                "頭在動、或剛停下不到這個時間，收到的方位全部丟掉（舵機的聲音會被麥克風當成有人說話）。太短頭會來回擺。"
                "一定要比下面的「方位視窗」長 0.1 秒以上。",
                consumer=DUCKD, min=0.6, max=5.0, step=0.1, unit=" 秒", basis=_HW_TEST + "：0.5 秒會來回擺，改成 1.0"))
    add(Setting("hearing.recenter_s", "hearing", "多久沒聲音就回正", "number", 8.0,
                "這麼久沒有聽到聲音，頭轉回正前方。", consumer=DUCKD, min=2.0, max=60.0, step=1.0, unit=" 秒"))
    add(Setting("hearing.deadzone_deg", "hearing", "不動的範圍（死區）", "number", 8.0,
                "新的聲音方向和目前的頭部方向差不到這個角度就不動，避免說話的人稍微晃動頭就跟著抖。",
                consumer=DUCKD, min=2.0, max=30.0, step=1.0, unit="°"))
    add(Setting("hearing.min_confidence", "hearing", "方位信心下限", "number", 0.3,
                "方位的信心（主要方向占語音樣本的比例）低於這個值就不採用。", consumer=DUCKD, min=0.0, max=1.0, step=0.05, advanced=True))
    add(Setting("hearing.window_s", "hearing", "方位視窗", "number", 0.5,
                "聲源方位服務用最近這段時間的語音樣本估方向。", consumer=DOA, min=0.2, max=2.0, step=0.1, unit=" 秒", advanced=True))
    add(Setting("hearing.min_speech_samples", "hearing", "視窗內最少語音樣本數", "int", 4,
                "視窗內有語音的樣本少於這個數就不送方位（每秒取樣 20 次）。", consumer=DOA, min=1, max=20, step=1, advanced=True))
    add(Setting("hearing.cluster_tolerance_deg", "hearing", "方向分群的容許角度", "number", 25.0,
                "角度差在這個範圍內的樣本算同一個方向。", consumer=DOA, min=5.0, max=60.0, step=1.0, unit="°", advanced=True))
    add(Setting("hearing.speech_source", "hearing", "怎麼判斷有語音", "enum", "energy",
                "energy＝看語音能量（即時）。flag＝看晶片的語音旗標（聲音停了還會停留 2–3 秒，頭會被自己的舵機聲帶著跑，只留作對照）。",
                consumer=DOA, choices=(("energy", "語音能量（建議）"), ("flag", "語音旗標（對照用）")), advanced=True, basis=_HW_TEST))

    # ------------------------------------------------------------ 頭部動作
    add(Setting("head.speed_deg_s", "head", "頭部最高角速度", "number", 30.0,
                "頭每秒最多轉幾度。duckd 內建的硬上限是 90°/s，這裡最多只能設到 60。",
                consumer=DUCKD, apply="restart", min=5.0, max=60.0, step=5.0, unit="°/s",
                basis="30°/s 是 2026-11-25 無人看顧時的規定（duckd/limits.py）；模擬量測還沒做"))
    add(Setting("head.window_deg", "head", "頭部活動範圍（接手位置 ±）", "number", 15.0,
                "每一軸只能在 duckd 接手時的位置 ± 這個角度內活動。機構的角度上限另外算，這裡改不到。",
                consumer=DUCKD, apply="restart", min=5.0, max=30.0, step=1.0, unit="°",
                basis="±15° 是 2026-11-25 無人看顧時的規定"))
    add(Setting("head.presence_amplitude", "head", "對話小動作的幅度", "number", 1.0,
                "對話時頭部小動作（歪頭、擺動、點頭）的幅度倍率。1＝設計值，只能調小。",
                consumer=DUCKD, min=0.0, max=1.0, step=0.1, unit=" 倍"))

    # ------------------------------------------------------------ 眼睛表情
    for state, default in PRESENCE_DEFAULT_EXPRESSION.items():
        add(Setting(f"eyes.presence.{state}", "eyes", f"{PRESENCE_LABEL[state]}（{state}）", "enum", default,
                    f"Nous 的語音工作階段在「{PRESENCE_LABEL[state]}」時，眼睛顯示哪個表情。"
                    + ("鏡頭開著時不會顯示閉眼睡著（ADR-0013）。" if state == "sleeping" else ""),
                    consumer=DUCKD, choices=_expr_choices(state), extra={"presence": state}))
    add(Setting("eyes.brightness", "eyes", "螢幕亮度", "number", 1.0, "眼睛螢幕的背光亮度。", status="hardware_missing",
                blocked_by="GC9A01 螢幕還沒到貨；有沒有背光控制腳要收貨後確認", min=0.1, max=1.0, step=0.1))
    add(Setting("eyes.auto_blink", "eyes", "自動眨眼", "bool", True, "每隔幾秒自動眨眼。", status="planned",
                blocked_by="眨眼間隔寫在各表情的定義裡，還沒有開關"))

    # ------------------------------------------------------------ 隱私（ADR-0006）
    add(Setting("privacy.sound_direction", "privacy", "讀取聲源方向", "bool", True,
                "讓聲源方位服務向麥克風陣列讀「聲音從哪個方向來」。只讀方向，不讀也不存任何聲音。"
                "關掉後服務不再碰麥克風，聽聲轉頭也就不能用。",
                consumer=DOA, tighten=(True, False), basis="ADR-0006 §4：規則在資料產生處執行"))
    add(Setting("privacy.mode", "privacy", "隱私模式", "enum", "normal", "一鍵切換的組合（ADR-0006 §2.3）。", status="planned",
                blocked_by="隱私設定文件與兩端同步還沒做（protocol 的 privacy_policy 規劃中）",
                choices=(("normal", "一般"), ("guest", "訪客"), ("night", "夜間"), ("full", "完全隱私")),
                tighten=("normal", "guest", "night", "full")))
    add(Setting("privacy.camera", "privacy", "鏡頭", "bool", True, "關掉後不能導航、找人、回充。", status="hardware_missing",
                blocked_by="雙目鏡頭還沒裝", tighten=(True, False)))
    add(Setting("privacy.wake_listening", "privacy", "常駐喚醒聆聽（麥克風）", "bool", True,
                "關掉後語音服務不開麥克風，叫不醒鴨子。喚醒前的聲音只在記憶體裡經過喚醒引擎，不存檔、不外傳。",
                consumer=VOICE, tighten=(True, False), basis="ADR-0003 §6、ADR-0006 §4：規則在資料產生處執行"))
    add(Setting("privacy.face_recognition", "privacy", "臉部辨識", "bool", True, "關掉後找人只靠聲音方向與聲紋。", status="planned",
                blocked_by="在 Nous 端執行（ADR-0006 §4），鴨子上沒有這個開關可以接", tighten=(True, False)))

    # ------------------------------------------------------------ 機體量測值
    add(Setting("calibration.mic.mount", "calibration", "麥克風裝在哪", "enum", "head",
                "head＝裝在頭上、跟著頭轉（方位要加上當下的頭部角度）；body＝裝在身體上；desk＝放在桌上、不在鴨子身上。",
                consumer=DOA, kind="measurement",
                choices=(("head", "頭上（跟著頭轉）"), ("body", "身體上"), ("desk", "桌上（不在鴨子身上）")), basis=_HW_TEST))
    add(Setting("calibration.mic.front_angle_deg", "calibration", "正前方校正值", "number", 0.0,
                "麥克風回報的哪個角度對應鴨子的正前方。用 `python -m duck_audio.doa --calibrate 5 --write-config` 量"
                "（人站在鴨子正前方說話），不建議用猜的。",
                consumer=DOA, kind="measurement", min=0.0, max=359.9, step=0.1, unit="°"))
    add(Setting("calibration.mic.counterclockwise", "calibration", "角度往鴨子左邊增加", "bool", False,
                "麥克風角度增加的方向。麥克風平放在頭頂、USB 接頭朝後時是「關」。換安裝方向要重新確認（站到鴨子左邊說話，頭應該往左轉）。",
                consumer=DOA, kind="measurement", basis=_HW_TEST + "：人眼確認"))
    add(Setting("calibration.mic.calibrated", "calibration", "正前方已校正", "bool", False,
                "校正過正前方才打開。沒打開時，服務的存活訊息會帶「front angle not calibrated」。", consumer=DOA, kind="measurement"))
    return tuple(s)


SETTINGS: tuple[Setting, ...] = _build()
BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}


def defaults(kind: str | None = None) -> dict[str, Any]:
    return {s.key: s.default for s in SETTINGS if kind is None or s.kind == kind}


def check_cross_rules(values: dict[str, Any]) -> list[str]:
    """跨項目的規則。回傳錯誤訊息清單（空的＝通過）。"""
    errors = []
    if values["hearing.settle_s"] < values["hearing.window_s"] + 0.1 - 1e-9:
        errors.append(
            f"「頭停穩後等多久才再聽」（{values['hearing.settle_s']:g} 秒）要比「方位視窗」（{values['hearing.window_s']:g} 秒）長 0.1 秒以上，"
            "否則頭停下後還會收到轉動時的方位，頭會來回擺"
        )
    if values["audio.listen_end_silence_s"] >= values["audio.listen_no_speech_s"]:
        errors.append("「說完後安靜多久算說完」要比「叫醒後沒人說話，等多久」短")
    return errors
