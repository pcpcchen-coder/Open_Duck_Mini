// AIOS `prototype/ambient-shell/server/integrations/schema.ts` 的型別子集（不含只給 legacy Facade 用的 scalar，也不含驗證函式）。
// 來源：pcpcchen-coder/AIOS，commit c85307861f7562803fb3776407493da49cdc8a83（2026-11-24，唯讀查閱；2026-11-26 確認 origin/main 仍是這個 commit）
// 搬進 AIOS 時這個檔案不搬。

export type PropertySchema =
  | { type: "string"; description?: string; enum?: readonly string[]; minLength?: number; maxLength?: number }
  | { type: "number" | "integer"; description?: string; minimum?: number; maximum?: number }
  | { type: "boolean"; description?: string };

export interface InputSchema {
  type: "object";
  properties: Readonly<Record<string, PropertySchema>>;
  required?: readonly string[];
  additionalProperties: false;
}
