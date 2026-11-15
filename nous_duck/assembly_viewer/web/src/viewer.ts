// three.js 場景：載入零件、組裝／爆炸／透視、步驟狀態著色、點選、舵機 ID 與方位標籤。
// 座標沿用 pipeline：+X 是鴨子的左邊、+Y 上、+Z 前，單位毫米。
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { decodeMesh } from "./data";
import type { Part, Scene, Servo, Vec3 } from "./types";

/** 透視模式下變半透明的外殼。 */
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

/** 每個零件在畫面上的狀態。 */
export type PartState = "normal" | "current" | "focus" | "done" | "ghost" | "hidden";

export type CameraView = "iso" | "front" | "left" | "back" | "right" | "top";

interface PartObject {
  part: Part;
  mesh: THREE.Mesh;
  state: PartState;
}

const COLORS = {
  current: new THREE.Color("#e8862a"),
  focus: new THREE.Color("#2f8fd8"),
  selected: new THREE.Color("#18a058"),
};

export class Viewer {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: OrbitControls;
  private readonly objects = new Map<string, PartObject>();
  private readonly pickables: THREE.Mesh[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly labelLayer: HTMLElement;
  private readonly servoLabels: { servo: Servo; el: HTMLElement; anchor: THREE.Vector3 }[] = [];
  private readonly sideLabels: { el: HTMLElement; anchor: THREE.Vector3 }[] = [];
  private explode = 0;
  private xray = false;
  private selection = new Set<string>();
  private isolate = false;
  private showServoLabels = true;
  private needsRender = true;
  private tween: { from: THREE.Vector3; to: THREE.Vector3; camFrom: THREE.Vector3; camTo: THREE.Vector3; t0: number } | null =
    null;
  onPick: (partId: string | null) => void = () => {};

  constructor(
    private readonly container: HTMLElement,
    private readonly data: Scene,
    meshBin: ArrayBuffer,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setClearColor(0x000000, 0); // 透明背景，顏色交給 CSS（深淺色主題）
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.setAttribute("aria-label", "Open Duck Mini v2 3D 模型");

    this.labelLayer = document.createElement("div");
    this.labelLayer.className = "label-layer";
    container.appendChild(this.labelLayer);

    this.camera = new THREE.PerspectiveCamera(35, 1, 5, 20000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
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

    this.buildParts(meshBin);
    this.buildLabels();
    this.setView("iso", false);

    const ro = new ResizeObserver(() => this.resize());
    ro.observe(container);
    this.resize();
    this.bindPointer();
    const loop = (t: number) => {
      this.stepTween(t);
      if (this.needsRender) this.render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  private buildParts(meshBin: ArrayBuffer): void {
    const geometries = new Map<string, THREE.BufferGeometry>();
    for (const [name, rec] of Object.entries(this.data.meshes)) geometries.set(name, decodeMesh(meshBin, rec));
    for (const part of this.data.parts) {
      const geom = geometries.get(part.mesh);
      if (!geom) throw new Error(`零件 ${part.id} 找不到網格 ${part.mesh}`);
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(part.color),
        flatShading: true,
        roughness: part.kind === "servo_part" ? 0.45 : 0.7,
        metalness: part.kind === "bearing" ? 0.5 : 0.05,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.quaternion.set(...part.quaternion_xyzw);
      mesh.userData.partId = part.id;
      mesh.matrixAutoUpdate = true;
      this.scene.add(mesh);
      this.objects.set(part.id, { part, mesh, state: "normal" });
      this.pickables.push(mesh);
    }
    this.applyLayout();
  }

  private buildLabels(): void {
    const byId = new Map(this.data.parts.map((p) => [p.id, p]));
    for (const servo of this.data.servos) {
      const el = document.createElement("div");
      el.className = `servo-label side-${servo.side}`;
      el.textContent = String(servo.id);
      el.title = `舵機 ID ${servo.id}`;
      this.labelLayer.appendChild(el);
      // 標籤跟著舵機一起爆炸：用舵機第一個網格的爆炸向量
      const ex = byId.get(servo.parts[0])?.explode_mm ?? [0, 0, 0];
      this.servoLabels.push({ servo, el, anchor: new THREE.Vector3(...servo.horn_center_mm) });
      el.dataset.ex = ex.join(",");
    }
    const { bbox_min_mm: lo, bbox_max_mm: hi } = this.data.summary;
    const sides: [string, string, Vec3][] = [
      ["鴨子的左邊 L", "side-left", [hi[0] + 110, 0, 40]],
      ["鴨子的右邊 R", "side-right", [lo[0] - 110, 0, 40]],
      ["前 Front", "side-front", [0, 0, hi[2] + 90]],
    ];
    for (const [text, cls, pos] of sides) {
      const el = document.createElement("div");
      el.className = `side-label ${cls}`;
      el.textContent = text;
      this.labelLayer.appendChild(el);
      this.sideLabels.push({ el, anchor: new THREE.Vector3(...pos) });
    }
  }

  private applyLayout(): void {
    for (const { part, mesh } of this.objects.values()) {
      const [x, y, z] = part.position_mm;
      const [ex, ey, ez] = part.explode_mm;
      mesh.position.set(x + ex * this.explode, y + ey * this.explode, z + ez * this.explode);
    }
    this.requestRender();
  }

  setExplode(amount: number): void {
    this.explode = amount;
    this.applyLayout();
  }

  setXray(on: boolean): void {
    this.xray = on;
    this.refreshMaterials();
  }

  setServoLabels(on: boolean): void {
    this.showServoLabels = on;
    this.requestRender();
  }

  setStates(states: Map<string, PartState>): void {
    for (const obj of this.objects.values()) obj.state = states.get(obj.part.id) ?? "normal";
    this.refreshMaterials();
  }

  setSelection(ids: Iterable<string>, isolate: boolean): void {
    this.selection = new Set(ids);
    this.isolate = isolate && this.selection.size > 0;
    this.refreshMaterials();
  }

  private refreshMaterials(): void {
    for (const { part, mesh, state } of this.objects.values()) {
      const mat = mesh.material as THREE.MeshStandardMaterial;
      const selected = this.selection.has(part.id);
      let visible = state !== "hidden";
      if (this.isolate) visible = selected;
      mesh.visible = visible;
      let opacity = 1;
      if (state === "ghost") opacity = 0.12;
      else if (state === "done") opacity = 0.85;
      if (this.xray && SHELL_MESHES.has(part.mesh) && !selected && state !== "current") opacity = Math.min(opacity, 0.16);
      mat.transparent = opacity < 1;
      mat.opacity = opacity;
      mat.depthWrite = opacity >= 0.5;
      mat.emissive.set(0x000000);
      mat.emissiveIntensity = 0;
      mat.color.set(part.color);
      if (selected) {
        mat.emissive.copy(COLORS.selected);
        mat.emissiveIntensity = 0.55;
      } else if (state === "current") {
        mat.color.lerp(COLORS.current, 0.55);
        mat.emissive.copy(COLORS.current);
        mat.emissiveIntensity = 0.25;
      } else if (state === "focus") {
        mat.color.lerp(COLORS.focus, 0.5);
        mat.emissive.copy(COLORS.focus);
        mat.emissiveIntensity = 0.2;
      }
      mesh.renderOrder = mat.transparent ? 2 : 0;
      mat.needsUpdate = true;
    }
    this.requestRender();
  }

  /** 把鏡頭對準一組零件（有動畫）。 */
  frameParts(ids: string[], animate = true): void {
    const box = new THREE.Box3();
    for (const id of ids) {
      const obj = this.objects.get(id);
      if (obj?.mesh.visible) box.expandByObject(obj.mesh);
    }
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    const dist = Math.max(size * 1.6, 260) / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)));
    this.moveCamera(center, center.clone().add(dir.multiplyScalar(Math.min(dist, 2400))), animate);
  }

  setView(view: CameraView, animate = true): void {
    const target = new THREE.Vector3(0, 215, 0);
    const d = 1350;
    const dirs: Record<CameraView, Vec3> = {
      iso: [0.55, 0.42, 0.72],
      front: [0, 0.08, 1],
      back: [0, 0.08, -1],
      left: [1, 0.08, 0],
      right: [-1, 0.08, 0],
      top: [0.001, 1, 0.002],
    };
    const dir = new THREE.Vector3(...dirs[view]).normalize().multiplyScalar(d);
    this.moveCamera(target, target.clone().add(dir), animate);
  }

  private moveCamera(target: THREE.Vector3, position: THREE.Vector3, animate: boolean): void {
    if (!animate) {
      this.controls.target.copy(target);
      this.camera.position.copy(position);
      this.controls.update();
      this.requestRender();
      return;
    }
    this.tween = {
      from: this.controls.target.clone(),
      to: target,
      camFrom: this.camera.position.clone(),
      camTo: position,
      t0: performance.now(),
    };
    this.requestRender();
  }

  private stepTween(now: number): void {
    if (!this.tween) return;
    const k = Math.min(1, (now - this.tween.t0) / 450);
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    this.controls.target.lerpVectors(this.tween.from, this.tween.to, e);
    this.camera.position.lerpVectors(this.tween.camFrom, this.tween.camTo, e);
    this.controls.update();
    if (k >= 1) this.tween = null;
    this.needsRender = true;
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
        this.pickables.filter((m) => m.visible && (m.material as THREE.Material).opacity > 0.3),
        false,
      );
      this.onPick(hits.length ? (hits[0].object.userData.partId as string) : null);
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
    this.renderer.render(this.scene, this.camera);
    this.updateLabels();
  }

  private project(p: THREE.Vector3, el: HTMLElement): void {
    const v = p.clone().project(this.camera);
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    const inside = v.z < 1 && Math.abs(v.x) <= 1.05 && Math.abs(v.y) <= 1.05;
    el.style.display = inside ? "" : "none";
    if (inside) el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -50%)`;
  }

  private updateLabels(): void {
    for (const { servo, el, anchor } of this.servoLabels) {
      const obj = this.objects.get(servo.parts[0]);
      if (!this.showServoLabels || !obj?.mesh.visible) {
        el.style.display = "none";
        continue;
      }
      const ex = (el.dataset.ex ?? "0,0,0").split(",").map(Number);
      const p = anchor.clone().add(new THREE.Vector3(ex[0], ex[1], ex[2]).multiplyScalar(this.explode));
      this.project(p, el);
      el.classList.toggle("is-selected", servo.parts.some((id) => this.selection.has(id)));
    }
    for (const { el, anchor } of this.sideLabels) this.project(anchor, el);
  }
}
