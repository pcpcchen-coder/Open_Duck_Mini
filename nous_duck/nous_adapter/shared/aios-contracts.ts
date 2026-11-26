import type { EffectClass, HealthReason, IntegrationHealth, IntegrationRoute, IntegrationToolId, ToolResult } from "./aios-integrations.ts";
import type { InputSchema } from "./aios-schema.ts";

// AIOS `prototype/ambient-shell/server/integrations/contracts.ts` 的最小重新宣告。
// 來源：pcpcchen-coder/AIOS，commit c85307861f7562803fb3776407493da49cdc8a83（2026-11-24，唯讀查閱；2026-11-26 確認 origin/main 仍是這個 commit）
// 沒有宣告的 AIOS 欄位：ToolDefinition.legacyName（只給 AIL-2 的 Facade）、AdapterCatalog.builtin、ToolCapability、IntegrationFunctionSpec。
// 搬進 AIOS 時這個檔案不搬。

/** AIOS shared/domain.ts 的腦區 ID（只用在 catalog.domain）。 */
export type Domain = "language" | "math" | "art" | "auditory" | "visual" | "planning";

export interface ToolCatalogInfo {
  summary: string;
  examples: readonly [string, ...string[]];
  needs?: string;
  domain: Domain | null;
  hidden?: true;
}

export interface ToolDefinition {
  id: IntegrationToolId;
  description: string;
  descriptionEn?: string;
  inputSchema: InputSchema;
  effect: EffectClass;
  enabled: boolean;
  /** 單次執行的時限（100 ms 到 60 s）。 */
  timeoutMs: number;
  supportedRoutes: readonly IntegrationRoute[];
  catalog: ToolCatalogInfo;
}

export type CatalogTool = Pick<ToolDefinition, "id" | "effect" | "enabled" | "supportedRoutes" | "catalog">;

export interface AdapterCatalog {
  id: string;
  service: string;
  label: string;
  mock: boolean | "config";
  tools: readonly CatalogTool[];
}

export interface ExecutionContext {
  actor: "user" | "agent";
  route: IntegrationRoute;
  sessionId: string;
  requestId: string;
  signal: AbortSignal;
  page?: string;
}

export interface HealthReport {
  health: IntegrationHealth;
  reason: HealthReason;
}

export interface IntegrationAdapter {
  readonly id: string;
  readonly service: string;
  readonly version: number;
  readonly mock: boolean;
  tools(): readonly ToolDefinition[];
  health(signal: AbortSignal): Promise<HealthReport>;
  execute(toolId: IntegrationToolId, args: Record<string, unknown>, ctx: ExecutionContext): Promise<ToolResult>;
}
