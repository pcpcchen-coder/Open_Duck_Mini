// 無頭瀏覽器檢查鴨子設定頁（桌面與手機寬度），對著**模擬的服務**實際操作一遍並截圖。
//
//   PYTHON=<有 numpy、duckd 依賴的 python> node nous_duck/robot/settings/tests/web/check_settings.cjs [輸出截圖的目錄]
//
// 這支腳本自己啟動三個行程（結束時全部關掉），都只綁 127.0.0.1：
//   1. 設定頁伺服器（真的）
//   2. 聲源方位服務，用模擬麥克風（`--mock-angle`，訊息帶 mock: true）
//   3. duckd，用模擬身體（`--body mock`），不連 hub、不碰硬體
// 驗證層級：無頭瀏覽器＋模擬服務。不是實機。
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const robot = path.resolve(__dirname, "..", "..", "..");
const outDir = path.resolve(process.argv[2] || path.join(robot, "settings", "dist", "screens"));
const python = process.env.PYTHON || "python3";
fs.mkdirSync(outDir, { recursive: true });
const work = fs.mkdtempSync(path.join(fs.existsSync("/tmp") ? "/tmp" : os.tmpdir(), "ducks-"));
const settingsDir = path.join(work, "settings");
const sock = path.join(work, "duckd.sock");
const procs = [];
const results = [];
let failed = false;

function ok(name, cond, detail) {
  results.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  console.log((cond ? "✓ " : "✗ ") + name + (detail !== undefined && !cond ? "  → " + JSON.stringify(detail) : ""));
  if (!cond) failed = true;
}
function freePort() {
  return new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
}
function run(name, cwd, args, env) {
  const log = fs.openSync(path.join(work, name + ".log"), "w");
  const p = spawn(python, args, { cwd, env: { ...process.env, PYTHONUNBUFFERED: "1", ...env }, stdio: ["ignore", log, log] });
  procs.push(p);
  return p;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 15000, step = 150) {
  const end = Date.now() + ms;
  for (;;) { let v; try { v = await fn(); } catch (e) { v = false; } if (v) return v; if (Date.now() > end) return false; await sleep(step); }
}
const chip = (page, key) => page.locator(`[data-effect="${key}"]`).innerText();
const card = (page, key) => page.locator(`[id="card-${key}"]`);

(async () => {
  const port = await freePort();
  const udp = 20000 + Math.floor(Math.random() * 20000);
  const base = `http://127.0.0.1:${port}`;
  run("settings", path.join(robot, "settings"), ["-m", "duck_settings", "--dir", settingsDir, "--bind", "127.0.0.1", "--port", String(port), "--display-name", "duck-sim（模擬）"], { DUCKD_SOCKET: sock });
  run("doa", path.join(robot, "audio"), ["-m", "duck_audio.doa", "--run", "--mock-angle", "30", "--settings-dir", settingsDir, "--port", String(udp)], {});
  run("duckd", path.join(robot, "duckd"), ["-m", "duckd", "--body", "mock", "--settings-dir", settingsDir, "--ctl-socket", sock, "--percept-port", String(udp),
    "--url", "ws://127.0.0.1:9/duck-link", "--eyes-panel", path.join(work, "eyes.png"), "--eyes-fps", "2"], {});
  const api = async (p) => (await fetch(base + p)).json();
  ok("設定頁伺服器起來了", await until(async () => (await fetch(base + "/healthz")).ok));
  ok("模擬的 duckd 與聲源方位服務都回報了實際在用的設定", await until(async () => {
    const st = await api("/api/state");
    const by = Object.fromEntries(st.settings.map((s) => [s.key, s.effect.state]));
    return by["head.speed_deg_s"] === "applied" && by["hearing.min_speech_energy"] === "applied" && st.duckd.reachable;
  }, 30000), fs.readFileSync(path.join(work, "duckd.log"), "utf8").slice(-600));

  const browser = await chromium.launch();
  const external = [];
  const consoleErrors = [];
  async function open(viewport, mobile) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: mobile ? 2 : 1, isMobile: !!mobile, hasTouch: !!mobile, locale: "zh-TW" });
    const page = await ctx.newPage();
    page.on("request", (r) => { const u = r.url(); if (!u.startsWith(base) && !u.startsWith("data:")) external.push(u); });
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await page.goto(base + "/");
    await page.waitForSelector('[id="card-hearing.min_speech_energy"]');
    await page.waitForFunction(() => document.querySelectorAll(".expr img").length === 25, null, { timeout: 60000 });
    return page;
  }

  // ---------------------------------------------------------------- 桌面
  const page = await open({ width: 1280, height: 900 });
  ok("七個分區加系統狀態都在", (await page.locator("nav a").allInnerTexts()).join("|") === "功能開關|語音與聲音|聽聲轉頭門檻|頭部動作|眼睛|隱私|機體量測值|系統狀態");
  ok("表情預覽 25 張都畫出來了", await page.evaluate(() => [...document.querySelectorAll(".expr img")].every((i) => i.complete && i.naturalWidth === 200)));
  ok("已實作的設定顯示「已生效」", (await chip(page, "hearing.min_speech_energy")) === "已生效" && (await chip(page, "features.track_sound")) === "已生效");
  const blocked = card(page, "audio.volume_cap_night");
  ok("規劃中的項目停用、標示原因", (await blocked.locator("input").first().isDisabled()) && /規劃中/.test(await blocked.innerText()) && /還不能設定/.test(await blocked.innerText()));
  ok("硬體未到的項目停用", (await card(page, "privacy.camera").locator("input").isDisabled()) && /硬體未到/.test(await card(page, "privacy.camera").innerText()));
  ok("量測值沒勾確認前不能改", await card(page, "calibration.mic.front_angle_deg").locator("input[type=number]").isDisabled());
  await page.screenshot({ path: path.join(outDir, "settings-desktop-full.png"), fullPage: true });
  await page.screenshot({ path: path.join(outDir, "settings-desktop-top.png") });

  // 改門檻 → 儲存 → 執行中的服務套用
  const energy = card(page, "hearing.min_speech_energy").locator("input[type=number]");
  await energy.fill("300000");
  await energy.blur();
  ok("改了之後出現儲存列", /1 項還沒儲存/.test(await page.locator("#dirtycount").innerText()));
  await page.click("#save");
  await page.waitForFunction(() => /已儲存 1 項/.test(document.getElementById("toast").textContent));
  ok("儲存後聲源方位服務約 1 秒內套用，頁面顯示已生效", await until(async () => (await chip(page, "hearing.min_speech_energy")) === "已生效" && /目前 300,000/.test(await card(page, "hearing.min_speech_energy").innerText()), 8000));
  const applied = JSON.parse(fs.readFileSync(path.join(settingsDir, "applied", "duck-doa.json"), "utf8"));
  ok("服務回報的值就是新的值", applied.values["hearing.min_speech_energy"] === 300000);

  // 要重啟的項目：照實說還沒生效
  const speed = card(page, "head.speed_deg_s").locator("input[type=number]");
  await speed.fill("45");
  await speed.blur();
  await page.click("#save");
  ok("頭部角速度改了：顯示要重啟 duckd、現在用的還是 30", await until(async () => /要重啟 duckd 才生效（現在用的是 30）/.test(await chip(page, "head.speed_deg_s")), 8000), await chip(page, "head.speed_deg_s"));
  await card(page, "head.speed_deg_s").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(outDir, "settings-desktop-restart-needed.png") });

  // 超出範圍：不儲存，回報原因
  await speed.fill("999");
  await speed.blur();
  await page.click("#save");
  await page.waitForFunction(() => /沒有儲存/.test(document.getElementById("toast").textContent));
  ok("超出範圍被拒絕並說明原因", /超出範圍 5～60/.test(await card(page, "head.speed_deg_s").innerText()));
  ok("被拒絕的值沒有寫進去", (await api("/api/state")).settings.find((s) => s.key === "head.speed_deg_s").value === 45);
  await page.screenshot({ path: path.join(outDir, "settings-desktop-rejected.png") });
  await page.click("#discard");

  // presence 對應的表情：改了之後 duckd 套用
  await card(page, "eyes.presence.thinking").locator("select").selectOption("curious");
  await page.click("#save");
  ok("presence 表情對應改了，duckd 即時套用", await until(async () => (await chip(page, "eyes.presence.thinking")) === "已生效" && /目前 curious/.test(await card(page, "eyes.presence.thinking").innerText()), 8000));

  // 眼睛亮度與幀率：改了之後 duckd 即時套用（模擬的 duckd 只有虛擬面板，套用的是渲染端）
  const bright = card(page, "eyes.brightness").locator("input[type=number]");
  await bright.fill("0.5");
  await bright.blur();
  await page.click("#save");
  ok("眼睛亮度改了，duckd 即時套用", await until(async () => (await chip(page, "eyes.brightness")) === "已生效" && /目前 0.5/.test(await card(page, "eyes.brightness").innerText()), 8000), await chip(page, "eyes.brightness"));
  ok("亮度說明寫明是軟體調暗、不省電", /不會省電/.test(await card(page, "eyes.brightness").innerText()));
  const openAdv = () => page.evaluate(() => { document.querySelector("#sec-eyes details").open = true; });
  await openAdv();
  const fps = card(page, "eyes.fps").locator("input[type=number]");
  await fps.fill("8");
  await fps.blur();
  await page.click("#save");
  ok("眼睛幀率改了，duckd 即時套用", await until(async () => (await openAdv(), await chip(page, "eyes.fps")) === "已生效" && /目前 8/.test(await card(page, "eyes.fps").innerText()), 8000), await chip(page, "eyes.fps"));
  await openAdv();  // 儲存後頁面重畫，進階區會收起來
  await fps.fill("30");
  await fps.blur();
  await page.click("#save");
  await page.waitForFunction(() => /沒有儲存/.test(document.getElementById("toast").textContent));
  ok("幀率超出範圍被拒絕", /超出範圍 2～20/.test(await card(page, "eyes.fps").innerText()));
  await page.click("#discard");

  // 在鴨子上預覽（模擬的 duckd：虛擬面板）
  await page.locator(".expr", { hasText: "happy" }).first().locator("button").click();
  await page.waitForFunction(() => /虛擬面板/.test(document.getElementById("toast").textContent));
  ok("在鴨子上預覽：duckd 換成該表情，並說明是虛擬面板", await until(async () => (await api("/api/state")).duckd.expression === "happy", 5000));

  // 隱私：收緊可以，之後這一頁打不開
  page.once("dialog", (d) => d.accept());
  await card(page, "privacy.sound_direction").locator("input").uncheck({ force: true });
  await page.click("#save");
  ok("關掉「讀取聲源方向」後服務停止讀取", await until(async () => (await chip(page, "privacy.sound_direction")) === "已生效" && /目前 關/.test(await card(page, "privacy.sound_direction").innerText()), 8000));
  ok("收緊後這一頁的開關鎖住，並告訴你怎麼放寬", (await card(page, "privacy.sound_direction").locator("input").isDisabled()) && /duck-settings set privacy.sound_direction true/.test(await card(page, "privacy.sound_direction").innerText()));
  const forced = await page.evaluate(async () => (await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json", "X-Duck-Settings": "1" }, body: JSON.stringify({ changes: { "privacy.sound_direction": true } }) })).status);
  ok("繞過頁面直接打 API 放寬也被拒絕", forced === 400);
  await card(page, "privacy.sound_direction").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(outDir, "settings-desktop-privacy.png") });
  await page.locator("#sec-eyes").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(outDir, "settings-desktop-eyes.png") });
  await page.locator("#sec-system").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(outDir, "settings-desktop-system.png") });
  ok("變更紀錄有記下來源", /設定頁/.test(await page.locator("#sec-system").innerText()));

  // ---------------------------------------------------------------- 手機寬度
  const phone = await open({ width: 390, height: 844 }, true);
  ok("手機寬度沒有水平捲動", await phone.evaluate(() => document.documentElement.scrollWidth <= 391 && window.innerWidth <= 391));
  ok("手機上開關的觸控範圍夠大（≥ 32 px 高）", await phone.evaluate(() => [...document.querySelectorAll(".switch")].every((e) => e.getBoundingClientRect().height >= 32)));
  await phone.screenshot({ path: path.join(outDir, "settings-phone-top.png") });
  await phone.locator("#sec-hearing").scrollIntoViewIfNeeded();
  await phone.evaluate(() => document.getElementById("sec-hearing").scrollIntoView());
  await phone.screenshot({ path: path.join(outDir, "settings-phone-hearing.png") });
  await phone.evaluate(() => document.getElementById("gallery").scrollIntoView());
  await phone.screenshot({ path: path.join(outDir, "settings-phone-eyes.png") });
  const recenter = card(phone, "hearing.recenter_s").locator("input[type=number]");
  await recenter.fill("12");
  await recenter.blur();
  await phone.evaluate(() => document.getElementById("card-hearing.recenter_s").scrollIntoView({ block: "center" }));
  await phone.screenshot({ path: path.join(outDir, "settings-phone-unsaved.png") });
  await phone.tap("#save");
  ok("手機上儲存，duckd 即時套用", await until(async () => (await chip(phone, "hearing.recenter_s")) === "已生效" && /目前 12 秒/.test(await card(phone, "hearing.recenter_s").innerText()), 8000));
  await phone.screenshot({ path: path.join(outDir, "settings-phone-full.png"), fullPage: true });

  ok("頁面沒有向外部網路要任何資源", external.length === 0, external);
  ok("瀏覽器 console 沒有錯誤（被拒絕的請求除外）", consoleErrors.filter((e) => !/400|409|503/.test(e)).length === 0, consoleErrors);
  await browser.close();
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify({ ok: !failed, checks: results, note: "duckd 是模擬身體、麥克風是模擬裝置（mock）；不是實機" }, null, 1));
})().catch((e) => { console.error(e); failed = true; }).finally(() => {
  for (const p of procs) p.kill("SIGTERM");
  setTimeout(() => { for (const p of procs) p.kill("SIGKILL"); fs.rmSync(work, { recursive: true, force: true }); process.exit(failed ? 1 : 0); }, 1500);
});
