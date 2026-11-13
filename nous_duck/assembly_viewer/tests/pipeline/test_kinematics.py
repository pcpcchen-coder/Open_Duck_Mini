import struct

import numpy as np
import pytest

from viewer_pipeline.geometry import read_binary_stl, transform_points
from viewer_pipeline.kinematics import load_robot
from viewer_pipeline.scene import ROBOT_DIR

TINY = """<mujoco>
  <compiler angle="radian"/>
  <asset><mesh name="m" file="m.stl"/></asset>
  <worldbody>
    <body name="root" pos="1 0 0" quat="0.70710678 0 0 0.70710678">
      <geom type="mesh" mesh="m" pos="1 0 0"/>
      <body name="child" pos="0 2 0" quat="0.70710678 0.70710678 0 0">
        <joint name="j" axis="0 0 1" range="-1 1"/>
        <geom type="mesh" mesh="m" pos="0 0 1"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""


def _tiny(tmp_path, xml=TINY):
    (tmp_path / "m.stl").write_bytes(b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 12 + np.zeros(9, "<f4").tobytes() + b"\0\0")
    (tmp_path / "robot.xml").write_text(xml)
    return load_robot(tmp_path / "robot.xml")


def test_tiny_chain_by_hand(tmp_path):
    robot = _tiny(tmp_path)
    # root：在 (1,0,0)，繞 Z 轉 90°。它的 geom 的局部 (1,0,0) → 世界 (1,1,0)
    assert np.allclose(robot.geoms[0].position, [1, 1, 0])
    # child：局部 (0,2,0) 經 root 旋轉 → (-2,0,0)，加上 root 位置 → (-1,0,0)
    assert np.allclose(robot.bodies["child"].position, [-1, 0, 0])
    # child 再繞自己的 X 轉 90°；關節軸局部 Z → 先變 -Y（繞 X），再經 root 繞 Z → +X
    assert np.allclose(robot.joints["j"].axis, [1, 0, 0])
    # child 的 geom 局部 (0,0,1) → 同樣轉成 (1,0,0)，加上 child 位置 → (0,0,0)
    assert np.allclose(robot.geoms[1].position, [0, 0, 0])
    assert robot.joints["j"].range == (-1.0, 1.0)
    assert robot.joints["j"].parent_body == "root"


def test_unsupported_orientation_rejected(tmp_path):
    with pytest.raises(ValueError, match="euler"):
        _tiny(tmp_path, TINY.replace('quat="0.70710678 0 0 0.70710678"', 'euler="0 0 1.57"'))


def test_degree_compiler_rejected(tmp_path):
    with pytest.raises(ValueError, match="radian"):
        _tiny(tmp_path, TINY.replace('angle="radian"', 'angle="degree"'))


def test_upstream_robot_counts(repo_root):
    robot = load_robot(repo_root / ROBOT_DIR / "robot.xml")
    assert len(robot.geoms) == 131
    assert len(robot.joints) == 16
    assert len(robot.mesh_files) == 45


def test_matches_mujoco(repo_root):
    """用 MuJoCo 自己算的零位姿態，逐一比對每個 geom 的世界外框（誤差 < 1 µm）。"""
    mujoco = pytest.importorskip("mujoco")
    xml = repo_root / ROBOT_DIR / "robot.xml"
    model = mujoco.MjModel.from_xml_path(str(xml))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    ours = load_robot(xml)
    assert model.ngeom == len(ours.geoms)

    mj_geoms: dict[tuple[str, int], int] = {}
    counter: dict[str, int] = {}
    for g in range(model.ngeom):
        body = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, model.geom_bodyid[g])
        k = counter.get(body, 0)
        mj_geoms[(body, k)] = g
        counter[body] = k + 1

    worst = 0.0
    for geom in ours.geoms:
        g = mj_geoms[(geom.body, geom.index_in_body)]
        mesh_id = model.geom_dataid[g]
        assert mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh_id) == geom.mesh
        start, count = model.mesh_vertadr[mesh_id], model.mesh_vertnum[mesh_id]
        verts = model.mesh_vert[start : start + count].astype(np.float64)
        mj_world = verts @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g]

        our_world = transform_points(read_binary_stl(geom.mesh_file).reshape(-1, 3), geom.rotation, geom.position)
        for a, b in ((mj_world.min(0), our_world.min(0)), (mj_world.max(0), our_world.max(0))):
            worst = max(worst, float(np.max(np.abs(a - b))))
    assert worst < 1e-6, f"最大差異 {worst * 1e6:.3f} µm"

    for name, joint in ours.joints.items():
        j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        assert np.allclose(data.xanchor[j], joint.position, atol=1e-9)
        assert np.allclose(data.xaxis[j], joint.axis, atol=1e-9)
