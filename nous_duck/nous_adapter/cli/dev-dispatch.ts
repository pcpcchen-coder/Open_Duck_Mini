import { isToolResult, toolResult, type InputSchema, type IntegrationAdapter, type IntegrationToolId, type ToolResult } from "../shared/aios-contracts.ts";

// 開發用的最小 Dispatcher：duckctl 不經過 AIOS，但仍照 AIOS Dispatcher 的順序做三件事，
// 讓這裡試到的行為接近之後在 AIOS 裡的行為：驗證參數（inputSchema）→ 執行並套工具的時限 → 檢查結果格式。
// 沒有做的（AIOS 才有）：NOUS_AIL_SERVICES 啟用檢查、路徑檢查、每分鐘 30 次的頻率限制、稽核紀錄、結果大小上限。
// 參數驗證規則對照 AIOS server/integrations/schema.ts 的 validateArgs（commit c853078）。

export function validateArgs(schema: InputSchema, args: Record<string, unknown>): string | null {
  for (const key of Object.keys(args)) if (!Object.hasOwn(schema.properties, key)) return `不認得的參數：${key.slice(0, 32)}`;
  for (const key of schema.required ?? []) if (args[key] === undefined) return `缺少參數：${key}`;
  for (const [key, prop] of Object.entries(schema.properties)) {
    const v = args[key];
    if (v === undefined) continue;
    if (prop.type === "string") {
      if (typeof v !== "string") return `${key} 必須是字串`;
      if (prop.enum && !prop.enum.includes(v)) return `${key} 不在允許的值裡（${prop.enum.join("、")}）`;
      if (prop.minLength !== undefined && v.length < prop.minLength) return `${key} 太短`;
      if (v.length > (prop.maxLength ?? 500)) return `${key} 太長`;
    } else if (prop.type === "number" || prop.type === "integer") {
      if (typeof v !== "number" || !Number.isFinite(v) || (prop.type === "integer" && !Number.isInteger(v))) return `${key} 必須是${prop.type === "integer" ? "整數" : "數字"}`;
      if (prop.minimum !== undefined && v < prop.minimum) return `${key} 小於下限 ${prop.minimum}`;
      if (prop.maximum !== undefined && v > prop.maximum) return `${key} 大於上限 ${prop.maximum}`;
    } else if (typeof v !== "boolean") {
      return `${key} 必須是 true 或 false`;
    }
  }
  return null;
}

let counter = 0;

export async function devExecute(adapter: IntegrationAdapter, toolId: string, args: Record<string, unknown>): Promise<ToolResult> {
  const tool = adapter.tools().find((t) => t.id === toolId);
  if (!tool) return toolResult("refused", "沒有這個工具。", { reason: "not_registered" });
  const problem = validateArgs(tool.inputSchema, args);
  if (problem) return toolResult("refused", `參數不正確：${problem}。沒有送出。`, { reason: "invalid_arguments" });
  const controller = new AbortController();
  const requestId = `duckctl_${Date.now().toString(36)}_${(++counter).toString(36).padStart(4, "0")}`;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<ToolResult>((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve(toolResult("unknown", "工具在時限內沒有完成，結果不明。", { reason: "timeout" }));
    }, tool.timeoutMs);
  });
  try {
    // route 填 "live" 只是為了滿足契約的型別；duckctl 是開發入口，不是 AIOS 的任何一條語音路徑。
    const result = await Promise.race([adapter.execute(tool.id as IntegrationToolId, args, { actor: "user", route: "live", sessionId: "duckctl-dev", requestId, signal: controller.signal }), timeout]);
    return isToolResult(result) ? result : toolResult("failed", "Adapter 回傳的結果格式不正確。", { reason: "invalid_result" });
  } catch (error) {
    return toolResult("failed", `Adapter 發生錯誤：${error instanceof Error ? error.message.slice(0, 200) : "unknown"}`, { reason: "adapter_error" });
  } finally {
    clearTimeout(timer);
  }
}
