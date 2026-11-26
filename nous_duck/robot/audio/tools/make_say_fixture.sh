#!/usr/bin/env bash
# D7：用 macOS 的 `say -o`（只寫檔，不經過喇叭）產生**合成語音**的喚醒詞測試檔。
#
# 產出放 robot/audio/build/say_kws/（**不進版控**：系統語音的輸出能不能再散布不確定，所以只在本機產生）。
# 不是真人錄音；句子不含任何人名或家裡的資訊。每台 Mac 裝的語音不同，沒有的語音會略過。
#
#   bash tools/make_say_fixture.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=build/say_kws
rm -rf "$OUT" && mkdir -p "$OUT"
MAN="$OUT/manifest.jsonl"
: > "$MAN"

gen() { # voice keyword_id(or -) slug text
  local voice="$1" kid="$2" slug="$3" text="$4"
  local vslug; vslug="$(printf "%s" "$voice" | tr -cd "A-Za-z")"
  local base="$OUT/${slug}_${vslug}"
  if say -v "$voice" -o "$base.aiff" "$text" 2>/dev/null; then
    afconvert -f WAVE -d LEI16@16000 -c 1 "$base.aiff" "$base.wav"
    rm -f "$base.aiff"
    if [ "$kid" = "-" ]; then kid=null; else kid="\"$kid\""; fi
    printf '{"file":"%s","keyword_id":%s,"voice":"%s","text":"%s","synthetic":true}\n' "$(basename "$base.wav")" "$kid" "$voice" "$text" >> "$MAN"
  else
    echo "略過（沒有這個語音）：$voice" >&2
  fi
}

for v in Meijia Tingting Sinji "Flo (中文（台灣）)" "Eddy (中文（台灣）)" "Sandy (中文（台灣）)" "Reed (中文（台灣）)"; do
  gen "$v" HEI_YAZI hei_yazi "嘿鴨子"
  gen "$v" HEY_YAZI hey_yazi "Hey 鴨子"
  gen "$v" HELLO_YAZI hello_yazi "Hello 鴨子"
  gen "$v" - neg_hello_yeye "Hello 爺爺，鴨子在哪裡？"
  gen "$v" XIAOYA_XIAOYA xiaoya_xiaoya "小鴨小鴨"
  gen "$v" YAZI_YAZI yazi_yazi "鴨子鴨子"
  gen "$v" - neg_weather "今天天氣很好，我們去散步吧。"
  gen "$v" - neg_black_shoes "黑色的鞋子放在架子上。"
  gen "$v" - neg_duck_pond "鴨子在池塘裡游泳。"
  gen "$v" - neg_time "現在幾點了？"
done
for v in Samantha Daniel Alex Karen; do
  gen "$v" HEY_DUCK hey_duck "Hey duck"
  gen "$v" HEY_NOUS hey_nous "Hey Nous"
  gen "$v" HELLO_NOUS hello_nous "Hello Nous"
  gen "$v" - neg_hey_nurse "Hey nurse, they know us."
  gen "$v" HELLO_DUCK hello_duck "Hello duck"
  gen "$v" - neg_hey_doug "Hey Doug, the dock is over there."
  gen "$v" - neg_weather_en "The weather is nice today, let us go for a walk."
  gen "$v" - neg_luck "Good luck with the truck."
done
echo "產生 $(wc -l < "$MAN" | tr -d ' ') 個檔案 → $OUT（不進版控）"
