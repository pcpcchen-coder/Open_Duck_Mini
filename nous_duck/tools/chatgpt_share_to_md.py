#!/usr/bin/env python3
"""把 ChatGPT 分享頁的 HTML 轉成 Markdown 對話紀錄。

用法：
    curl -sSL -A "Mozilla/5.0 ... Chrome/130.0 Safari/537.36" -o share.html <分享連結>
    python3 -I chatgpt_share_to_md.py share.html out.md --url <分享連結>

原理：
- 分享頁把資料放在 `streamController.enqueue("...")` 的 JS 字串裡；逐段 json.loads 後接起來。
- 內容是 React Router turbo-stream 格式的扁平陣列：物件的 key 是 "_N"（指向陣列索引 N 的字串），
  value 是索引；負數代表 null/undefined。從索引 0 遞迴解開。
- 找到含 `mapping` 的對話物件，取每個節點的 message.author.role 與內容：
  content_type == "text" 取 parts；content_type == "code" 取 text（助理執行的程式碼）。
  thoughts、reasoning_recap、tool 回傳等不輸出。依 create_time 排序。

只用標準函式庫。下載的 HTML 是不受信任的資料，請用 `python3 -I` 執行。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

SPECIAL_TAGS = {"D", "P", "Z", "S", "$"}


def load_turbo_array(html: str) -> list:
    chunks = re.findall(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\)', html, re.S)
    if not chunks:
        raise SystemExit("找不到 streamController.enqueue(...)，頁面格式可能變了")
    raw = "".join(json.loads(c) for c in chunks)
    lines = [line for line in raw.split("\n") if line.startswith("[")]
    return json.loads(lines[0])


def make_decoder(arr: list):
    memo: dict[int, object] = {}

    def dec(i):
        if i < 0:
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, dict):
            out: dict = {}
            memo[i] = out
            for k, idx in v.items():
                key = arr[int(k[1:])] if k.startswith("_") else k
                out[key] = dec(idx) if isinstance(idx, int) else idx
            return out
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in SPECIAL_TAGS:
                return v
            lst: list = []
            memo[i] = lst
            lst.extend(dec(x) if isinstance(x, int) else x for x in v)
            return lst
        return v

    return dec


def find_conversation(o):
    stack = [o]
    seen = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, dict):
            if isinstance(cur.get("mapping"), dict):
                return cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    raise SystemExit("找不到含 mapping 的對話物件")


def extract_messages(conv: dict) -> list[tuple[float, str, str]]:
    msgs = []
    for node in conv["mapping"].values():
        m = (node or {}).get("message")
        if not m:
            continue
        role = (m.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or {}
        ctype = content.get("content_type")
        if ctype == "text":
            parts = content.get("parts") or []
            text = "\n\n".join(
                p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "")
                for p in parts
                if p
            ).strip()
        elif ctype == "code" and content.get("text"):
            lang = content.get("language") or ""
            if lang == "unknown":
                lang = ""
            text = f"（程式碼，送往 `{m.get('recipient')}`）\n\n````{lang}\n{content['text'].rstrip()}\n````"
        else:
            continue
        if text:
            msgs.append((m.get("create_time") or 0, role, text))
    msgs.sort(key=lambda x: x[0])
    return msgs


def render(conv: dict, msgs, url: str | None) -> str:
    n_user = sum(1 for m in msgs if m[1] == "user")
    out = [f"# {conv.get('title') or 'ChatGPT 對話'}", ""]
    src = f"ChatGPT 分享連結 {url}" if url else "ChatGPT 分享頁"
    out += [f"來源：{src}（{dt.date.today()} 以 `nous_duck/tools/chatgpt_share_to_md.py` 從分享頁 HTML 解出，未經人工改寫）", ""]
    out += [f"使用者訊息 {n_user} 則、助理回覆 {len(msgs) - n_user} 則（含助理執行的程式碼；不含思考過程與工具回傳）。", ""]
    for t, role, text in msgs:
        ts = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if t else "?"
        who = "使用者" if role == "user" else "ChatGPT"
        out.append(f"---\n\n## {who}（{ts}）\n\n{text}\n")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--url")
    args = ap.parse_args()
    with open(args.html, encoding="utf-8") as f:
        arr = load_turbo_array(f.read())
    sys.setrecursionlimit(100000)
    conv = find_conversation(make_decoder(arr)(0))
    msgs = extract_messages(conv)
    md = render(conv, msgs, args.url)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    n_user = sum(1 for m in msgs if m[1] == "user")
    print(f"使用者 {n_user} 則、助理 {len(msgs) - n_user} 則、{len(md.encode())} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
