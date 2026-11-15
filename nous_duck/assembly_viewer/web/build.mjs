// 把 pipeline 輸出（scene.json、meshes.bin、steps.json）與前端程式打包成單一、可離線開啟的 HTML。
//   cd nous_duck/assembly_viewer/web && npm ci && npm run build
// 輸出：../dist/duck_viewer.html（不進版控）
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import * as esbuild from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const buildDir = join(here, "..", "dist", "build");
const outFile = join(here, "..", "dist", "duck_viewer.html");
const REPO_URL = "https://github.com/pcpcchen-coder/Open_Duck_Mini";

for (const f of ["scene.json", "meshes.bin", "steps.json"]) {
  if (!existsSync(join(buildDir, f))) {
    console.error(`缺少 ${join(buildDir, f)}。先執行 pipeline：cd ../pipeline && python -m viewer_pipeline`);
    process.exit(1);
  }
}

const scene = JSON.parse(readFileSync(join(buildDir, "scene.json"), "utf8"));
const steps = JSON.parse(readFileSync(join(buildDir, "steps.json"), "utf8"));
const meshBin = readFileSync(join(buildDir, "meshes.bin"));
if (meshBin.length !== scene.summary.meshes_bin_bytes) {
  console.error(`meshes.bin 大小 ${meshBin.length} 和 scene.json 記錄的 ${scene.summary.meshes_bin_bytes} 不符，請重新執行 pipeline`);
  process.exit(1);
}

function git(...args) {
  try {
    return execFileSync("git", args, { cwd: here, encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}
const dirty = git("status", "--porcelain", "--", "..").length > 0;
const commit = (git("rev-parse", "--short", "HEAD") || "unknown") + (dirty ? "-dirty" : "");
const epoch = process.env.SOURCE_DATE_EPOCH;
const builtAt = (epoch ? new Date(Number(epoch) * 1000) : new Date()).toISOString().slice(0, 10);
const threeVersion = JSON.parse(readFileSync(join(here, "node_modules", "three", "package.json"), "utf8")).version;

const js = await esbuild.build({
  entryPoints: [join(here, "src", "main.ts")],
  bundle: true,
  format: "iife",
  target: ["es2020"],
  minify: true,
  legalComments: "eof",
  write: false,
  logLevel: "warning",
});
const css = await esbuild.transform(readFileSync(join(here, "src", "style.css"), "utf8"), { loader: "css", minify: true });

const data = { scene, steps, build: { built_at: builtAt, git_commit: commit, repo_url: REPO_URL, three_version: threeVersion } };
// JSON 放進 <script> 前，把 < 換成 <，避免內容提早結束 script 標籤
const dataJson = JSON.stringify(data).replace(/</g, "\\u003c");
const meshB64 = gzipSync(meshBin, { level: 9 }).toString("base64");
const script = js.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");

let html = readFileSync(join(here, "src", "index.html"), "utf8");
const fill = (marker, value) => {
  if (!html.includes(marker)) throw new Error(`範本缺少 ${marker}`);
  html = html.replace(marker, () => value);
};
fill("/*__STYLE__*/", css.code);
fill("/*__DATA__*/", dataJson);
fill("/*__MESHES__*/", meshB64);
fill("/*__SCRIPT__*/", script);

mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(outFile, html);
const kb = (n) => `${(n / 1024).toFixed(0)} KB`;
console.log(`duck_viewer.html  ${outFile}`);
console.log(`  總大小 ${kb(Buffer.byteLength(html))}（網格 gzip+base64 ${kb(meshB64.length)}、程式 ${kb(script.length)}、資料 ${kb(dataJson.length)}、樣式 ${kb(css.code.length)}）`);
console.log(`  ${scene.parts.length} 個零件、${steps.steps.length} 步；commit ${commit}；three.js ${threeVersion}`);
