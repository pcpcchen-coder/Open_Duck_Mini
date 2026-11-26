import { chmodSync, existsSync, unlinkSync } from "node:fs";
import { connect, createServer, type Server, type Socket } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

// duckctl ↔ hub 行程的本機控制通道：UNIX domain socket（檔案權限 0600），一行一則 JSON。
// 為什麼不用 TCP：8791 會經 SSH 通道轉給 Pi，Pi 上的任何程式都連得到那個埠；
// 控制通道（可以下任何 app.duck.* 工具）只留在 Mac 本機的檔案系統權限之內。
// 這是開發用的設施，搬回 AIOS 時不需要（AIOS 的工具呼叫走它自己的 Dispatcher）。

export function defaultSocketPath(port: number): string {
  return process.env.DUCK_HUB_SOCKET || join(tmpdir(), `nous-duck-hub-${port}.sock`);
}

export interface ControlRequest {
  id: number;
  op: string;
  [key: string]: unknown;
}

export type ControlHandler = (request: ControlRequest, push: (frame: Record<string, unknown>) => void, onClose: (fn: () => void) => void) => Promise<unknown>;

function probe(path: string): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = connect(path);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
  });
}

export async function startControlServer(path: string, handler: ControlHandler): Promise<{ close(): Promise<void> }> {
  if (existsSync(path)) {
    if (await probe(path)) throw new Error(`已經有一個 hub 在執行（控制通道 ${path} 有人在聽）。`);
    unlinkSync(path); // 上次沒有正常結束留下的檔案
  }
  const sockets = new Set<Socket>();
  const server: Server = createServer((socket: Socket) => {
    sockets.add(socket);
    let buffer = "";
    const closers: (() => void)[] = [];
    const push = (frame: Record<string, unknown>) => {
      if (!socket.destroyed) socket.write(`${JSON.stringify(frame)}\n`);
    };
    socket.on("data", (chunk) => {
      buffer += chunk.toString();
      if (buffer.length > 256 * 1024) return socket.destroy();
      let index: number;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        if (!line.trim()) continue;
        let request: ControlRequest;
        try {
          request = JSON.parse(line) as ControlRequest;
        } catch {
          push({ ok: false, error: "不是合法的 JSON" });
          continue;
        }
        handler(request, push, (fn) => closers.push(fn)).then(
          (result) => push({ id: request.id, ok: true, result }),
          (error: unknown) => push({ id: request.id, ok: false, error: error instanceof Error ? error.message : String(error) }),
        );
      }
    });
    socket.on("close", () => {
      sockets.delete(socket);
      closers.splice(0).forEach((fn) => fn());
    });
    socket.on("error", () => {});
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(path, () => {
      server.off("error", reject);
      resolve();
    });
  });
  chmodSync(path, 0o600);
  return {
    close: () =>
      new Promise<void>((resolve) => {
        for (const socket of sockets) socket.destroy();
        server.close(() => resolve());
      }),
  };
}

export class ControlClient {
  private socket: Socket | null = null;
  private buffer = "";
  private nextId = 1;
  private readonly waiting = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  onPush: (frame: Record<string, unknown>) => void = () => {};
  onClose: () => void = () => {};

  constructor(private readonly path: string) {}

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = connect(this.path);
      this.socket = socket;
      socket.once("error", reject);
      socket.once("connect", () => {
        socket.off("error", reject);
        socket.on("error", () => {});
        resolve();
      });
      socket.on("data", (chunk) => {
        this.buffer += chunk.toString();
        let index: number;
        while ((index = this.buffer.indexOf("\n")) >= 0) {
          const line = this.buffer.slice(0, index);
          this.buffer = this.buffer.slice(index + 1);
          if (!line.trim()) continue;
          const frame = JSON.parse(line) as { id?: number; ok?: boolean; result?: unknown; error?: string };
          const waiter = frame.id !== undefined ? this.waiting.get(frame.id) : undefined;
          if (waiter && frame.ok !== undefined) {
            this.waiting.delete(frame.id!);
            if (frame.ok) waiter.resolve(frame.result);
            else waiter.reject(new Error(frame.error ?? "hub 回報錯誤"));
          } else {
            this.onPush(frame as Record<string, unknown>);
          }
        }
      });
      socket.on("close", () => {
        for (const w of this.waiting.values()) w.reject(new Error("和 hub 的控制通道中斷"));
        this.waiting.clear();
        this.onClose();
      });
    });
  }

  request<T = unknown>(op: string, body: Record<string, unknown> = {}): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.waiting.set(id, { resolve: resolve as (v: unknown) => void, reject });
      this.socket!.write(`${JSON.stringify({ id, op, ...body })}\n`);
    });
  }

  close(): void {
    this.socket?.destroy();
  }
}
