// 把剛建置好的 ../dist/duck_viewer.html 複製到 ../release/duck_viewer.html（這份進版控，給人直接下載）。
//   npm run release   # = npm run build + 本腳本
// 要在原始碼都已 commit 的狀態下執行，頁面裡記錄的 commit 才不會帶 -dirty。
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "dist", "duck_viewer.html");
const dst = join(here, "..", "release", "duck_viewer.html");
const commit = readFileSync(src, "utf8").match(/"git_commit":"([^"]+)"/)?.[1] ?? "unknown";
if (commit.endsWith("-dirty") || commit === "unknown") {
  console.error(`建置時原始碼有未 commit 的改動（${commit}）。先 commit，再執行 npm run release。`);
  process.exit(1);
}
mkdirSync(dirname(dst), { recursive: true });
copyFileSync(src, dst);
console.log(`已更新 ${dst}（建置自 commit ${commit}）`);
