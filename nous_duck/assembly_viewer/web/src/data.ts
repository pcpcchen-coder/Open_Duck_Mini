// 讀取頁面內嵌的資料：JSON 放在 <script type="application/json">，網格是 gzip 後 base64 的 meshes.bin。
import * as THREE from "three";
import type { Bundle, MeshRecord } from "./types";

export function readBundle(): Bundle {
  const el = document.getElementById("viewer-data");
  if (!el?.textContent) throw new Error("頁面裡找不到檢視器資料（viewer-data）");
  const bundle = JSON.parse(el.textContent) as Bundle;
  if (bundle.scene.schema !== "nous-duck/viewer-scene@1") throw new Error(`不支援的 scene 版本：${bundle.scene.schema}`);
  if (bundle.steps.schema !== "nous-duck/viewer-steps@1") throw new Error(`不支援的 steps 版本：${bundle.steps.schema}`);
  return bundle;
}

export async function readMeshBin(expectedBytes: number): Promise<ArrayBuffer> {
  const el = document.getElementById("mesh-data");
  if (!el?.textContent) throw new Error("頁面裡找不到網格資料（mesh-data）");
  if (typeof DecompressionStream === "undefined") {
    throw new Error("這個瀏覽器不支援 DecompressionStream，請改用較新版本的 Chrome、Edge、Firefox 或 Safari。");
  }
  const raw = atob(el.textContent.trim());
  const gz = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) gz[i] = raw.charCodeAt(i);
  const stream = new Blob([gz]).stream().pipeThrough(new DecompressionStream("gzip"));
  const buf = await new Response(stream).arrayBuffer();
  if (buf.byteLength !== expectedBytes) {
    throw new Error(`網格資料大小不符：${buf.byteLength} bytes，預期 ${expectedBytes} bytes`);
  }
  return buf;
}

/** 依 pipeline 的量化格式還原一種網格：位置 = bbox_min_mm + q × step_mm。 */
export function decodeMesh(buf: ArrayBuffer, rec: MeshRecord): THREE.BufferGeometry {
  const q = new Uint16Array(buf, rec.vertex_offset, rec.vertex_count * 3);
  const pos = new Float32Array(rec.vertex_count * 3);
  for (let i = 0; i < rec.vertex_count; i++) {
    for (let k = 0; k < 3; k++) pos[i * 3 + k] = rec.bbox_min_mm[k] + q[i * 3 + k] * rec.step_mm[k];
  }
  const index =
    rec.index_type === "uint16"
      ? new Uint16Array(buf, rec.index_offset, rec.index_count)
      : new Uint32Array(buf, rec.index_offset, rec.index_count);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(index, 1));
  g.computeBoundingBox();
  g.computeBoundingSphere();
  return g;
}
