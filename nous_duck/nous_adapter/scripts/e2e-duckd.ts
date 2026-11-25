// 端到端檢查：這個 repo 的 hub＋DuckAdapter（TypeScript）對「另一個獨立實作的鴨子端」（robot/duckd，Python）。
// 目的是確認兩個實作照同一份 duck-link schema 講得通，並把每個工具的結果印出來給人看。
//
// 用法（鴨子端要另外啟動，並連到同一個埠）：
//   npx tsx scripts/e2e-duckd.ts --port 18792 [--json 輸出檔]
// 這個腳本只下「不會動腿」的指令：status、look（小角度）、gesture、express、track、presence、stop，
// 以及會被沒有對應硬體的鴨子拒絕的 walk／go_to（用來確認拒絕與 unsupported 的對應）。
// 對面是 mock 還是實機由鴨子自己在 hello／state 的 mock 欄位說明，這裡照實印出來。
import { writeFileSync } from "node:fs";
import { DuckAdapter, DUCK_TOOL } from "../adapters/duck.ts";
import { devExecute } from "../cli/dev-dispatch.ts";
import { DuckLinkHub } from "../hub/duck-link-hub.ts";
import type { ToolResult } from "../shared/aios-contracts.ts";

const arg = (name: string) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
};
const port = Number(arg("port") ?? 18792);
const waitS = Number(arg("wait") ?? 30);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const logs: string[] = [];
const hub = new DuckLinkHub({ port, log: (l) => logs.push(l) });
const adapter = new DuckAdapter(hub);
const events: string[] = [];
hub.onEvent((e) => events.push(`${e.event}${e.reason ? `(${e.reason})` : ""}`));

await hub.start();
console.log(`hub 在 ws://127.0.0.1:${port}/duck-link 等鴨子（最多 ${waitS} 秒）…`);
const deadline = Date.now() + waitS * 1000;
while (!(hub.snapshot().connected && hub.snapshot().state) && Date.now() < deadline) await sleep(100);
const first = hub.snapshot();
if (!first.connected || !first.state) {
  console.error("鴨子沒有連上或沒有送 state。hub 的紀錄：\n" + logs.join("\n"));
  await hub.stop();
  process.exit(3);
}
console.log(`鴨子：${first.hello?.software}  duck_id=${first.hello?.duck_id}  mock=${first.hello?.mock === true}`);
console.log(`能力：${JSON.stringify(Object.fromEntries(Object.entries(first.state.capabilities).map(([k, v]) => [k, v?.status])))}`);
console.log(`動作清單：${JSON.stringify(first.hello?.gestures ?? [])}  表情：${JSON.stringify(first.hello?.expressions ?? [])}`);

const gesture = first.hello?.gestures?.[0];
const expression = first.hello?.expressions?.find((e) => e !== first.state?.expression) ?? first.hello?.expressions?.[0];
const steps: [string, string, Record<string, unknown>][] = [
  ["status", DUCK_TOOL.status, {}],
  ["look 小角度", DUCK_TOOL.look, { head_yaw: 0.1, duration_s: 1 }],
  ["look 超出範圍（看夾限）", DUCK_TOOL.look, { head_yaw: 1.5, duration_s: 1 }],
  ["look 回正", DUCK_TOOL.look, { head_yaw: 0, head_pitch: 0, head_roll: 0, neck_pitch: 0, duration_s: 1 }],
  ...(gesture ? ([[`gesture ${gesture}`, DUCK_TOOL.gesture, { name: gesture }]] as [string, string, Record<string, unknown>][]) : []),
  ["gesture 不存在的名稱", DUCK_TOOL.gesture, { name: "backflip_zz" }],
  ...(expression ? ([[`express ${expression}`, DUCK_TOOL.express, { expression }]] as [string, string, Record<string, unknown>][]) : []),
  ["antennas", DUCK_TOOL.antennas, { left: 0.3, right: -0.3 }],
  ["track face", DUCK_TOOL.track, { target: "face", timeout_s: 5 }],
  ["track none", DUCK_TOOL.track, { target: "none" }],
  ["walk（預期被拒或 unsupported）", DUCK_TOOL.walk, { vx: 0.05, duration_s: 1 }],
  ["where", DUCK_TOOL.where, {}],
  ["places", DUCK_TOOL.places, {}],
  ["go_to（預期被拒或 unsupported）", DUCK_TOOL.goTo, { place: "living_room" }],
  ["mission_status", DUCK_TOOL.missionStatus, {}],
  ["cancel_mission（沒有任務）", DUCK_TOOL.cancelMission, {}],
  ["wait_here", DUCK_TOOL.waitHere, {}],
  ["stop", DUCK_TOOL.stop, {}],
];

const rows: { step: string; tool: string; args: unknown; ms: number; result: ToolResult }[] = [];
for (const [step, tool, args] of steps) {
  const t0 = Date.now();
  const result = await devExecute(adapter, tool, args);
  rows.push({ step, tool, args, ms: Date.now() - t0, result });
  const d = (result.data ?? {}) as Record<string, unknown>;
  const notes = ["duck_reason", "capability", "clamped", "reached", "evidence", "mission_id"].filter((k) => d[k] !== undefined).map((k) => `${k}=${JSON.stringify(d[k])}`);
  console.log(`${step.padEnd(34)} ${result.status.padEnd(11)} ${String(Date.now() - t0).padStart(5)} ms  ${notes.join(" ")}\n    ${result.message}`);
  await sleep(300);
}

console.log("\npresence（由這個腳本直接送，不是 Nous 的事件）：");
const presence: Record<string, string> = {};
for (const state of ["wake", "listening", "thinking", "speaking", "working", "error", "sleeping", "idle"] as const) {
  const result = await adapter.presence(state, state === "speaking" ? 0.5 : undefined);
  presence[state] = result.status;
  console.log(`  ${state.padEnd(10)} ${result.status}  ${result.message}`);
  await sleep(400);
}

await sleep(1500);
const end = hub.snapshot();
console.log(`\n往返時間（最近一次心跳）：${end.rttMs} ms`);
console.log(`計數：${JSON.stringify(end.counters)}`);
console.log(`收到的事件：${events.join("、") || "無"}`);
if (logs.some((l) => l.includes("不合 schema"))) console.log("hub 紀錄裡不合 schema 的訊息：\n" + logs.filter((l) => l.includes("schema")).join("\n"));

const out = arg("json");
if (out) writeFileSync(out, JSON.stringify({ port, duck: end.hello, rows, presence, events, counters: end.counters, rtt_ms: end.rttMs, hubLog: logs }, null, 2));
await hub.stop();
// 協定層的問題（任何一邊送了不合 schema 的訊息）才算這個檢查失敗；工具被鴨子拒絕是正常的結果。
process.exit(end.counters.rxInvalid || end.counters.txInvalid ? 1 : 0);
