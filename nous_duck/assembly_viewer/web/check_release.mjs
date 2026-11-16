// 檢查進版控的 ../release/duck_viewer.html 和目前原始碼建置的 ../dist/duck_viewer.html 內容相同。
//   npm run build && npm run check:release
// 比對時忽略建置資訊（日期、commit），網格比對解壓後的位元組（不同 zlib 版本壓出來的位元組可能不同）。
// 不相同時代表 release 過期：請在原始碼 commit 後執行 npm run release，再 commit release/duck_viewer.html。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, "..", p), "utf8");

function parts(html, name) {
  const data = html.match(/(<script type="application\/json" id="viewer-data">)([\s\S]*?)(<\/script>)/);
  const mesh = html.match(/(<script type="application\/octet-stream" id="mesh-data">)([\s\S]*?)(<\/script>)/);
  if (!data || !mesh) throw new Error(`${name} 缺少內嵌資料`);
  const d = JSON.parse(data[2]);
  const build = d.build;
  delete d.build;
  return {
    build,
    data: JSON.stringify(d),
    mesh: gunzipSync(Buffer.from(mesh[2].trim(), "base64")),
    shell: html.replace(data[0], "<!--data-->").replace(mesh[0], "<!--mesh-->"),
  };
}

const rel = parts(read("release/duck_viewer.html"), "release/duck_viewer.html");
const cur = parts(read("dist/duck_viewer.html"), "dist/duck_viewer.html");
const diffs = [];
if (rel.data !== cur.data) diffs.push("零件或步驟資料不同（scene.json／steps.json 有改）");
if (!rel.mesh.equals(cur.mesh)) diffs.push("網格資料不同（meshes.bin 有改）");
if (rel.shell !== cur.shell) diffs.push("頁面、程式或樣式不同（web/src 或依賴有改）");
if (diffs.length) {
  console.error(`release/duck_viewer.html 過期（建置自 ${rel.build.git_commit}）：\n- ${diffs.join("\n- ")}`);
  console.error("請在原始碼 commit 後執行 npm run release，再 commit release/duck_viewer.html。");
  process.exit(1);
}
console.log(`release/duck_viewer.html 和目前原始碼一致（建置自 commit ${rel.build.git_commit}，${rel.build.built_at}）`);
