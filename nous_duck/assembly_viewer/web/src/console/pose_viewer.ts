// 會動的 3D 鴨子：沿用組裝檢視器的網格與零件位置，依 body 樹分組，用關節角度擺姿勢。
//
// 做法（product of exponentials）：scene.json 的零件、關節位置與轉軸都是「全部關節 0 度」時的世界座標。
// 每個有關節的 body 是一個 Group，區域矩陣 = 平移(p)·旋轉(軸, q)·平移(−p)，子 body 的 Group 掛在父 Group 底下，
// 世界矩陣就會一路相乘。關節角度與 MuJoCo 的 qpos 相同（上游 runtime 也直接用這個角度）。
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { decodeMesh } from "../data";
import type { Vec3 } from "../types";
import type { ConsoleScene } from "./types";

const SHELL_MESHES = new Set([
  "body_front",
  "body_back",
  "body_middle_bottom",
  "body_middle_top",
  "battery_pack_lid",
  "head",
  "head_bot_sheet",
  "left_cache",
  "right_cache",
]);

export type CameraView = "iso" | "front" | "left" | "right" | "back" | "top";

interface JointNode {
  group: THREE.Group;
  pivot: THREE.Vector3;
  axis: THREE.Vector3;
}

const SELECTED = new THREE.Color("#18a058");
const OFF = new THREE.Color("#8a8f98");

export class PoseViewer {
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(35, 1, 5, 20000);
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: OrbitControls;
  private readonly groups = new Map<string, THREE.Group>();
  private readonly joints = new Map<string, JointNode>();
  private readonly meshes: { mesh: THREE.Mesh; servoId: number | null; shell: boolean; color: string }[] = [];
  private readonly labels: { id: number; el: HTMLElement; anchor: THREE.Vector3; body: string }[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly labelLayer: HTMLElement;
  private selected: number | null = null;
  private limp = new Set<number>();
  private xray = false;
  private showLabels = true;
  private needsRender = true;
  onPickServo: (id: number | null) => void = () => {};

  constructor(
    private readonly container: HTMLElement,
    private readonly data: ConsoleScene,
    meshBin: ArrayBuffer,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.setAttribute("aria-label", "鴨子目前姿勢的 3D 模型");
    this.labelLayer = document.createElement("div");
    this.labelLayer.className = "label-layer";
    container.appendChild(this.labelLayer);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener("change", () => this.requestRender());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a96, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(400, 900, 700);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.9);
    fill.position.set(-600, 300, -500);
    this.scene.add(fill);
    const grid = new THREE.GridHelper(600, 12, 0x9aa0aa, 0xc9ced6);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.5;
    this.scene.add(grid);

    this.buildTree();
    this.buildParts(meshBin);
    this.buildLabels();
    this.setView("iso");
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.bindPointer();
    const loop = () => {
      if (this.needsRender) this.render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  private buildTree(): void {
    for (const b of this.data.bodies) {
      const g = new THREE.Group();
      g.name = b.name;
      g.matrixAutoUpdate = false;
      this.groups.set(b.name, g);
    }
    for (const b of this.data.bodies) {
      const g = this.groups.get(b.name)!;
      const parent = b.parent ? this.groups.get(b.parent) : null;
      (parent ?? this.scene).add(g);
    }
    for (const j of this.data.joints) {
      const group = this.groups.get(j.body);
      if (!group) throw new Error(`關節 ${j.name} 的 body ${j.body} 不存在`);
      this.joints.set(j.name, { group, pivot: new THREE.Vector3(...j.position_mm), axis: new THREE.Vector3(...j.axis).normalize() });
    }
  }

  private buildParts(meshBin: ArrayBuffer): void {
    const geometries = new Map<string, THREE.BufferGeometry>();
    for (const [name, rec] of Object.entries(this.data.meshes)) geometries.set(name, decodeMesh(meshBin, rec));
    for (const part of this.data.parts) {
      const geom = geometries.get(part.mesh);
      const group = this.groups.get(part.body);
      if (!geom || !group) throw new Error(`零件 ${part.id} 缺少網格或 body`);
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(part.color),
        flatShading: true,
        roughness: part.kind === "servo_part" ? 0.45 : 0.7,
        metalness: part.kind === "bearing" ? 0.5 : 0.05,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(...part.position_mm);
      mesh.quaternion.set(...part.quaternion_xyzw);
      mesh.userData.servoId = part.servo_id;
      group.add(mesh);
      this.meshes.push({ mesh, servoId: part.servo_id, shell: SHELL_MESHES.has(part.mesh), color: part.color });
    }
    this.refreshMaterials();
  }

  private buildLabels(): void {
    for (const s of this.data.servos) {
      const el = document.createElement("div");
      el.className = `servo-label side-${s.side}`;
      el.textContent = String(s.id);
      this.labelLayer.appendChild(el);
      this.labels.push({ id: s.id, el, anchor: new THREE.Vector3(...(s.horn_center_mm as Vec3)), body: s.body });
    }
  }

  /** 依關節角度（rad）擺姿勢；沒給的關節維持 0。 */
  setAngles(angles: Record<string, number | null | undefined>): void {
    const m = new THREE.Matrix4();
    const r = new THREE.Matrix4();
    const t = new THREE.Matrix4();
    for (const [name, node] of this.joints) {
      const q = angles[name] ?? 0;
      m.makeTranslation(node.pivot.x, node.pivot.y, node.pivot.z);
      r.makeRotationAxis(node.axis, q);
      t.makeTranslation(-node.pivot.x, -node.pivot.y, -node.pivot.z);
      node.group.matrix.copy(m.multiply(r).multiply(t));
      node.group.matrixWorldNeedsUpdate = true;
    }
    this.requestRender();
  }

  setSelected(id: number | null): void {
    this.selected = id;
    this.refreshMaterials();
  }

  /** 沒出力的舵機畫成灰色。 */
  setLimp(ids: Iterable<number>): void {
    const next = new Set(ids);
    if (next.size === this.limp.size && [...next].every((i) => this.limp.has(i))) return;
    this.limp = next;
    this.refreshMaterials();
  }

  setXray(on: boolean): void {
    this.xray = on;
    this.refreshMaterials();
  }

  setLabels(on: boolean): void {
    this.showLabels = on;
    this.requestRender();
  }

  private refreshMaterials(): void {
    for (const { mesh, servoId, shell, color } of this.meshes) {
      const mat = mesh.material as THREE.MeshStandardMaterial;
      mat.color.set(color);
      mat.emissive.set(0x000000);
      mat.emissiveIntensity = 0;
      if (servoId !== null && this.limp.has(servoId)) mat.color.lerp(OFF, 0.6);
      if (servoId !== null && servoId === this.selected) {
        mat.emissive.copy(SELECTED);
        mat.emissiveIntensity = 0.6;
      }
      const opacity = this.xray && shell ? 0.16 : 1;
      mat.transparent = opacity < 1;
      mat.opacity = opacity;
      mat.depthWrite = opacity >= 0.5;
      mesh.renderOrder = mat.transparent ? 2 : 0;
      mat.needsUpdate = true;
    }
    this.requestRender();
  }

  setView(view: CameraView): void {
    const target = new THREE.Vector3(0, 200, 0);
    const dirs: Record<CameraView, Vec3> = {
      iso: [0.55, 0.42, 0.72],
      front: [0, 0.08, 1],
      back: [0, 0.08, -1],
      left: [1, 0.08, 0],
      right: [-1, 0.08, 0],
      top: [0.001, 1, 0.002],
    };
    const dir = new THREE.Vector3(...dirs[view]).normalize().multiplyScalar(1250);
    this.controls.target.copy(target);
    this.camera.position.copy(target.clone().add(dir));
    this.controls.update();
    this.requestRender();
  }

  private bindPointer(): void {
    const el = this.renderer.domElement;
    let down: { x: number; y: number } | null = null;
    el.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }));
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
      down = null;
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      this.raycaster.setFromCamera(ndc, this.camera);
      const hits = this.raycaster.intersectObjects(
        this.meshes.filter((m) => (m.mesh.material as THREE.Material).opacity > 0.3).map((m) => m.mesh),
        false,
      );
      const hit = hits.find((h) => h.object.userData.servoId !== null);
      this.onPickServo(hits.length && hit === hits[0] ? (hit!.object.userData.servoId as number) : null);
    });
  }

  requestRender(): void {
    this.needsRender = true;
  }

  private resize(): void {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  private render(): void {
    this.needsRender = false;
    this.scene.updateMatrixWorld();
    this.renderer.render(this.scene, this.camera);
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    for (const { id, el, anchor, body } of this.labels) {
      const g = this.groups.get(body);
      if (!this.showLabels || !g) {
        el.style.display = "none";
        continue;
      }
      const v = anchor.clone().applyMatrix4(g.matrixWorld).project(this.camera);
      const inside = v.z < 1 && Math.abs(v.x) <= 1.05 && Math.abs(v.y) <= 1.05;
      el.style.display = inside ? "" : "none";
      if (inside) el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -50%)`;
      el.classList.toggle("is-selected", id === this.selected);
    }
  }
}
