// 舵機控制台的型別：scene.json 裡檢視器沒用到的 bodies／joints，以及伺服器 /api/state 的回應。
import type { Scene, Vec3 } from "../types";

export interface SceneBody {
  name: string;
  parent: string | null;
  joint: string | null;
}

export interface SceneJoint {
  name: string;
  body: string;
  parent_body: string | null;
  servo_id: number | null;
  position_mm: Vec3;
  axis: Vec3;
  range_rad: [number, number] | null;
}

export interface ConsoleScene extends Scene {
  bodies: SceneBody[];
  joints: SceneJoint[];
}

export interface ConsoleBuild {
  built_at: string;
  git_commit: string;
  repo_url: string;
  three_version: string;
}

export interface ConsoleBundle {
  scene: ConsoleScene;
  build: ConsoleBuild;
}

export interface JointState {
  name: string;
  id: number;
  zh: string;
  group: "right_leg" | "left_leg" | "head";
  lo_deg: number;
  hi_deg: number;
  actual_deg: number | null;
  target_deg: number | null;
  cmd_deg: number | null;
  torque: boolean | null;
  temperature: number | null;
  voltage: number | null;
  load: number | null;
  kp: number | null;
  offset_deg: number;
  offset_saved_deg: number;
  current_ma: number | null;
  status: string[];
}

export interface PowerSummary {
  available: boolean;
  battery_v?: number;
  cell_v?: number;
  servo_v_min?: number;
  servo_v_max?: number;
  current_a?: number | null;
  power_w?: number | null;
  temp_max_c?: number | null;
  torque_on?: number;
  flagged?: number[];
}

export interface HistorySample {
  t: number;
  battery_v: number | null;
  v_min: number | null;
  v_max: number | null;
  current_a: number | null;
  power_w: number | null;
  temp_max_c: number | null;
  cpu_temp_c: number | null;
  throttled: number | null;
}

export interface Alarm {
  key: string;
  level: "warn" | "stop";
  message: string;
}

export interface LogEvent {
  t: number;
  level: "info" | "warn" | "error";
  message: string;
}

export interface PoseItem {
  key: string;
  label: string;
  builtin: boolean;
}

export interface ImuState {
  ok: boolean;
  mock?: boolean;
  error?: string;
  euler_deg?: (number | null)[];
  accel?: (number | null)[];
  gyro?: (number | null)[];
  calibration?: number[];
  temperature_c?: number | null;
}

export interface FeetState {
  ok: boolean;
  mock?: boolean;
  error?: string;
  left?: boolean;
  right?: boolean;
}

export interface PiState {
  throttled?: string | null;
  throttled_value?: number | null;
  volts?: Record<string, number | null>;
  arm_mhz?: number | null;
  throttled_flags?: string[];
  cpu_temp_c?: number | null;
  load?: number[] | null;
  mem_used_mb?: number | null;
  mem_total_mb?: number | null;
  uptime_s?: number | null;
}

export interface ConsoleState {
  ok: boolean;
  version: string;
  auth: boolean;
  mock: boolean;
  connected: boolean;
  estop: string | null;
  alarms: Alarm[];
  speed_deg: number;
  speed_choices: number[];
  kp_choices: number[];
  offsets_dirty: boolean;
  config_path: string;
  joints: JointState[];
  poses: PoseItem[];
  limits: { temp_warn_c: number; temp_stop_c: number; volt_warn_v: number; volt_stop_v: number; heartbeat_s: number };
  events: LogEvent[];
  imu: ImuState;
  feet: FeetState;
  pi: PiState;
  power: PowerSummary;
  sounds: string[];
}
