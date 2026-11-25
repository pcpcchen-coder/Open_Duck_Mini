import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Ajv2020, type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import type { DuckLinkMessage } from "./duck-link.ts";

// duck-link v0 的 schema 驗證（TypeScript 端）。驗證器：Ajv 8.20.0（draft 2020-12），版本鎖在 package.json。
// schema 檔只有一份，在 ../../protocol/schemas/；這裡在啟動時讀進來，不複製、不改寫。

export const SCHEMA_PATH = fileURLToPath(new URL("../../protocol/schemas/duck-link.v0.schema.json", import.meta.url));

export type Validation = { ok: true; message: DuckLinkMessage } | { ok: false; errors: string[] };

export interface DuckLinkValidator {
  /** 驗證一則已經解析成物件的訊息。 */
  validate(value: unknown): Validation;
  /** 驗證一個 WebSocket 文字框（先 JSON.parse）。 */
  parse(text: string): Validation;
}

const MESSAGE_TYPES = ["hello", "heartbeat", "command", "ack", "state", "event"];

function describe(errors: ErrorObject[] | null | undefined): string[] {
  // 錯誤說明只有欄位路徑與規則，不回顯值（值可能是外來內容）。
  const lines = (errors ?? []).map((e) => `${e.instancePath || "/"} ${e.message ?? e.keyword}`);
  return [...new Set(lines)].slice(0, 8);
}

export function createValidator(schemaPath: string = SCHEMA_PATH): DuckLinkValidator {
  const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as { $id: string };
  // strict:false：schema 的子定義刻意不重複寫 type:"object"（由最外層宣告），Ajv 的 strictTypes 會抱怨。
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const whole = ajv.compile(schema);
  const byType = new Map<string, ValidateFunction>();
  for (const type of MESSAGE_TYPES) byType.set(type, ajv.compile({ $ref: `${schema.$id}#/$defs/${type}` }));

  function validate(value: unknown): Validation {
    if (whole(value)) return { ok: true, message: value as unknown as DuckLinkMessage };
    // 最外層是 oneOf，錯誤訊息很難讀；知道 type 時改用該種訊息的子定義再驗一次，拿到看得懂的錯誤。
    const type = value && typeof value === "object" ? (value as Record<string, unknown>).type : undefined;
    const sub = typeof type === "string" ? byType.get(type) : undefined;
    if (sub && !sub(value)) return { ok: false, errors: describe(sub.errors) };
    return { ok: false, errors: describe(whole.errors?.filter((e) => e.keyword !== "oneOf")) };
  }

  return {
    validate,
    parse(text: string): Validation {
      let value: unknown;
      try {
        value = JSON.parse(text);
      } catch {
        return { ok: false, errors: ["不是合法的 JSON"] };
      }
      return validate(value);
    },
  };
}
