import { unlinkSync } from "node:fs";
import { DuckAdapter } from "../adapters/duck.ts";
import { compactState, DUCK_TIMING } from "../adapters/duck-exec.ts";
import { DEFAULT_PORT, DUCK_LINK_PATH, DuckLinkHub } from "../hub/duck-link-hub.ts";
import { PRESENCE_STATES, type PresenceState } from "../shared/duck-link.ts";
import { DuckTerminal } from "../terminal/duck-terminal.ts";
import { ManualPresenceSource } from "../terminal/manual-presence-source.ts";
import { defaultSocketPath, startControlServer, type ControlRequest } from "./control.ts";
import { devExecute } from "./dev-dispatch.ts";
import { interpretTextCommand, TEXT_COMMAND_EXAMPLES } from "./text-command.ts";

// 開發用的 hub 行程：duck-link hub ＋ DuckAdapter ＋ DuckTerminal（presence 接「開發用手動來源」）＋ duckctl 的控制通道。
// 之後在 AIOS 裡，這些元件由 AIOS 核心建立（docs/aios-integration-plan.md §4）；這個檔案不會搬過去。

export interface RunningHub {
  hub: DuckLinkHub;
  adapter: DuckAdapter;
  terminal: DuckTerminal;
  port: number;
  socketPath: string;
  stop(): Promise<void>;
}

export async function runHub(options: { port?: number; socketPath?: string; log?: (line: string) => void } = {}): Promise<RunningHub> {
  const log = options.log ?? (() => {});
  const hub = new DuckLinkHub({ port: options.port ?? DEFAULT_PORT, log });
  const port = await hub.start();
  const socketPath = options.socketPath ?? defaultSocketPath(port);
  // 開發入口：17 個工具全開（AIOS 裡第一階段只開 DUCK_STAGE1_TOOLS 那六個）。
  const adapter = new DuckAdapter(hub, { enableAllTools: true });
  const manual = new ManualPresenceSource();
  const terminal = new DuckTerminal(hub, { sendPresence: (state, level) => adapter.presence(state, level), log });
  terminal.attachPresenceSource(manual);

  const handler = async (request: ControlRequest, push: (frame: Record<string, unknown>) => void, onClose: (fn: () => void) => void): Promise<unknown> => {
    switch (request.op) {
      case "tools":
        return adapter.tools().map((t) => ({ id: t.id, effect: t.effect, description: t.description, inputSchema: t.inputSchema, timeoutMs: t.timeoutMs }));
      case "execute":
        return devExecute(adapter, String(request.tool), (request.args as Record<string, unknown>) ?? {});
      case "say_command": {
        // 開發用：固定規則把一句文字對應到一個工具（不是 Nous、不是語音辨識、不是語言模型）。
        const hello = hub.snapshot().hello;
        const text = String(request.text ?? "").slice(0, 200);
        const match = interpretTextCommand(text, { gestures: hello?.gestures ?? [], expressions: hello?.expressions ?? [] });
        if (!match) return { source: "dev_text_rules", matched: null, examples: TEXT_COMMAND_EXAMPLES, gestures: hello?.gestures ?? [], expressions: hello?.expressions ?? [] };
        return { source: "dev_text_rules", matched: match, result: request.dry_run ? null : await devExecute(adapter, match.tool, match.args) };
      }
      case "resume":
        return adapter.resume();
      case "presence": {
        const state = String(request.state) as PresenceState;
        if (!PRESENCE_STATES.includes(state)) throw new Error(`presence 狀態只能是：${PRESENCE_STATES.join("、")}`);
        const level = typeof request.level === "number" ? request.level : undefined;
        if (level !== undefined && (level < 0 || level > 1)) throw new Error("level 要在 0 到 1 之間");
        manual.request(state, level);
        const sent = await terminal.presence.settled();
        return { source: terminal.presence.source, requested: { state, ...(level !== undefined ? { level } : {}) }, sent };
      }
      case "link": {
        const snapshot = hub.snapshot();
        return {
          listening: `ws://127.0.0.1:${port}${DUCK_LINK_PATH}`,
          connected: snapshot.connected,
          duck: snapshot.hello ? { software: snapshot.hello.software, duck_id: snapshot.hello.duck_id ?? null, mock: snapshot.hello.mock === true } : null,
          rtt_ms: snapshot.rttMs,
          connected_for_ms: snapshot.connectedAt ? Date.now() - snapshot.connectedAt : null,
          state_age_ms: snapshot.stateAt ? Date.now() - snapshot.stateAt : null,
          health: await adapter.health(),
          counters: snapshot.counters,
          presence_source: terminal.presence.source,
        };
      }
      case "state": {
        const snapshot = hub.snapshot();
        return { connected: snapshot.connected, hello: snapshot.hello, state: snapshot.state, summary: compactState(snapshot, DUCK_TIMING) };
      }
      case "events": {
        if (request.follow) onClose(terminal.onEvent((event) => push({ stream: "event", event })));
        return terminal.events();
      }
      default:
        throw new Error(`不認得的操作：${String(request.op).slice(0, 32)}`);
    }
  };
  const control = await startControlServer(socketPath, handler).catch(async (error: unknown) => {
    terminal.stop();
    await hub.stop();
    throw error;
  });

  return {
    hub,
    adapter,
    terminal,
    port,
    socketPath,
    async stop() {
      terminal.stop();
      await control.close();
      try {
        unlinkSync(socketPath);
      } catch {
        // 已經不在
      }
      await hub.stop();
    },
  };
}
