// 打包舵機控制台的頁面（nous_duck/robot/servo_console 用）：沿用組裝檢視器的 pipeline 輸出與網格。
//   cd nous_duck/assembly_viewer/web && npm ci && npm run build:console
// 輸出（不進版控）：
//   ../dist/duck_console.html    單一 HTML（程式、樣式、模型都內嵌），由 Pi 上的伺服器提供
//   ../dist/console_joints.json  14 個關節的範圍（robot.xml），伺服器用來夾住目標角度
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import * as esbuild from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const buildDir = join(here, "..", "dist", "build");
const outHtml = join(here, "..", "dist", "duck_console.html");
const outJoints = join(here, "..", "dist", "console_joints.json");
const REPO_URL = "https://github.com/pcpcchen-coder/Open_Duck_Mini";
const SERVO_IDS = [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33];

for (const f of ["scene.json", "meshes.bin"]) {
  if (!existsSync(join(buildDir, f))) {
    console.error(`缺少 ${join(buildDir, f)}。先執行 pipeline：cd ../pipeline && python -m viewer_pipeline`);
    process.exit(1);
  }
}
const scene = JSON.parse(readFileSync(join(buildDir, "scene.json"), "utf8"));
const meshBin = readFileSync(join(buildDir, "meshes.bin"));
if (meshBin.length !== scene.summary.meshes_bin_bytes) {
  console.error("meshes.bin 和 scene.json 對不上，請重新執行 pipeline");
  process.exit(1);
}
if (!Array.isArray(scene.bodies) || !Array.isArray(scene.joints)) {
  console.error("scene.json 缺少 bodies／joints（pipeline 太舊？）");
  process.exit(1);
}

const servoJoints = scene.joints.filter((j) => j.servo_id !== null);
const ids = servoJoints.map((j) => j.servo_id).sort((a, b) => a - b);
if (JSON.stringify(ids) !== JSON.stringify(SERVO_IDS)) {
  console.error(`關節的舵機 ID 不是預期的 14 顆：${ids}`);
  process.exit(1);
}
for (const j of servoJoints) {
  if (!j.range_rad || j.range_rad.length !== 2 || !(j.range_rad[0] < j.range_rad[1])) {
    console.error(`${j.name} 沒有合理的範圍：${j.range_rad}`);
    process.exit(1);
  }
}

function git(...args) {
  try {
    return execFileSync("git", args, { cwd: here, encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}
const dirty = git("status", "--porcelain", "--", "..", "../../robot/servo_console", ":(exclude)../release").length > 0;
const commit = (git("rev-parse", "--short", "HEAD") || "unknown") + (dirty ? "-dirty" : "");
const epoch = process.env.SOURCE_DATE_EPOCH;
const builtAt = (epoch ? new Date(Number(epoch) * 1000) : new Date()).toISOString().slice(0, 10);
const threeVersion = JSON.parse(readFileSync(join(here, "node_modules", "three", "package.json"), "utf8")).version;

const js = await esbuild.build({
  entryPoints: [join(here, "src", "console", "main.ts")],
  bundle: true,
  format: "iife",
  target: ["es2020"],
  minify: true,
  legalComments: "eof",
  write: false,
  logLevel: "warning",
});
const cssSrc = readFileSync(join(here, "src", "style.css"), "utf8") + "\n" + readFileSync(join(here, "src", "console", "console.css"), "utf8");
const css = await esbuild.transform(cssSrc, { loader: "css", minify: true });

const data = { scene, build: { built_at: builtAt, git_commit: commit, repo_url: REPO_URL, three_version: threeVersion } };
const dataJson = JSON.stringify(data).replace(/</g, "\\u003c");
const meshB64 = gzipSync(meshBin, { level: 9 }).toString("base64");
const script = js.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");

let html = readFileSync(join(here, "src", "console", "index.html"), "utf8");
const fill = (marker, value) => {
  if (!html.includes(marker)) throw new Error(`範本缺少 ${marker}`);
  html = html.replace(marker, () => value);
};
fill("/*__STYLE__*/", css.code);
fill("/*__DATA__*/", dataJson);
fill("/*__MESHES__*/", meshB64);
fill("/*__SCRIPT__*/", script);

const joints = {
  schema: "nous-duck/console-joints@1",
  source: "mini_bdx/robots/open_duck_mini_v2/robot.xml（經 assembly_viewer pipeline）",
  robot_xml_sha256: scene.sources["mini_bdx/robots/open_duck_mini_v2/robot.xml"],
  git_commit: commit,
  joints: servoJoints.map((j) => ({ name: j.name, servo_id: j.servo_id, range_rad: j.range_rad })),
};

mkdirSync(dirname(outHtml), { recursive: true });
writeFileSync(outHtml, html);
writeFileSync(outJoints, JSON.stringify(joints, null, 1) + "\n");
const kb = (n) => `${(n / 1024).toFixed(0)} KB`;
console.log(`duck_console.html  ${outHtml}（${kb(Buffer.byteLength(html))}）`);
console.log(`console_joints.json  ${outJoints}（${joints.joints.length} 個關節）；commit ${commit}`);
