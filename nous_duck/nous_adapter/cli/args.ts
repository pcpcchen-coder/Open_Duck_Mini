import type { InputSchema } from "../shared/aios-contracts.ts";

// duckctl 的參數解析：把「duckctl look --yaw 0.2」這種寫法轉成工具的參數物件。
// 規則：--head-yaw 與 --head_yaw 相同；每個工具有幾個短別名與一個位置參數；值依工具 inputSchema 的型別轉換。

/** 每個工具的第一個位置參數對應到哪個欄位（duckctl gesture nod → { name: "nod" }）。 */
export const POSITIONAL: Record<string, string> = {
  gesture: "name",
  express: "expression",
  go_to: "place",
  find_person: "person",
  track: "target",
  mission_status: "mission_id",
  cancel_mission: "mission_id",
};

/** 短別名（只在該工具內有效）。 */
export const ALIASES: Record<string, Record<string, string>> = {
  look: { yaw: "head_yaw", pitch: "head_pitch", roll: "head_roll", neck: "neck_pitch", time: "duration_s", duration: "duration_s" },
  walk: { yaw: "yaw_rate", time: "duration_s", duration: "duration_s" },
  express: { time: "duration_s", duration: "duration_s" },
  track: { timeout: "timeout_s" },
  follow_me: { distance: "distance_m" },
  wait_here: { timeout: "timeout_min" },
};

const DEGREE_FIELDS = ["neck_pitch", "head_pitch", "head_yaw", "head_roll"];

export interface ParsedArgs {
  args: Record<string, unknown>;
  flags: { json: boolean; deg: boolean };
}

export function parseToolArgs(action: string, argv: readonly string[], schema: InputSchema): ParsedArgs {
  const args: Record<string, unknown> = {};
  const flags = { json: false, deg: false };
  const aliases = ALIASES[action] ?? {};
  const rest = [...argv];
  while (rest.length) {
    const token = rest.shift()!;
    if (token === "--json") {
      flags.json = true;
      continue;
    }
    if (token === "--deg") {
      flags.deg = true;
      continue;
    }
    if (!token.startsWith("--")) {
      const field = POSITIONAL[action];
      if (!field || args[field] !== undefined) throw new Error(`多出來的參數：${token}`);
      args[field] = token;
      continue;
    }
    let [rawKey, value] = token.slice(2).split("=", 2) as [string, string | undefined];
    const key = aliases[rawKey.replaceAll("-", "_")] ?? rawKey.replaceAll("-", "_");
    const prop = schema.properties[key];
    if (!prop) throw new Error(`這個工具沒有參數 --${rawKey}（可用：${Object.keys(schema.properties).map((k) => `--${k}`).join("、") || "無"}）`);
    if (prop.type === "boolean") {
      // 布林值可以只寫旗標（--body）或寫 --body=false。
      args[key] = value === undefined ? true : value !== "false" && value !== "0";
      continue;
    }
    // 負數（--yaw -0.2）也是值，不是下一個旗標。
    if (value === undefined) value = rest.shift();
    if (value === undefined) throw new Error(`--${rawKey} 後面要接一個值`);
    if (prop.type === "string") {
      args[key] = value;
    } else {
      const n = Number(value);
      if (!Number.isFinite(n)) throw new Error(`--${rawKey} 要是數字，收到「${value}」`);
      args[key] = n;
    }
  }
  if (flags.deg) {
    for (const field of DEGREE_FIELDS) if (typeof args[field] === "number") args[field] = Number((((args[field] as number) * Math.PI) / 180).toFixed(4));
  }
  return { args, flags };
}
