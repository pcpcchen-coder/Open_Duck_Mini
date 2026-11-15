"""命令列：產生 scene.json、meshes.bin 與 steps.json。

    cd nous_duck/assembly_viewer/pipeline
    python -m viewer_pipeline                       # 輸出到 ../dist/build/
    python -m viewer_pipeline --out /some/dir
"""
from __future__ import annotations

import argparse
from pathlib import Path

import json

from .scene import build, default_repo_root
from .steps import load_steps


def main() -> None:
    parser = argparse.ArgumentParser(prog="viewer_pipeline", description="Open Duck Mini v2 組裝檢視器資料處理")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root(), help="repo 根目錄（預設自動判斷）")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "dist" / "build",
        help="輸出目錄（預設 nous_duck/assembly_viewer/dist/build，不進版控）",
    )
    args = parser.parse_args()

    result = build(args.repo_root)
    steps = load_steps(args.repo_root, result.scene)  # 先檢查步驟，沒過就不寫任何輸出
    scene_path, bin_path = result.write(args.out)
    steps_path = args.out / "steps.json"
    steps_path.write_text(json.dumps(steps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    s = result.scene["summary"]
    print(f"scene.json  {scene_path}  {scene_path.stat().st_size:,} bytes")
    print(f"meshes.bin  {bin_path}  {bin_path.stat().st_size:,} bytes")
    print(f"steps.json  {steps_path}  {len(steps['steps'])} 步")
    print(f"零件實例 {s['part_instances']}：{s['parts_by_kind']}")
    print(f"列印件 {s['printed_pieces']} 件（{s['print_stl_types']} 種）；STS3215 {s['servos']} 顆")
    print(f"高度 {s['height_mm']} mm（不含天線 {s['height_without_antennas_mm']} mm）")
    print(f"網格 {s['unique_meshes']} 種、{s['triangles_unique']:,} 個三角形；量化誤差上限 {s['max_quant_error_mm']} mm")
    for servo in result.scene["servos"]:
        print(
            f"  ID {servo['id']:>2}  {servo['joint']:<16} {servo['side']:<6} "
            f"舵盤離轉軸 {servo['horn_to_axis_mm']:.4f} mm、離關節點 {servo['horn_to_joint_mm']:.1f} mm、"
            f"次近舵盤 {servo['next_nearest_horn_mm']:.1f} mm"
        )


if __name__ == "__main__":
    main()
