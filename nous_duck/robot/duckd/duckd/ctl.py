"""本機控制指令（在鴨子上執行）：

    python -m duckd.ctl status        # 連線、接手狀態、量測數字
    python -m duckd.ctl engage        # 接手硬體：開匯流排、頭部出力（先檢查沒有別的程式占用）
    python -m duckd.ctl release       # 頭回到接手時的位置、恢復扭力狀態、放開匯流排
    python -m duckd.ctl estop         # 緊急停止（頭部關扭力並鎖住）
    python -m duckd.ctl clear-estop   # 解除緊急停止（只有本機能做；之後要 release 再 engage）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .localctl import request


def main() -> int:
    p = argparse.ArgumentParser(description="duckd 本機控制")
    p.add_argument("cmd", choices=["status", "engage", "release", "estop", "clear-estop", "reset-fallen"])
    p.add_argument("--socket", type=Path, default=None)
    args = p.parse_args()
    try:
        reply = request(args.cmd, args.socket)
    except OSError as exc:
        print(f"連不到 duckd（服務有在跑嗎？）：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(reply, ensure_ascii=False, indent=1))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
