"""把上游 CAD 轉成檢視器的 scene.json 與 meshes.bin。

座標：檢視器座標（+X 左、+Y 上、+Z 前），單位毫米。Y=0 是腳底最低點；X、Z 以整機外框中心為 0。
姿態：所有關節 0 度（上游 CAD 的零位）。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import SCENE_SCHEMA
from .bom import build_bom
from .catalog import load_catalog
from .explode import explode_vectors
from .geometry import MUJOCO_TO_VIEWER, is_rotation, matrix_to_quat_xyzw, read_binary_stl, transform_points
from .kinematics import load_robot
from .meshes import MeshPack, encode_mesh
from .selectors import PartRef, Resolver
from .servos import assign_servos
from .steps import build_steps
from .upstream import motor_ids, print_list, sha256

ROBOT_DIR = Path("mini_bdx/robots/open_duck_mini_v2")
PRINT_DIR = Path("print")
CONFIGURE_MOTORS = Path("docs/configure_motors.md")
PRINT_GUIDE = Path("docs/print_guide.md")
CATALOG = Path("nous_duck/assembly_viewer/data/cad_parts.yaml")
BOM = Path("nous_duck/assembly_viewer/data/bom.yaml")
STEPS = Path("nous_duck/assembly_viewer/data/steps.yaml")
ANTENNA_MESH = "antenna"


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass
class BuildResult:
    scene: dict
    mesh_bin: bytes

    def scene_json(self) -> str:
        return json.dumps(self.scene, ensure_ascii=False, indent=1) + "\n"

    def write(self, out_dir: Path) -> tuple[Path, Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        scene_path = out_dir / "scene.json"
        bin_path = out_dir / "meshes.bin"
        scene_path.write_text(self.scene_json(), encoding="utf-8")
        bin_path.write_bytes(self.mesh_bin)
        return scene_path, bin_path


def _rgba_hex(rgba) -> str | None:
    if rgba is None:
        return None
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgba[:3])


def _side(joint: str) -> str:
    if joint.startswith("left_"):
        return "left"
    if joint.startswith("right_"):
        return "right"
    return "center"


def _round(values, digits: int) -> list[float]:
    return [round(float(v), digits) + 0.0 for v in values]  # + 0.0 把 -0.0 變成 0.0


def build(repo_root: Path | None = None, *, bom_path: Path | None = None, steps_path: Path | None = None) -> BuildResult:
    """bom_path、steps_path 只給測試用：換成另一份資料檔，檢查錯誤能被擋下。"""
    root = Path(repo_root) if repo_root else default_repo_root()
    bom_file = Path(bom_path) if bom_path else root / BOM
    steps_file = Path(steps_path) if steps_path else root / STEPS
    robot_xml = root / ROBOT_DIR / "robot.xml"
    robot = load_robot(robot_xml)
    ids = motor_ids(root / CONFIGURE_MOTORS)
    print_counts = print_list(root / PRINT_GUIDE)

    used_meshes = {g.mesh for g in robot.geoms}
    unused = sorted(set(robot.mesh_files) - used_meshes)
    if unused:
        raise ValueError(f"robot.xml 宣告了沒用到的網格：{unused}")
    catalog = load_catalog(root / CATALOG, used_meshes, root / PRINT_DIR)
    servos = assign_servos(robot, ids)
    servo_of_geom = {i: s for s in servos for i in s.geom_indices}

    rot_v = MUJOCO_TO_VIEWER

    # ---- 零件實例（先用未平移的檢視器座標，算完外框再平移） ----
    instances: list[dict] = []
    per_body_mesh = Counter((g.body, g.mesh) for g in robot.geoms)
    seen: Counter = Counter()
    for i, g in enumerate(robot.geoms):
        seen[(g.body, g.mesh)] += 1
        part_id = f"{g.body}/{g.mesh}"
        if per_body_mesh[(g.body, g.mesh)] > 1:
            part_id += f"#{seen[(g.body, g.mesh)]}"
        info = catalog.info(g.mesh, g.body)
        servo = servo_of_geom.get(i)
        instances.append(
            {
                "id": part_id,
                "mesh": g.mesh,
                "mesh_file": g.mesh_file,
                "mesh_scale": 1000.0,  # CAD 網格單位是公尺
                "body": g.body,
                "rotation": rot_v @ g.rotation,
                "position": rot_v @ g.position * 1000.0,
                "info": info,
                "servo": servo,
                "placement": "cad",
                "color": _rgba_hex(g.rgba),
            }
        )

    for extra in catalog.print_only:
        anchors = [inst for inst in instances if inst["mesh"] == extra.frame_of]
        if len(anchors) != 1:
            raise ValueError(f"{extra.key} 的 frame_of {extra.frame_of!r} 在 CAD 裡出現 {len(anchors)} 次，應該剛好 1 次")
        anchor = anchors[0]
        instances.append(
            {
                "id": f"{anchor['body']}/print:{extra.key}",
                "mesh": f"print:{extra.key}",
                "mesh_file": root / PRINT_DIR / extra.print_stl,
                "mesh_scale": 1.0,  # print/ 的 STL 單位是毫米
                "body": anchor["body"],
                "rotation": anchor["rotation"],
                "position": anchor["position"],
                "info": type(anchor["info"])(
                    kind="printed",
                    name_zh=extra.name_zh,
                    name_en=extra.name_en,
                    print_stl=extra.print_stl,
                    identification=f"CAD 沒有擺放位置；套用 {extra.frame_of} 的座標（上游列印檔與 CAD 匯出在同一座標系）",
                ),
                "servo": None,
                "placement": "print_frame",
                "color": None,
            }
        )

    # ---- 世界頂點、外框、平移 ----
    all_min = np.full(3, np.inf)
    all_max = np.full(3, -np.inf)
    no_antenna_max_y = -np.inf
    for inst in instances:
        if not is_rotation(inst["rotation"]):
            raise ValueError(f"{inst['id']} 的旋轉矩陣不正交")
        local = read_binary_stl(inst["mesh_file"]).reshape(-1, 3) * inst["mesh_scale"]
        world = transform_points(local, inst["rotation"], inst["position"])
        lo, hi = world.min(axis=0), world.max(axis=0)
        inst["bbox"] = (lo, hi)
        all_min = np.minimum(all_min, lo)
        all_max = np.maximum(all_max, hi)
        if inst["mesh"] != ANTENNA_MESH:
            no_antenna_max_y = max(no_antenna_max_y, hi[1])
    shift = np.array([-(all_min[0] + all_max[0]) / 2, -all_min[1], -(all_min[2] + all_max[2]) / 2])
    for inst in instances:
        inst["position"] = inst["position"] + shift
        lo, hi = inst["bbox"]
        inst["center"] = (lo + hi) / 2 + shift
    bbox_min, bbox_max = all_min + shift, all_max + shift

    # ---- 列印件數量對照上游列印清單 ----
    printed = Counter(inst["info"].print_stl for inst in instances if inst["info"].kind == "printed")
    expected = {name: v["count"] for name, v in print_counts.items()}
    if dict(printed) != expected:
        diff = {k: (printed.get(k, 0), expected.get(k, 0)) for k in set(printed) | set(expected) if printed.get(k, 0) != expected.get(k, 0)}
        raise ValueError(f"列印件數量和 docs/print_guide.md 不一致（模型, 清單）：{diff}")

    # ---- 網格 ----
    pack = MeshPack()
    for inst in instances:
        key = inst["mesh"]
        if key in pack.records:
            continue
        tris = read_binary_stl(inst["mesh_file"]) * inst["mesh_scale"]
        pack.add(
            key,
            encode_mesh(tris),
            source=str(Path(inst["mesh_file"]).resolve().relative_to(root.resolve())),
            source_sha256=sha256(inst["mesh_file"]),
            source_units="m" if inst["mesh_scale"] == 1000.0 else "mm",
        )

    # ---- 爆炸向量 ----
    body_info = {
        name: {
            "parent": b.parent,
            "origin": rot_v @ b.position * 1000.0 + shift,
            "has_joint": b.joint is not None,
        }
        for name, b in robot.bodies.items()
    }
    explode = explode_vectors(
        [
            {
                "id": inst["id"],
                "body": inst["body"],
                "center": inst["center"],
                "group": f"servo-{inst['servo'].servo_id}" if inst["servo"] else None,
            }
            for inst in instances
        ],
        body_info,
    )

    # ---- BOM 與組裝步驟 ----
    refs = [
        PartRef(id=inst["id"], mesh=inst["mesh"], body=inst["body"], servo_id=inst["servo"].servo_id if inst["servo"] else None)
        for inst in instances
    ]
    resolver = Resolver(
        refs,
        cad_meshes=set(catalog.cad),
        bodies=set(robot.bodies),
        print_only_keys={extra.key for extra in catalog.print_only},
    )
    bom_rows, cad_without_bom, bom_of_part = build_bom(
        bom_file,
        catalog,
        print_counts,
        refs,
        {inst["id"]: inst["info"].print_stl for inst in instances},
        resolver,
    )
    steps, step_of_part = build_steps(
        steps_file,
        root,
        resolver,
        [inst["id"] for inst in instances],
        {row["id"] for row in bom_rows},
    )

    # ---- 輸出 ----
    servo_by_joint = {s.joint: s for s in servos}
    parts_out = []
    for inst in instances:
        info = inst["info"]
        servo = inst["servo"]
        parts_out.append(
            {
                "id": inst["id"],
                "mesh": inst["mesh"],
                "body": inst["body"],
                "kind": info.kind,
                "name_zh": info.name_zh,
                "name_en": info.name_en,
                "print_stl": info.print_stl,
                "servo_id": servo.servo_id if servo else None,
                "placement": inst["placement"],
                "identification": info.identification,
                "color": inst["color"],
                "position_mm": _round(inst["position"], 4),
                "quaternion_xyzw": _round(matrix_to_quat_xyzw(inst["rotation"]), 8),
                "center_mm": _round(inst["center"], 3),
                "explode_mm": explode[inst["id"]],
                "bom_id": bom_of_part.get(inst["id"]),
                "step": step_of_part[inst["id"]],
            }
        )

    servos_out = []
    for s in servos:
        servos_out.append(
            {
                "id": s.servo_id,
                "joint": s.joint,
                "side": _side(s.joint),
                "body": s.body,
                "parts": [instances[i]["id"] for i in s.geom_indices],
                "horn_center_mm": _round(rot_v @ s.horn_center * 1000.0 + shift, 3),
                "horn_to_axis_mm": round(s.axis_distance_m * 1000.0, 4),
                "horn_to_joint_mm": round(s.joint_distance_m * 1000.0, 3),
                "next_nearest_horn_mm": round(s.runner_up_distance_m * 1000.0, 3),
            }
        )

    joints_out = []
    for name, j in robot.joints.items():
        servo = servo_by_joint.get(name)
        joints_out.append(
            {
                "name": name,
                "body": j.body,
                "parent_body": j.parent_body,
                "servo_id": servo.servo_id if servo else None,
                "position_mm": _round(rot_v @ j.position * 1000.0 + shift, 4),
                "axis": _round(rot_v @ j.axis, 8),
                "range_rad": list(j.range) if j.range else None,
            }
        )

    kinds = Counter(p["kind"] for p in parts_out)
    scene = {
        "schema": SCENE_SCHEMA,
        "robot": "Open Duck Mini v2",
        "units": "mm",
        "frame": {
            "left": "+X",
            "up": "+Y",
            "front": "+Z",
            "origin": "Y=0 是腳底最低點；X、Z 以整機外框中心為 0",
        },
        "pose": "所有關節 0 度（上游 CAD 零位）",
        "sources": {
            str(p): sha256(root / p)
            for p in (ROBOT_DIR / "robot.xml", CONFIGURE_MOTORS, PRINT_GUIDE, CATALOG, BOM, STEPS)
        },
        "summary": {
            "height_mm": round(float(bbox_max[1] - bbox_min[1]), 1),
            "height_without_antennas_mm": round(float(no_antenna_max_y + shift[1] - bbox_min[1]), 1),
            "bbox_min_mm": _round(bbox_min, 3),
            "bbox_max_mm": _round(bbox_max, 3),
            "part_instances": len(parts_out),
            "parts_by_kind": dict(sorted(kinds.items())),
            "printed_pieces": sum(printed.values()),
            "print_stl_types": len(printed),
            "servos": len(servos_out),
            "unique_meshes": len(pack.records),
            "triangles_unique": sum(r["triangle_count"] for r in pack.records.values()),
            "max_quant_error_mm": max(r["max_quant_error_mm"] for r in pack.records.values()),
            "bom_rows": len(bom_rows),
            "bom_rows_by_category": dict(sorted(Counter(r["category"] for r in bom_rows).items())),
            "steps": len(steps),
        },
        "meshes": pack.records,
        "bodies": [{"name": n, "parent": b.parent, "joint": b.joint} for n, b in robot.bodies.items()],
        "joints": joints_out,
        "servos": servos_out,
        "parts": parts_out,
        "bom": bom_rows,
        "cad_without_bom": cad_without_bom,
        "steps": steps,
    }
    mesh_bin = pack.tobytes()
    scene["summary"]["meshes_bin_bytes"] = len(mesh_bin)
    return BuildResult(scene=scene, mesh_bin=mesh_bin)
