// AIOS `prototype/ambient-shell/shared/integrations.ts` 的最小重新宣告（只有 DuckAdapter 用得到的部分）。
// 來源：pcpcchen-coder/AIOS，commit c85307861f7562803fb3776407493da49cdc8a83（2026-11-24，唯讀查閱；2026-11-26 確認 origin/main 仍是這個 commit）
// 形狀與 AIOS 相同；搬進 AIOS 時這個檔案不搬，import 改指向 AIOS 的原檔（scripts/make-aios-port.mjs 會自動改寫）。
// 不要在這裡加 AIOS 沒有的欄位。和 AIOS 原檔的逐項比對見 docs/aios-port.md §3。

export const EFFECT_CLASSES = ["read", "reversible_write", "external_commit"] as const;
export type EffectClass = (typeof EFFECT_CLASSES)[number];

export const INTEGRATION_ROUTES = ["api_key", "live", "text", "background", "page"] as const;
export type IntegrationRoute = (typeof INTEGRATION_ROUTES)[number];

/**
 * 只有 confirmed 可以說「完成」；unconfirmed＝已送出但沒有回讀確認；unknown＝結果不明（逾時、中止、連線中斷），
 * 不能推定沒有執行；refused＝沒有執行（未註冊、停用、參數不對、對方拒絕）；failed＝確定失敗。
 */
export const TOOL_RESULT_STATUSES = ["confirmed", "unconfirmed", "unknown", "needs_confirmation", "refused", "failed"] as const;
export type ToolResultStatus = (typeof TOOL_RESULT_STATUSES)[number];

/** AIOS 的固定原因代碼。鴨子自己的原因代碼（duck-link reason）放在 data.duck_reason，不擴充這份清單。 */
export const TOOL_RESULT_REASONS = [
  "not_registered",
  "disabled",
  "route_not_supported",
  "invalid_arguments",
  "rate_limited",
  "confirmation_unavailable",
  "timeout",
  "aborted",
  "adapter_error",
  "invalid_result",
  "unavailable",
] as const;
export type ToolResultReason = (typeof TOOL_RESULT_REASONS)[number];

export interface ToolResult {
  ok: boolean;
  status: ToolResultStatus;
  message: string;
  reason?: ToolResultReason;
  data?: unknown;
}

/** ok 一律由 status 推導（只有 confirmed 為 true）。 */
export function toolResult(status: ToolResultStatus, message: string, extra: { reason?: ToolResultReason; data?: unknown } = {}): ToolResult {
  return {
    ok: status === "confirmed",
    status,
    message,
    ...(extra.reason ? { reason: extra.reason } : {}),
    ...(extra.data !== undefined ? { data: extra.data } : {}),
  };
}

export function isToolResult(value: unknown): value is ToolResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  if (!(TOOL_RESULT_STATUSES as readonly unknown[]).includes(v.status)) return false;
  if (typeof v.message !== "string" || typeof v.ok !== "boolean") return false;
  if (v.ok !== (v.status === "confirmed")) return false;
  if (v.reason !== undefined && !(TOOL_RESULT_REASONS as readonly unknown[]).includes(v.reason)) return false;
  return true;
}

const SEGMENT = "[a-z][a-z0-9]*(?:_[a-z0-9]+)*";
export const INTEGRATION_TOOL_ID = new RegExp(`^app\\.(${SEGMENT})\\.(${SEGMENT})$`);
export const WIRE_NAME_MAX = 64;
export type IntegrationToolId = `app.${string}.${string}`;

/** app.duck.go_to → app__duck__go_to（送給模型的函式名稱）。 */
export function toWireName(id: IntegrationToolId): string {
  const match = INTEGRATION_TOOL_ID.exec(id);
  if (!match) throw new Error(`不是整合工具 ID：${id}`);
  return `app__${match[1]}__${match[2]}`;
}

export const INTEGRATION_HEALTH = ["available", "unavailable", "unknown"] as const;
export type IntegrationHealth = (typeof INTEGRATION_HEALTH)[number];

export const HEALTH_REASONS = [
  "ok",
  "not_configured",
  "connection_refused",
  "connection_closed",
  "timeout",
  "bad_reply",
  "expired",
  "taken_over",
  "not_ready",
  "error",
  "unreachable",
  "not_paired",
] as const;
export type HealthReason = (typeof HEALTH_REASONS)[number];
