"""離螢幕算圖（截圖與短 GIF）。需要能建立 OpenGL 環境；無頭 Mac 用 CGL，Linux 可設 MUJOCO_GL=egl。"""

from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np


class Snapshotter:
    def __init__(self, model: mujoco.MjModel, width: int = 480, height: int = 360):
        self.m = model
        self.r = mujoco.Renderer(model, height=height, width=width)
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.cam.distance = 1.1
        self.cam.elevation = -18
        self.cam.azimuth = 130
        self.frames: list[np.ndarray] = []

    def grab(self, data: mujoco.MjData, lookat=None, keep: bool = True) -> np.ndarray:
        if lookat is not None:
            self.cam.lookat[:] = lookat
        self.r.update_scene(data, self.cam)
        img = self.r.render().copy()
        if keep:
            self.frames.append(img)
        return img

    def save_png(self, path: Path, img: np.ndarray | None = None) -> None:
        from PIL import Image

        Image.fromarray(img if img is not None else self.frames[-1]).save(path, optimize=True)

    def save_gif(self, path: Path, fps: int = 10, colors: int = 48) -> None:
        from PIL import Image

        ims = [Image.fromarray(f).quantize(colors=colors, method=Image.Quantize.MEDIANCUT) for f in self.frames]
        ims[0].save(path, save_all=True, append_images=ims[1:], duration=int(1000 / fps), loop=0, optimize=True)

    def close(self) -> None:
        self.r.close()
