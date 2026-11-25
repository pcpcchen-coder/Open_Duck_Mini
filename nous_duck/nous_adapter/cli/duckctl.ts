import { DUCK_TOOLS } from "../adapters/duck.ts";
import { DEFAULT_PORT, DUCK_LINK_PATH } from "../hub/duck-link-hub.ts";
import { MockDuck } from "../mock/mock-duck.ts";
import type { ToolResult } from "../shared/aios-contracts.ts";
import { PRESENCE_STATES } from "../shared/duck-link.ts";
import { parseToolArgs, POSITIONAL } from "./args.ts";
import { ControlClient, defaultSocketPath } from "./control.ts";
import { runHub } from "./hub-main.ts";

// duckctl：不經過 AIOS，直接從終端機對鴨子下 app.duck.* 工具（開發與親手測試用）。
// 用法說明見 ../README.md 的「親手試」與 `duckctl help`。

const HELP = `duckctl — 從終端機對鴨子下指令（開發用，不經過 Nous／AIOS）

先啟動（各開一個終端機分頁，或用 scripts/duck-link-dev.sh 在背景跑）：
  duckctl hub                     啟動 duck-link hub（只聽 127.0.0.1:${DEFAULT_PORT}，等鴨子連進來）
  duckctl mock-duck               啟動「模擬的鴨子」連到 hub（沒有真的鴨子時用；輸出一律標示模擬）

看狀態：
  duckctl link                    hub 與鴨子的連線、往返時間、對面是不是模擬
  duckctl status                  app.duck.status：模式、頭部角度、能力清單
  duckctl state                   鴨子最新一則 state 的原文
  duckctl events [--follow]       鴨子回報的事件（跌倒、任務進度、斷線…）
  duckctl tools                   列出所有 app.duck.* 工具與參數

動作（對應 app.duck.<動作>）：
  duckctl look --yaw 0.2                  頭轉到 0.2 rad（正＝往左）；也可以 --pitch --roll --neck --time 1.5
  duckctl look --yaw 10 --deg             用「度」輸入
  duckctl gesture nod                     做預錄動作（清單看 duckctl status 的 gestures）
  duckctl express happy                   換眼睛表情
  duckctl track face | none               開關視線跟隨
  duckctl antennas --left 0.5 --right -0.5
  duckctl walk --vx 0.05 --time 2         走路（要鴨子回報 walk 能力可用；先確認周圍安全）
  duckctl stop                            立刻停下
  duckctl go_to <地點> ／ find_person [家人ID] ／ return_home ／ follow_me ／ wait_here
  duckctl where ／ places ／ mission_status ／ cancel_mission

開發用的文字命令（固定關鍵字規則；不是 Nous、不是語音辨識、不是語言模型）：
  duckctl say-command "往左看"            把一句文字對應到一個工具並執行；認不得就不送
  duckctl say-command "點頭" --dry-run    只看會對應到什麼，不送出

不是模型工具、只給在場的人用：
  duckctl presence <狀態> [--level 0.4]   手動送互動狀態（${PRESENCE_STATES.join("／")}）
                                          這是「開發用手動來源」，不是 Nous 語音工作階段的真實事件
  duckctl resume                          解除暫停（之後的 walk 才會被接受）

共用選項：
  --json        只印 JSON（給腳本用）
  --port <n>    hub 的埠號（預設 ${DEFAULT_PORT}；也決定控制通道的檔名）

結果怎麼讀（和 Nous 用的 ToolResult 相同）：
  confirmed    鴨子接受了，而且之後讀回的狀態符合。動作類只代表「已開始」，不是做完
  unconfirmed  鴨子接受了，但沒有讀到符合的狀態
  unknown      已送出，沒有回覆或連線中斷——不能當成沒有執行，請看一下鴨子
  refused      沒有執行：鴨子拒絕（原因在 duck_reason），或參數不對、鴨子沒有這項能力
  failed       沒有送出（例如鴨子沒有連線）

結束代碼：0 confirmed；2 unconfirmed／unknown；1 refused／failed；3 連不到 hub
`;

const MARK: Record<ToolResult["status"], string> = { confirmed: "✔", unconfirmed: "？", unknown: "？", needs_confirmation: "…", refused: "✘", failed: "✘" };

function exitCode(result: ToolResult): number {
  if (result.status === "confirmed") return 0;
  return result.status === "unconfirmed" || result.status === "unknown" ? 2 : 1;
}

function printResult(label: string, result: ToolResult, json: boolean): void {
  if (json) return void console.log(JSON.stringify(result, null, 2));
  const data = (result.data ?? {}) as Record<string, unknown>;
  console.log(`${label} → ${result.status} ${MARK[result.status]}${result.reason ? `（${result.reason}）` : ""}`);
  console.log(`  ${result.message}`);
  if (data.mock) console.log("  ⚠ 對面是模擬的鴨子（mock），不是實機。");
  const { state, ...rest } = data;
  delete rest.mock;
  if (Object.keys(rest).length) console.log(`  結果：${JSON.stringify(rest)}`);
  if (state) console.log(`  回讀的狀態：${JSON.stringify(state)}`);
}

function takeOption(argv: string[], name: string): string | undefined {
  const index = argv.findIndex((a) => a === `--${name}` || a.startsWith(`--${name}=`));
  if (index < 0) return undefined;
  const token = argv[index]!;
  if (token.includes("=")) {
    argv.splice(index, 1);
    return token.split("=", 2)[1];
  }
  const value = argv[index + 1];
  argv.splice(index, 2);
  return value;
}

function takeFlag(argv: string[], name: string): boolean {
  const index = argv.indexOf(`--${name}`);
  if (index < 0) return false;
  argv.splice(index, 1);
  return true;
}

async function withHub<T>(port: number, fn: (client: ControlClient) => Promise<T>): Promise<T> {
  const client = new ControlClient(defaultSocketPath(port));
  try {
    await client.connect();
  } catch {
    console.error(`連不到 hub（控制通道 ${defaultSocketPath(port)}）。請先在另一個終端機執行：duckctl hub`);
    process.exit(3);
  }
  try {
    return await fn(client);
  } finally {
    client.close();
  }
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const port = Number(takeOption(argv, "port") ?? process.env.DUCK_HUB_PORT ?? DEFAULT_PORT);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("--port 要是 1～65535 的整數");
  const command = (argv.shift() ?? "help").replaceAll("-", "_");

  if (command === "help" || command === "__help" || command === "_h") {
    console.log(HELP);
    return 0;
  }

  if (command === "hub") {
    const stamp = () => new Date().toLocaleTimeString("zh-TW", { hour12: false });
    const running = await runHub({ port, log: (line) => console.log(`[${stamp()}] ${line}`) });
    console.log(`duck-link hub 已啟動：ws://127.0.0.1:${running.port}${DUCK_LINK_PATH}（只聽本機 loopback）`);
    console.log(`控制通道：${running.socketPath}`);
    console.log("presence 來源：開發用手動來源（duckctl presence …），不是 Nous 的事件。");
    console.log("等鴨子連進來…（Ctrl-C 結束）");
    running.terminal.onEvent((e) => console.log(`[${stamp()}] 事件 ${e.origin === "hub" ? "（hub）" : ""}${e.name}${e.reason ? ` reason=${e.reason}` : ""}${e.mission_id ? ` mission=${e.mission_id}` : ""}${e.mock ? "（模擬）" : ""}`));
    await new Promise<void>((resolve) => {
      process.once("SIGINT", resolve);
      process.once("SIGTERM", resolve);
    });
    await running.stop();
    console.log("hub 已結束。");
    return 0;
  }

  if (command === "mock_duck") {
    const url = `ws://127.0.0.1:${port}${DUCK_LINK_PATH}`;
    console.log("⚠ 這是模擬的鴨子（mock）：不連任何硬體，回報的狀態、地點、夾限範圍都是測試用的固定值。");
    const duck = new MockDuck({ url, startPaused: takeFlag(argv, "start-paused"), log: (line) => console.log(line) });
    let stopping = false;
    const stop = new Promise<void>((resolve) => {
      const done = () => {
        stopping = true;
        resolve();
      };
      process.once("SIGINT", done);
      process.once("SIGTERM", done);
    });
    void (async () => {
      let wasConnected = false;
      while (!stopping) {
        if (!duck.connected) {
          if (wasConnected) console.log("和 hub 的連線中斷，重連中…");
          wasConnected = false;
          try {
            await duck.connect();
            wasConnected = true;
            console.log(`模擬鴨子已連上 ${url}`);
          } catch {
            // hub 還沒起來：稍後再試
          }
        }
        await new Promise((r) => setTimeout(r, 1_000));
      }
    })();
    await stop;
    duck.disconnect();
    return 0;
  }

  const json = takeFlag(argv, "json");

  if (command === "tools") {
    if (json) return console.log(JSON.stringify(DUCK_TOOLS.map((t) => ({ id: t.id, effect: t.effect, description: t.description, inputSchema: t.inputSchema })), null, 2)), 0;
    for (const tool of DUCK_TOOLS) {
      const action = tool.id.split(".")[2]!;
      const params = Object.entries(tool.inputSchema.properties).map(([k, p]) => `--${k}${(tool.inputSchema.required ?? []).includes(k) ? "*" : ""}${p.type === "boolean" ? "" : `<${"enum" in p && p.enum ? p.enum.join("|") : p.type}>`}`);
      console.log(`${tool.id}  [${tool.effect}]${POSITIONAL[action] ? `  位置參數＝${POSITIONAL[action]}` : ""}`);
      console.log(`  ${tool.description}`);
      if (params.length) console.log(`  參數：${params.join("  ")}  （* 必填）`);
    }
    return 0;
  }

  if (command === "link" || command === "state") {
    const result = await withHub(port, (c) => c.request<Record<string, unknown>>(command));
    if (json || command === "state") return console.log(JSON.stringify(result, null, 2)), 0;
    const duck = result.duck as { software: string; duck_id: string | null; mock: boolean } | null;
    console.log(`hub：${String(result.listening)}`);
    console.log(`鴨子：${result.connected ? "已連線" : "沒有連線"}${duck ? `（${duck.software}${duck.duck_id ? `，${duck.duck_id}` : ""}${duck.mock ? "，⚠ 模擬" : ""}${result.connected ? "" : "，上一次連線的資料"}）` : ""}`);
    if (result.connected) console.log(`往返時間：${result.rtt_ms === null ? "還沒量到" : `${String(result.rtt_ms)} ms`}；已連線 ${Math.round(Number(result.connected_for_ms) / 1000)} 秒；${result.state_age_ms === null ? "還沒收到 state" : `最新 state 是 ${String(result.state_age_ms)} ms 前`}`);
    console.log(`health：${JSON.stringify(result.health)}`);
    console.log(`計數：${JSON.stringify(result.counters)}`);
    console.log(`presence 來源：${(result.presence_source as { label: string } | null)?.label ?? "無"}`);
    return 0;
  }

  if (command === "events") {
    const follow = takeFlag(argv, "follow");
    const show = (e: Record<string, unknown>) => {
      if (json) return console.log(JSON.stringify(e));
      const extra = ["reason", "mission_id", "request_id"].filter((k) => e[k] !== undefined).map((k) => `${k}=${String(e[k])}`);
      console.log(`${new Date(Number(e.at)).toLocaleTimeString("zh-TW", { hour12: false })}  ${String(e.category).padEnd(7)} ${String(e.name)}${e.origin === "hub" ? "（hub 觀察到的）" : ""}${e.attention === "notify" ? "  ❗" : ""}${extra.length ? `  ${extra.join(" ")}` : ""}${e.data ? `  ${JSON.stringify(e.data)}` : ""}${e.mock ? "  （模擬）" : ""}`);
    };
    return withHub(port, async (c) => {
      c.onPush = (frame) => frame.stream === "event" && show(frame.event as Record<string, unknown>);
      const recent = await c.request<Record<string, unknown>[]>("events", { follow });
      if (!recent.length && !follow) console.log("還沒有事件。");
      recent.forEach(show);
      if (follow) await new Promise<void>((resolve) => ((c.onClose = resolve), process.once("SIGINT", resolve)));
      return 0;
    });
  }

  if (command === "presence") {
    const level = takeOption(argv, "level");
    const state = argv.shift();
    if (!state || !(PRESENCE_STATES as readonly string[]).includes(state)) throw new Error(`用法：duckctl presence <${PRESENCE_STATES.join("|")}> [--level 0~1]`);
    const result = await withHub(port, (c) => c.request<{ source: { label: string }; sent: { state: string; speechLevel?: number; result: ToolResult } | null }>("presence", { state, ...(level !== undefined ? { level: Number(level) } : {}) }));
    if (json) return console.log(JSON.stringify(result, null, 2)), result.sent ? exitCode(result.sent.result) : 1;
    console.log(`來源：${result.source.label}`);
    if (!result.sent) return console.log("沒有送出任何 presence。"), 1;
    printResult(`presence ${result.sent.state}${result.sent.speechLevel !== undefined ? ` level=${result.sent.speechLevel}` : ""}`, result.sent.result, false);
    if (result.sent.state !== state) console.log(`  （要求的是 ${state}；依工作階段規則目前送出的是 ${result.sent.state}，例如 wake 之後會自動接著下一個狀態）`);
    return exitCode(result.sent.result);
  }

  if (command === "say_command") {
    const dryRun = takeFlag(argv, "dry-run");
    const text = argv.join(" ").trim();
    if (!text) throw new Error('用法：duckctl say-command "往左看" [--dry-run]');
    const reply = await withHub(port, (c) => c.request<{ matched: { tool: string; args: Record<string, unknown>; rule: string } | null; result?: ToolResult | null; examples?: string[]; gestures?: string[] }>("say_command", { text, dry_run: dryRun }));
    if (json) return console.log(JSON.stringify(reply, null, 2)), reply.result ? exitCode(reply.result) : reply.matched ? 0 : 1;
    console.log("開發用的文字命令對應（固定規則）：不是 Nous、不是語音辨識、不是語言模型。");
    if (!reply.matched) {
      console.log(`認不得「${text}」，沒有送出任何指令。`);
      console.log(`認得的說法例如：${(reply.examples ?? []).join("、")}`);
      console.log(`鴨子目前回報的動作清單：${(reply.gestures ?? []).join("、") || "（空的；點頭、搖頭這類命令現在對應不到）"}`);
      return 1;
    }
    console.log(`「${text}」 → ${reply.matched.tool} ${JSON.stringify(reply.matched.args)}   （規則：${reply.matched.rule}）`);
    if (!reply.result) return console.log("（--dry-run：只顯示對應，沒有送出）"), 0;
    printResult(reply.matched.tool, reply.result, false);
    return exitCode(reply.result);
  }

  if (command === "resume") {
    const result = await withHub(port, (c) => c.request<ToolResult>("resume"));
    printResult("resume（不是模型工具）", result, json);
    return exitCode(result);
  }

  const tool = DUCK_TOOLS.find((t) => t.id === `app.duck.${command}`);
  if (!tool) throw new Error(`不認得的指令：${command}。執行 duckctl help 看用法。`);
  const parsed = parseToolArgs(command, argv, tool.inputSchema);
  const result = await withHub(port, (c) => c.request<ToolResult>("execute", { tool: tool.id, args: parsed.args }));
  printResult(`${tool.id} ${JSON.stringify(parsed.args)}`, result, json || parsed.flags.json);
  return exitCode(result);
}

main().then(
  (code) => process.exit(code),
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  },
);
