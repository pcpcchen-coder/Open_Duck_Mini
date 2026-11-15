// 檢查 dist/duck_viewer.html 是單一檔、不引用外部資源、大小在上限內。
//   npm run check
import { readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const file = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "duck_viewer.html");
const html = readFileSync(file, "utf8");
const size = statSync(file).size;
const LIMIT = 16 * 1024 * 1024;
const problems = [];

if (size > LIMIT) problems.push(`檔案 ${size} bytes，超過 ${LIMIT}`);
const checks = [
  [/<script\b[^>]*\bsrc\s*=/i, "有 <script src>（外部程式）"],
  [/<link\b/i, "有 <link>（外部樣式或資源）"],
  [/<(img|iframe|video|audio|source|embed|object)\b[^>]*\bsrc\s*=\s*["']?https?:/i, "有載入外部網址的媒體標籤"],
  [/url\(\s*["']?https?:/i, "CSS 有 url(http…)"],
  [/@import/i, "CSS 有 @import"],
  [/\/\*__(STYLE|DATA|MESHES|SCRIPT)__\*\//, "範本標記沒有被取代"],
];
for (const [re, msg] of checks) if (re.test(html)) problems.push(msg);

const data = html.match(/<script type="application\/json" id="viewer-data">([\s\S]*?)<\/script>/);
if (!data) problems.push("找不到 viewer-data");
else {
  const d = JSON.parse(data[1]);
  if (d.scene.parts.length !== 138) problems.push(`零件數 ${d.scene.parts.length}，預期 138`);
  if (d.steps.steps.length < 1) problems.push("沒有步驟");
}

if (problems.length) {
  console.error("輸出檢查失敗：\n- " + problems.join("\n- "));
  process.exit(1);
}
console.log(`輸出檢查通過：${file}（${(size / 1024 / 1024).toFixed(2)} MB，單一檔、沒有外部資源）`);
