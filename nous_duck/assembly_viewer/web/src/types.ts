// pipeline 輸出的資料型別：scene.json（nous-duck/viewer-scene@1）與 steps.json（nous-duck/viewer-steps@1）。
// 欄位說明見 ../../pipeline/README.md。

export type Vec3 = [number, number, number];

export interface MeshRecord {
  vertex_offset: number;
  vertex_count: number;
  index_offset: number;
  index_count: number;
  index_type: "uint16" | "uint32";
  triangle_count: number;
  bbox_min_mm: Vec3;
  step_mm: Vec3;
  source: string;
}

export type PartKind = "printed" | "servo_part" | "electronics" | "power" | "bearing" | "other";

export interface Part {
  id: string;
  mesh: string;
  body: string;
  kind: PartKind;
  name_zh: string;
  name_en: string;
  print_stl: string | null;
  servo_id: number | null;
  placement: "cad" | "print_frame";
  identification: string | null;
  color: string;
  position_mm: Vec3;
  quaternion_xyzw: [number, number, number, number];
  center_mm: Vec3;
  explode_mm: Vec3;
}

export interface Servo {
  id: number;
  joint: string;
  side: "left" | "right" | "center";
  body: string;
  parts: string[];
  horn_center_mm: Vec3;
}

export interface Scene {
  schema: string;
  robot: string;
  sources: Record<string, string>;
  summary: {
    height_mm: number;
    height_without_antennas_mm: number;
    part_instances: number;
    printed_pieces: number;
    print_stl_types: number;
    servos: number;
    unique_meshes: number;
    triangles_unique: number;
    meshes_bin_bytes: number;
    bbox_min_mm: Vec3;
    bbox_max_mm: Vec3;
  };
  meshes: Record<string, MeshRecord>;
  servos: Servo[];
  parts: Part[];
}

export interface StepSource {
  label: string;
  path?: string;
  url?: string;
}

export interface Step {
  id: string;
  title: string;
  summary: string;
  tasks: string[];
  check: string;
  warnings: string[];
  optional: boolean;
  show_all: boolean;
  adds: string[];
  focus: string[];
  sources: StepSource[];
}

export interface Steps {
  schema: string;
  steps: Step[];
}

/** build.mjs 寫進頁面的建置資訊。 */
export interface BuildInfo {
  built_at: string;
  git_commit: string;
  repo_url: string;
  three_version: string;
}

export interface Bundle {
  scene: Scene;
  steps: Steps;
  build: BuildInfo;
}
