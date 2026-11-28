"""本機控制指令（在鴨子上執行）：

    python -m duckd.ctl status        # 連線、接手狀態、量測數字
    python -m duckd.ctl engage        # 接手硬體：開匯流排、頭部出力（先檢查沒有別的程式占用）
    python -m duckd.ctl release       # 頭回到接手時的位置、恢復扭力狀態、放開匯流排
    python -m duckd.ctl estop         # 緊急停止（頭部關扭力並鎖住）
    python -m duckd.ctl clear-estop   # 解除緊急停止（只有本機能做；之後要 release 再 engage）

腿（duckd 要用 --legs 啟動；ADR-0020 草案，**沒有實機驗證**，每次都要有人在旁邊扶著）：

    python -m duckd.ctl engage-legs           # 接手腿：沒出力的腿先寫目前位置再開扭力
    python -m duckd.ctl posture crouch        # 原地蹲低（預設 3 秒，--duration 3～10）
    python -m duckd.ctl posture stand         # 起立；收手後回站姿至少 6 秒
    python -m duckd.ctl posture-stop          # 停在目前位置（不放鬆）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .localctl import request


def main() -> int:
    p = argparse.ArgumentParser(description="duckd 本機控制")
    p.add_argument(
        "cmd",
        choices=["status", "engage", "release", "estop", "clear-estop", "reset-fallen", "engage-legs", "posture", "posture-stop"],
    )
    p.add_argument("target", nargs="?", choices=["crouch", "stand"], help="posture 的目標")
    p.add_argument("--duration", type=float, default=None, help="posture 走完整條路徑的秒數（3～10）")
    p.add_argument("--socket", type=Path, default=None)
    args = p.parse_args()
    fields = {}
    if args.cmd == "posture":
        if args.target is None:
            p.error("posture 要給 crouch 或 stand")
        fields["target"] = args.target
        if args.duration is not None:
            fields["duration_s"] = args.duration
    elif args.target is not None:
        p.error(f"{args.cmd} 不接受 {args.target}")
    try:
        reply = request(args.cmd, args.socket, **fields)
    except OSError as exc:
        print(f"連不到 duckd（服務有在跑嗎？）：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(reply, ensure_ascii=False, indent=1))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
