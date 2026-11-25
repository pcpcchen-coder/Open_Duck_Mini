import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { createValidator } from "../shared/validator.ts";

// 兩端共用的範例（protocol/examples）：合法的全部要過、不合法的全部要被拒。
// Python 端的同一組測試在 protocol/tests/test_schema.py（jsonschema）；這裡確認 Ajv 的判定一致。

const lines = (name: string) =>
  readFileSync(fileURLToPath(new URL(`../../protocol/examples/${name}`, import.meta.url)), "utf8")
    .split("\n")
    .filter((l) => l.trim());

describe("duck-link v0 schema（Ajv）", () => {
  const validator = createValidator();
  const valid = lines("valid.jsonl");
  const invalid = lines("invalid.jsonl");

  it("範例檔不是空的", () => {
    expect(valid.length).toBeGreaterThan(10);
    expect(invalid.length).toBeGreaterThan(5);
  });

  it.each(valid.map((l, i) => [i + 1, l] as const))("valid.jsonl 第 %i 行通過", (_n, line) => {
    const result = validator.parse(line);
    expect(result.ok ? [] : result.errors).toEqual([]);
  });

  it.each(invalid.map((l, i) => [i + 1, l] as const))("invalid.jsonl 第 %i 行被拒", (_n, line) => {
    expect(validator.parse(line).ok).toBe(false);
  });

  it("不是 JSON 的文字框被拒，錯誤不回顯內容", () => {
    const result = validator.parse("{secret");
    expect(result).toEqual({ ok: false, errors: ["不是合法的 JSON"] });
  });

  it("錯誤訊息指出欄位", () => {
    const result = validator.validate({ protocol_version: "0.1", type: "command", sent_at_ms: 1, request_id: "req_00000001", action: "walk", ttl_ms: 1000, params: { vx: 0.1 } });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.join(" ")).toContain("duration_s");
  });
});
