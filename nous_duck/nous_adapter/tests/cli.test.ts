import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { DUCK_TOOLS } from "../adapters/duck.ts";
import { parseToolArgs } from "../cli/args.ts";
import { ControlClient } from "../cli/control.ts";
import { devExecute, validateArgs } from "../cli/dev-dispatch.ts";
import { runHub, type RunningHub } from "../cli/hub-main.ts";
import { MockDuck } from "../mock/mock-duck.ts";
import { toolResult, type IntegrationAdapter, type ToolResult } from "../shared/aios-contracts.ts";
import { until } from "./helpers.ts";

// duckctl 的三個部分：參數解析、開發用 Dispatcher、hub 行程的控制通道（對 mock 鴨子）。

const schemaOf = (action: string) => DUCK_TOOLS.find((t) => t.id === `app.duck.${action}`)!.inputSchema;

describe("參數解析", () => {
  it("短別名、負數、連字號與等號", () => {
    expect(parseToolArgs("look", ["--yaw", "-0.2", "--pitch=0.1", "--time", "1.5"], schemaOf("look")).args).toEqual({ head_yaw: -0.2, head_pitch: 0.1, duration_s: 1.5 });
    expect(parseToolArgs("look", ["--head-yaw", "0.3"], schemaOf("look")).args).toEqual({ head_yaw: 0.3 });
    expect(parseToolArgs("walk", ["--vx", "0.05", "--yaw", "0.2", "--duration", "2"], schemaOf("walk")).args).toEqual({ vx: 0.05, yaw_rate: 0.2, duration_s: 2 });
  });

  it("--deg 把頭部角度從度換成弧度", () => {
    const { args } = parseToolArgs("look", ["--yaw", "10", "--deg", "--time", "1"], schemaOf("look"));
    expect(args.head_yaw).toBeCloseTo(0.1745, 4);
    expect(args.duration_s).toBe(1);
  });

  it("位置參數與布林旗標", () => {
    expect(parseToolArgs("gesture", ["nod"], schemaOf("gesture")).args).toEqual({ name: "nod" });
    expect(parseToolArgs("go_to", ["brother_room"], schemaOf("go_to")).args).toEqual({ place: "brother_room" });
    expect(parseToolArgs("track", ["face", "--body", "--timeout", "30"], schemaOf("track")).args).toEqual({ target: "face", body: true, timeout_s: 30 });
    expect(parseToolArgs("track", ["none", "--body=false"], schemaOf("track")).args).toEqual({ target: "none", body: false });
  });

  it("錯誤的用法有看得懂的訊息", () => {
    expect(() => parseToolArgs("look", ["--speed", "1"], schemaOf("look"))).toThrow(/沒有參數 --speed/);
    expect(() => parseToolArgs("look", ["--yaw", "left"], schemaOf("look"))).toThrow(/要是數字/);
    expect(() => parseToolArgs("look", ["--yaw"], schemaOf("look"))).toThrow(/後面要接一個值/);
    expect(() => parseToolArgs("stop", ["now"], schemaOf("stop"))).toThrow(/多出來的參數/);
  });
});

describe("開發用 Dispatcher", () => {
  it("參數驗證：多餘、缺少、型別、範圍、列舉", () => {
    expect(validateArgs(schemaOf("walk"), { vx: 0.1 })).toContain("缺少參數：duration_s");
    expect(validateArgs(schemaOf("walk"), { duration_s: 1, speed: 3 })).toContain("不認得的參數");
    expect(validateArgs(schemaOf("walk"), { duration_s: 99 })).toContain("大於上限");
    expect(validateArgs(schemaOf("track"), { target: "dog" })).toContain("不在允許的值裡");
    expect(validateArgs(schemaOf("gesture"), { name: 5 })).toContain("必須是字串");
    expect(validateArgs(schemaOf("look"), { head_yaw: 0.2 })).toBeNull();
  });

  const fake = (execute: IntegrationAdapter["execute"], timeoutMs = 100): IntegrationAdapter => ({
    id: "duck",
    service: "duck",
    version: 1,
    mock: true,
    tools: () => [{ ...DUCK_TOOLS[0]!, timeoutMs }],
    health: async () => ({ health: "available", reason: "ok" }),
    execute,
  });

  it("超過工具時限 → unknown／timeout，並中止 Adapter", async () => {
    let aborted = false;
    const result = await devExecute(
      fake((_id, _args, ctx) => new Promise<ToolResult>(() => ctx.signal.addEventListener("abort", () => (aborted = true)))),
      "app.duck.status",
      {},
    );
    expect(result).toMatchObject({ status: "unknown", reason: "timeout" });
    expect(aborted).toBe(true);
  });

  it("Adapter 丟錯 → failed；結果格式不對 → failed／invalid_result；沒有這個工具 → refused", async () => {
    expect(await devExecute(fake(async () => Promise.reject(new Error("boom"))), "app.duck.status", {})).toMatchObject({ status: "failed", reason: "adapter_error" });
    expect(await devExecute(fake(async () => ({ ok: true, status: "unknown", message: "x" }) as ToolResult), "app.duck.status", {})).toMatchObject({ status: "failed", reason: "invalid_result" });
    expect(await devExecute(fake(async () => toolResult("confirmed", "ok")), "app.duck.fly", {})).toMatchObject({ status: "refused", reason: "not_registered" });
  });
});

describe("hub 行程與控制通道（對 mock 鴨子）", () => {
  let running: RunningHub | null = null;
  let duck: MockDuck | null = null;
  let dir: string | null = null;
  let client: ControlClient | null = null;

  afterEach(async () => {
    client?.close();
    duck?.disconnect();
    await running?.stop();
    if (dir) rmSync(dir, { recursive: true, force: true });
    running = duck = dir = client = null;
  });

  async function start(withDuck = true) {
    dir = mkdtempSync(join(tmpdir(), "duckctl-test-"));
    running = await runHub({ port: 0, socketPath: join(dir, "hub.sock") });
    if (withDuck) {
      duck = new MockDuck({ url: `ws://127.0.0.1:${running.port}/duck-link`, stateIntervalMs: 50, speed: 10 });
      await duck.connect();
      await until(() => running!.hub.snapshot().state !== null);
    }
    client = new ControlClient(running.socketPath);
    await client.connect();
    return client;
  }

  it("execute：從控制通道下工具，拿到 ToolResult 與回讀的 state", async () => {
    const c = await start();
    const result = await c.request<ToolResult>("execute", { tool: "app.duck.look", args: { head_yaw: 0.2, duration_s: 0.3 } });
    expect(result).toMatchObject({ ok: true, status: "confirmed", data: { mock: true, reached: true } });
    const bad = await c.request<ToolResult>("execute", { tool: "app.duck.look", args: { head_yaw: "left" } });
    expect(bad).toMatchObject({ status: "refused", reason: "invalid_arguments" });
  });

  it("link 與 state：標示對面是模擬", async () => {
    const c = await start();
    const link = await c.request<Record<string, any>>("link");
    expect(link).toMatchObject({ connected: true, duck: { mock: true }, health: { health: "available" } });
    expect(link.presence_source).toMatchObject({ dev: true });
    const state = await c.request<Record<string, any>>("state");
    expect(state.state.mock).toBe(true);
  });

  it("presence：經開發用手動來源送出，回傳來源標示與結果", async () => {
    const c = await start();
    const result = await c.request<Record<string, any>>("presence", { state: "speaking", level: 0.4 });
    expect(result.source).toMatchObject({ dev: true });
    expect(result.sent).toMatchObject({ state: "speaking", speechLevel: 0.4, result: { status: "confirmed" } });
    await expect(c.request("presence", { state: "dancing" })).rejects.toThrow(/presence 狀態只能是/);
  });

  it("events --follow：先給最近的事件，再推新的", async () => {
    const c = await start();
    const pushed: any[] = [];
    c.onPush = (frame) => pushed.push(frame);
    const recent = await c.request<any[]>("events", { follow: true });
    expect(recent.map((e) => e.name)).toContain("duck_connected");
    duck!.emitEvent("battery_low");
    await until(() => pushed.length === 1);
    expect(pushed[0]).toMatchObject({ stream: "event", event: { name: "battery_low", attention: "notify", mock: true } });
  });

  it("沒有鴨子時：工具回 failed（沒有送出），不假裝成功", async () => {
    const c = await start(false);
    expect(await c.request<ToolResult>("execute", { tool: "app.duck.gesture", args: { name: "nod" } })).toMatchObject({ ok: false, status: "failed", reason: "unavailable" });
    expect(await c.request<Record<string, any>>("link")).toMatchObject({ connected: false, duck: null });
  });

  it("同一個控制通道不能啟動第二個 hub", async () => {
    await start(false);
    await expect(runHub({ port: 0, socketPath: running!.socketPath })).rejects.toThrow(/已經有一個 hub/);
  });
});
