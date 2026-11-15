// 無頭瀏覽器檢查 dist/duck_viewer.html：斷網開啟、沒有錯誤、WebGL 有畫面、15 步都能切換、搜尋與點選可用。
//   node nous_duck/assembly_viewer/tests/web/check_viewer.cjs [輸出截圖的目錄]
// 需要 Playwright 與 Chromium（雲端容器內建；CI 會另外安裝）。驗證層級：無頭瀏覽器（SwiftShader 軟體算圖）。
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require("playwright");

const html = path.resolve(__dirname, "..", "..", "dist", "duck_viewer.html");
const outDir = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "dist", "screens"));
fs.mkdirSync(outDir, { recursive: true });

function fail(msg) {
  console.error("✗ " + msg);
  process.exitCode = 1;
}

async function canvasStats(page) {
  // 讀 WebGL 畫布像素，確認不是一片空白
  return page.evaluate(() => {
    const c = document.querySelector("#stage-canvas canvas");
    const g = document.createElement("canvas");
    g.width = 160;
    g.height = 120;
    const ctx = g.getContext("2d");
    ctx.drawImage(c, 0, 0, g.width, g.height);
    const d = ctx.getImageData(0, 0, g.width, g.height).data;
    const colors = new Set();
    let sum = 0, sum2 = 0;
    for (let i = 0; i < d.length; i += 4) {
      const v = d[i] * 0.3 + d[i + 1] * 0.59 + d[i + 2] * 0.11;
      sum += v;
      sum2 += v * v;
      colors.add((d[i] >> 3) * 1024 + (d[i + 1] >> 3) * 32 + (d[i + 2] >> 3));
    }
    const n = d.length / 4;
    return { std: Math.sqrt(sum2 / n - (sum / n) ** 2), colors: colors.size };
  });
}

(async () => {
  // CI 沒有 GPU：明確允許 SwiftShader 軟體 WebGL（雲端容器不加也能跑，加了不影響）
  const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  const results = { requests_blocked: [], console_errors: [], steps: [] };
  for (const vp of [
    { name: "desktop", viewport: { width: 1440, height: 900 } },
    { name: "phone", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
  ]) {
    const context = await browser.newContext({ viewport: vp.viewport, isMobile: vp.isMobile, hasTouch: vp.hasTouch, deviceScaleFactor: 1 });
    await context.route("**/*", (route) => {
      const url = route.request().url();
      if (url.startsWith("file:")) return route.continue();
      results.requests_blocked.push(url);
      return route.abort();
    });
    const page = await context.newPage();
    page.on("console", (m) => m.type() === "error" && results.console_errors.push(m.text()));
    page.on("pageerror", (e) => results.console_errors.push(String(e)));
    const t0 = Date.now();
    await page.goto("file://" + html);
    await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 120000 });
    const ready = await page.evaluate(() => document.body.dataset.ready);
    if (ready !== "true") {
      fail(`${vp.name}：載入失敗 ${await page.textContent("#fatal")}`);
      await context.close();
      continue;
    }
    results[`${vp.name}_load_ms`] = Date.now() - t0;
    await page.waitForTimeout(800);

    if (vp.name === "desktop") {
      const nSteps = await page.locator("#step-list li").count();
      if (nSteps !== 15) fail(`步驟數 ${nSteps}，預期 15`);
      for (let i = 0; i < nSteps; i++) {
        await page.locator("#step-list li button").nth(i).click();
        await page.waitForTimeout(700);
        const title = await page.textContent("#step-detail h2");
        const stats = await canvasStats(page);
        results.steps.push({ step: i + 1, title, ...stats });
        if (stats.colors < 8) fail(`第 ${i + 1} 步畫面幾乎空白（${stats.colors} 色）`);
        const file = `desktop_step${String(i + 1).padStart(2, "0")}.png`;
        await page.screenshot({ path: path.join(outDir, file) });
      }
      // 小腿那一步，從正面看左右腿差異（右腿膝踝舵機在內側）
      await page.locator("#step-list li button").nth(3).click();
      await page.click('[data-view="front"]');
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(outDir, "desktop_shins_front.png") });
      // 整機＋爆炸＋透視
      await page.click("#mode-all");
      await page.locator("#explode").fill("100");
      await page.check("#xray");
      await page.click('[data-view="iso"]');
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(outDir, "desktop_all_exploded_xray.png") });
      results.exploded = await canvasStats(page);
      // 搜尋 ID 24 → 點選 → 資訊卡
      await page.fill("#part-search", "ID 24");
      const rows = await page.locator("#part-list .part-row").count();
      if (rows !== 1) fail(`搜尋「ID 24」得到 ${rows} 列，預期 1`);
      await page.locator("#part-list .part-row").first().click();
      await page.waitForTimeout(700);
      const infoText = await page.textContent("#part-info");
      if (!infoText.includes("左踝") || !infoText.includes("第 3 步")) fail(`ID 24 的資訊不對：${infoText}`);
      results.search_id24 = infoText.replace(/\s+/g, " ").trim();
      await page.screenshot({ path: path.join(outDir, "desktop_select_id24.png") });
      // 在畫面中央點一下，應該選到零件
      await page.click("#clear-btn");
      await page.click("#mode-all");
      await page.locator("#explode").fill("0");
      await page.uncheck("#xray");
      await page.click('[data-view="front"]');
      await page.waitForTimeout(700);
      const box = await page.locator("#stage-canvas canvas").boundingBox();
      await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.45);
      await page.waitForTimeout(300);
      results.center_click = (await page.textContent("#part-info h3").catch(() => null)) || null;
      if (!results.center_click) fail("點畫面中央沒有選到零件");
      // 進度存在 localStorage，重新整理後還在
      await page.locator("#step-list li button").nth(0).click();
      await page.check("#step-detail .done-toggle input");
      await page.reload();
      await page.waitForFunction(() => document.body.dataset.ready === "true", null, { timeout: 120000 });
      const doneAfterReload = await page.locator("#step-list .step-num.is-done").count();
      if (doneAfterReload !== 1) fail(`重新整理後完成步驟數 ${doneAfterReload}，預期 1`);
    } else {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      results.phone_horizontal_overflow_px = overflow;
      if (overflow > 0) fail(`手機寬度有水平捲動（多 ${overflow}px）`);
      await page.screenshot({ path: path.join(outDir, "phone_step1.png"), fullPage: false });
      await page.click('[data-tab="parts"]');
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(outDir, "phone_parts.png"), fullPage: true });
      results.phone = await canvasStats(page);
    }
    await context.close();
  }
  await browser.close();
  if (results.requests_blocked.length) fail(`有對外請求：${results.requests_blocked.join(", ")}`);
  if (results.console_errors.length) fail(`有錯誤：${results.console_errors.join(" | ")}`);
  fs.writeFileSync(path.join(outDir, "results.json"), JSON.stringify(results, null, 1));
  console.log(JSON.stringify(results, null, 1));
  console.log(process.exitCode ? "檢查未通過" : `檢查通過，截圖在 ${outDir}`);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
