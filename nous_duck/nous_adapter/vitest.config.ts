import { defineConfig } from "vitest/config";

// 測試只連本機的臨時埠（port 0），不碰開發用的 8791，也不連執行中的 Nous。
export default defineConfig({
  test: { include: ["tests/**/*.test.ts"], testTimeout: 10_000 },
});
