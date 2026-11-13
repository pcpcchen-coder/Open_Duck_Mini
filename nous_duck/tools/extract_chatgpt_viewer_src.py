#!/usr/bin/env python3
"""從 ChatGPT 對話紀錄抽出它寫的 3D 組裝檢視器原始碼。

用法：
    python3 -I nous_duck/tools/extract_chatgpt_viewer_src.py \
        nous_duck/docs/handoff/chatgpt_conversation_2026-11.md \
        nous_duck/docs/handoff/chatgpt_viewer_src

原理：
- 對話紀錄裡，ChatGPT 執行的程式碼放在 ```` 圍起來的區塊，內容是 `bash -lc /bin/bash -lc "<script>"`。
  用 shlex 拆出 <script>，再找 `cat > 檔名 <<'TAG' ... TAG` 的 heredoc，依出現順序寫出檔案（後出現的覆蓋先出現的）。
- ChatGPT 之後又用兩段 `python - <<'PY'` 就地修改 model.py、index.template、viewer.js、viewer.css。
  這兩段只在 sha256 與下方白名單一致時才執行，其他 python 片段一律不執行。
- 只用標準函式庫。對話紀錄是不受信任的資料，請用 `python3 -I` 執行。
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
from pathlib import Path

# ChatGPT 就地修改檔案的兩段腳本（依對話順序）。內容變了就不執行，避免跑到非預期的程式碼。
# sha256 用 --print-hashes 取得。
KNOWN_PATCHES: dict[str, str] = {
    "bb5b9372777193eb6adfdc075bc50683d9eee006ebcd6add53f1f6949dae2427":
        "model.py：舵機分組改成每個主動舵盤一組，舵機殼件歸給同一 body 內最近的舵盤",
    "a7dd1b8a7d422a70163f75196d77c8bd3b68c4b37a74d102d028d07711659753":
        "index.template、viewer.js、viewer.css：WebGL 無法使用時改顯示靜態組裝預覽圖",
}

BLOCK_RE = re.compile(r"^````\n(.*?)\n````$", re.S | re.M)
HEREDOC_RE = re.compile(r"cat > ([\w./-]+) <<'(\w+)'\n(.*?)\n\2(?:\n|$)", re.S)
PY_RE = re.compile(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", re.S)


def scripts(md: str):
    for block in BLOCK_RE.findall(md):
        if not block.startswith("bash -lc "):
            continue
        try:
            yield shlex.split(block)[-1]
        except ValueError:
            continue


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    print_hashes = "--print-hashes" in sys.argv
    if len(args) != 2:
        raise SystemExit(__doc__)
    src, out = Path(args[0]), Path(args[1]).resolve()
    md = src.read_text(encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}
    patches: list[str] = []
    for script in scripts(md):
        for name, _tag, body in HEREDOC_RE.findall(script):
            written[name] = body + "\n"
        for code in PY_RE.findall(script):
            # 只考慮「改寫已抽出檔案」的片段
            if re.search(r"Path\('(model\.py|index\.template|viewer\.js|viewer\.css)'\)", code) and ".write_text" in code:
                patches.append(code)

    for name, text in written.items():
        (out / name).write_text(text, encoding="utf-8")

    allowed = set(KNOWN_PATCHES)
    cwd = os.getcwd()
    os.chdir(out)
    try:
        for code in patches:
            digest = hashlib.sha256(code.encode()).hexdigest()
            if print_hashes:
                print("patch", digest)
            if digest in allowed:
                exec(compile(code, f"patch-{digest[:8]}", "exec"), {"__name__": "__patch__"})
                print(f"已套用修改 {digest[:12]}（{KNOWN_PATCHES[digest]}）")
            else:
                print(f"略過未列入白名單的修改 {digest[:12]}", file=sys.stderr)
    finally:
        os.chdir(cwd)

    for name in sorted(written):
        lines = (out / name).read_text(encoding="utf-8").count("\n")
        print(f"{name:20} {lines:4} 行")


if __name__ == "__main__":
    main()
