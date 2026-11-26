// 舵機控制台的頁面：輪詢 /api/state、畫 3D 姿勢、送指令。所有安全規則在伺服器端；這裡只負責顯示與送出。
import { readMeshBin } from "../data";
import { drawChart } from "./charts";
import { type CameraView, PoseViewer } from "./pose_viewer";
import type { ConsoleBundle, ConsoleState, HistorySample, JointState } from "./types";

const TOKEN_KEY = "nous-duck-console:token";
const POLL_MS = 200;
const SEND_MS = 80;
const GROUP_ZH: Record<JointState["group"], string> = { right_leg: "右腳（ID 10–14）", left_leg: "左腳（ID 20–24）", head: "脖子與頭（ID 30–33）" };
const RAD = Math.PI / 180;

const $ = <T extends HTMLElement = HTMLElement>(sel: string): T => {
  const e = document.querySelector<T>(sel);
  if (!e) throw new Error(`頁面缺少元素 ${sel}`);
  return e;
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const fmt = (v: number | null | undefined, digits = 1, unit = "°") => (v === null || v === undefined ? "—" : `${v.toFixed(digits)}${unit}`);
const sideOf = (name: string) => (name.startsWith("left_") ? "left" : name.startsWith("right_") ? "right" : "center");

function readBundle(): ConsoleBundle {
  const node = document.getElementById("viewer-data");
  if (!node?.textContent) throw new Error("頁面裡找不到模型資料");
  const bundle = JSON.parse(node.textContent) as ConsoleBundle;
  if (bundle.scene.schema !== "nous-duck/viewer-scene@1") throw new Error(`不支援的 scene 版本：${bundle.scene.schema}`);
  return bundle;
}

// ---------------------------------------------------------------- token 與 API
function loadToken(): string {
  const m = location.hash.match(/(?:^#|&)t=([^&]+)/);
  if (m) {
    const t = decodeURIComponent(m[1]);
    try {
      localStorage.setItem(TOKEN_KEY, t);
    } catch {
      /* 私密瀏覽時存不了，只用這次 */
    }
    history.replaceState(null, "", location.pathname + location.search);
    return t;
  }
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

let token = loadToken();

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Duck-Token": token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = (await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))) as { ok: boolean; error?: string } & T;
  if (!res.ok || !data.ok) throw new HttpError(res.status, data.error ?? `HTTP ${res.status}`);
  return data;
}

let toastTimer = 0;
function toast(message: string): void {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (t.hidden = true), 4000);
}

async function send(action: string, body: Record<string, unknown> = {}): Promise<Record<string, unknown> | null> {
  try {
    const res = await request<Record<string, unknown>>(`/api/${action}`, body);
    const notes = res.notes as string[] | undefined;
    if (notes?.length) toast(notes.join("；"));
    void poll();
    return res;
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) askToken();
    toast(err instanceof Error ? err.message : String(err));
    return null;
  }
}

function askToken(): void {
  const dlg = $<HTMLDialogElement>("#token-dialog");
  if (!dlg.open) dlg.showModal();
}

// ---------------------------------------------------------------- 狀態
let state: ConsoleState | null = null;
let selected = "head_yaw";
let show3d: "actual" | "target" = "actual";
let viewer: PoseViewer | null = null;
const pending = new Map<string, number>();
const dragging = new Set<string>();
let sendTimer = 0;

function queueTarget(name: string, deg: number): void {
  pending.set(name, deg);
  if (sendTimer) return;
  sendTimer = window.setTimeout(() => {
    sendTimer = 0;
    const targets = Object.fromEntries(pending);
    pending.clear();
    void send("targets", { targets_deg: targets });
  }, SEND_MS);
}

function canMove(j: JointState): boolean {
  return !!state?.connected && !state.estop && j.torque === true;
}

// ---------------------------------------------------------------- 舵機清單
interface Row {
  root: HTMLElement;
  slider: HTMLInputElement;
  torque: HTMLInputElement;
  val: HTMLElement;
  temp: HTMLElement;
}
const rows = new Map<string, Row>();

function buildRows(joints: JointState[]): void {
  const list = $("#joint-list");
  list.replaceChildren();
  let group = "";
  for (const j of joints) {
    if (j.group !== group) {
      group = j.group;
      list.appendChild(el("h3", undefined, GROUP_ZH[j.group]));
    }
    const root = el("div", "jrow");
    root.dataset.name = j.name;
    const id = el("span", `jid side-${sideOf(j.name)}`, String(j.id));
    const name = el("span", "jname", j.zh);
    const tqLabel = el("label", "jtq");
    const torque = el("input");
    torque.type = "checkbox";
    torque.setAttribute("aria-label", `ID ${j.id} 出力`);
    tqLabel.append(torque, document.createTextNode("出力"));
    const slider = el("input", "jslider");
    slider.type = "range";
    slider.min = String(j.lo_deg);
    slider.max = String(j.hi_deg);
    slider.step = "0.5";
    slider.setAttribute("aria-label", `ID ${j.id} ${j.zh} 目標角度`);
    const val = el("span", "jval");
    const temp = el("span", "jtemp");
    root.append(id, name, tqLabel, slider, val, temp);
    list.appendChild(root);

    root.addEventListener("click", (e) => {
      if (e.target === slider || e.target === torque || e.target === tqLabel) return;
      select(j.name);
    });
    torque.addEventListener("change", () => {
      void send("torque", { joints: [j.name], on: torque.checked });
    });
    slider.addEventListener("pointerdown", () => {
      dragging.add(j.name);
      select(j.name);
    });
    const done = () => window.setTimeout(() => dragging.delete(j.name), 400);
    slider.addEventListener("pointerup", done);
    slider.addEventListener("change", done);
    slider.addEventListener("input", () => {
      dragging.add(j.name);
      queueTarget(j.name, Number(slider.value));
    });
    rows.set(j.name, { root, slider, torque, val, temp });
  }
}

function updateRows(s: ConsoleState): void {
  for (const j of s.joints) {
    const r = rows.get(j.name);
    if (!r) continue;
    r.root.classList.toggle("is-selected", j.name === selected);
    r.torque.checked = j.torque === true;
    r.torque.disabled = !s.connected || (!!s.estop && j.torque !== true);
    r.slider.disabled = !canMove(j);
    if (!dragging.has(j.name) && document.activeElement !== r.slider) {
      const v = j.target_deg ?? j.actual_deg;
      if (v !== null) r.slider.value = String(v);
    }
    r.val.textContent = `目標 ${fmt(j.target_deg)} · 實際 ${fmt(j.actual_deg)}`;
    r.temp.textContent = (j.temperature === null ? "—" : `${j.temperature}°C`) + (j.voltage === null ? "" : ` · ${j.voltage.toFixed(1)}V`);
    r.temp.className = "jtemp" + (j.temperature !== null && j.temperature >= s.limits.temp_stop_c ? " bad" : j.temperature !== null && j.temperature >= s.limits.temp_warn_c ? " warn" : "");
  }
  const on = s.joints.filter((j) => j.torque).length;
  $("#joint-summary").textContent = s.connected ? `${on}／14 出力` : "未連線";
}

function select(name: string): void {
  selected = name;
  const j = state?.joints.find((x) => x.name === name);
  viewer?.setSelected(j ? j.id : null);
  if (state) {
    updateRows(state);
    renderSelected(state);
  }
  selectTab("joint");
}

// ---------------------------------------------------------------- 右側面板
function selectTab(tab: string): void {
  document.querySelectorAll<HTMLButtonElement>(".tabbar [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll<HTMLElement>("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== tab));
}

function kv(pairs: [string, string][]): HTMLDListElement {
  const dl = el("dl", "kv");
  for (const [k, v] of pairs) dl.append(el("dt", undefined, k), el("dd", undefined, v));
  return dl;
}

const current = (name: string) => state?.joints.find((x) => x.name === name);
let selectedKey = "";
let selectedValues: HTMLElement[] = [];

/** 選取面板：結構只在選取或狀態改變時重建（避免按鈕被重畫而點不到），數字每次原地更新。 */
function renderSelected(s: ConsoleState): void {
  const pane = $("#pane-joint");
  const j = s.joints.find((x) => x.name === selected);
  if (!j) return;
  const values = [
    fmt(j.actual_deg),
    fmt(j.target_deg),
    fmt(j.cmd_deg),
    `${j.lo_deg.toFixed(0)}° ～ ${j.hi_deg.toFixed(0)}°`,
    j.torque === null ? "—" : j.torque ? "是" : "否（放鬆）",
    `${j.offset_deg.toFixed(2)}°` + (Math.abs(j.offset_deg - j.offset_saved_deg) > 1e-3 ? "（未存檔）" : ""),
    j.temperature === null ? "—" : `${j.temperature} °C`,
    j.voltage === null ? "—" : `${j.voltage.toFixed(1)} V`,
    j.load === null ? "—" : `${j.load.toFixed(1)} %`,
    j.kp === null ? "—" : String(j.kp),
  ];
  const key = [j.name, s.connected, s.estop, j.torque, s.kp_choices.join()].join("|");
  if (key === selectedKey) {
    values.forEach((v, i) => (selectedValues[i].textContent = v));
    return;
  }
  selectedKey = key;
  pane.replaceChildren();
  const head = el("div");
  head.append(el("span", `jid side-${sideOf(j.name)}`, String(j.id)), document.createTextNode(" "), el("strong", undefined, j.zh), el("span", "muted small", `  ${j.name}`));
  pane.appendChild(head);
  const big = el("div", "big-num", values[0]);
  pane.appendChild(big);
  const dl = kv(
    ["目標", "指令（限速後）", "範圍", "出力", "偏移", "溫度", "電壓", "負載", "kp"].map((k, i) => [k, values[i + 1]] as [string, string]),
  );
  pane.appendChild(dl);
  selectedValues = [big, ...Array.from(dl.querySelectorAll<HTMLElement>("dd"))];
  const nudge = el("div", "nudge");
  for (const d of [-10, -5, -1, 1, 5, 10]) {
    const b = el("button", "btn mini", `${d > 0 ? "+" : ""}${d}°`);
    b.type = "button";
    b.disabled = !canMove(j);
    b.addEventListener("click", () => {
      const now = current(j.name);
      const base = now?.target_deg ?? now?.actual_deg ?? 0;
      void send("targets", { targets_deg: { [j.name]: base + d } });
    });
    nudge.appendChild(b);
  }
  pane.appendChild(el("p", "muted small", "微調目標角度："));
  pane.appendChild(nudge);
  const actions = el("div", "row-actions");
  const tq = el("button", "btn", j.torque ? "放鬆這顆" : "這顆出力");
  tq.type = "button";
  tq.disabled = !s.connected || (!!s.estop && !j.torque);
  tq.addEventListener("click", () => void send("torque", { joints: [j.name], on: !current(j.name)?.torque }));
  const kpSel = el("select");
  kpSel.setAttribute("aria-label", "這顆的 kp");
  kpSel.append(new Option("kp…", ""));
  for (const k of s.kp_choices) kpSel.append(new Option(`kp ${k}`, String(k)));
  kpSel.disabled = !s.connected;
  kpSel.addEventListener("change", () => {
    if (kpSel.value) void send("kp", { joints: [j.name], kp: Number(kpSel.value) });
  });
  actions.append(tq, kpSel);
  pane.appendChild(actions);
  if (!s.connected) pane.appendChild(el("p", "note note-warn", "還沒連線匯流排：按上方「連線匯流排」。"));
  else if (!j.torque) pane.appendChild(el("p", "muted small", "這顆沒有出力，可以用手轉，畫面會跟著動。要用網頁控制先按「這顆出力」。"));
}

function renderPoses(s: ConsoleState): void {
  const list = $("#pose-list");
  const key = [s.connected, s.estop, ...s.poses.map((p) => p.key)].join("|");
  if (list.dataset.key === key) return;
  list.dataset.key = key;
  list.replaceChildren();
  for (const p of s.poses) {
    const li = el("li");
    li.appendChild(el("span", undefined, p.label));
    const btns = el("span", "button-grid");
    const apply = el("button", "btn mini", "套用");
    apply.type = "button";
    apply.disabled = !s.connected || !!s.estop;
    apply.addEventListener("click", () => void send("pose_apply", { key: p.key }));
    btns.appendChild(apply);
    if (!p.builtin) {
      const del = el("button", "btn mini", "刪除");
      del.type = "button";
      del.addEventListener("click", () => {
        if (confirm(`刪除姿勢「${p.label}」？`)) void send("pose_delete", { name: p.label });
      });
      btns.appendChild(del);
    }
    li.appendChild(btns);
    list.appendChild(li);
  }
}

function renderOffsets(s: ConsoleState): void {
  const box = $("#offset-table");
  if (!box.childElementCount) {
    for (const j of s.joints) {
      const row = el("div", "offset-row");
      row.dataset.name = j.name;
      const label = el("span");
      label.append(el("span", `jid side-${sideOf(j.name)}`, String(j.id)), document.createTextNode(` ${j.zh}`));
      const ov = el("span", "ov");
      const btns = el("span", "obtns");
      for (const d of [-1, -0.2, 0.2, 1]) {
        const b = el("button", "btn mini", `${d > 0 ? "+" : ""}${d}°`);
        b.type = "button";
        b.addEventListener("click", () => void send("offset", { joint: j.name, delta_deg: d }));
        btns.appendChild(b);
      }
      row.append(label, btns, ov);
      box.appendChild(row);
    }
  }
  for (const j of s.joints) {
    const row = box.querySelector<HTMLElement>(`[data-name="${j.name}"]`);
    const ov = row?.querySelector<HTMLElement>(".ov");
    if (!ov) continue;
    const dirty = Math.abs(j.offset_deg - j.offset_saved_deg) > 1e-3;
    ov.textContent = dirty ? `檔案 ${j.offset_saved_deg.toFixed(2)}° → 目前 ${j.offset_deg.toFixed(2)}°（未存檔）` : `${j.offset_deg.toFixed(2)}°`;
    ov.classList.toggle("dirty", dirty);
  }
  $<HTMLButtonElement>("#btn-offsets-save").disabled = !s.offsets_dirty;
  $("#offset-path").textContent = `設定檔：${s.config_path}`;
}

function renderSensors(s: ConsoleState): void {
  const imu = $("#imu");
  imu.replaceChildren();
  if (!s.imu.ok) imu.appendChild(el("p", "muted small", s.imu.error ?? "沒有資料"));
  else {
    const e = s.imu.euler_deg ?? [];
    const a = s.imu.accel ?? [];
    const g = s.imu.gyro ?? [];
    const mag = a.every((v) => typeof v === "number") ? Math.hypot(...(a as number[])) : null;
    const c = s.imu.calibration ?? [];
    imu.appendChild(
      kv([
        ["航向／橫滾／俯仰", e.map((v) => fmt(v)).join(" / ")],
        ["加速度 (m/s²)", a.map((v) => fmt(v, 2, "")).join(" / ") + (mag === null ? "" : `（合力 ${mag.toFixed(2)}）`)],
        ["角速度 (rad/s)", g.map((v) => fmt(v, 3, "")).join(" / ")],
        ["校準 系統/陀螺/加速/磁", c.length ? c.join(" / ") + "（3 = 完成）" : "—"],
      ]),
    );
    if (s.imu.mock) imu.appendChild(el("p", "note note-warn", "模擬資料（mock），不是真的 IMU。"));
    imu.appendChild(el("p", "muted small", "BNO055 還沒裝進機身、也還沒跑上游的校準，數值只供參考。"));
  }
  const feet = $("#feet");
  feet.replaceChildren();
  if (!s.feet.ok) feet.appendChild(el("p", "muted small", s.feet.error ?? "沒有資料"));
  else {
    const box = el("div", "feet");
    for (const [label, on] of [["左腳（GPIO 22）", s.feet.left], ["右腳（GPIO 27）", s.feet.right]] as const) {
      box.appendChild(el("div", "foot" + (on ? " on" : ""), `${label}：${on ? "著地" : "懸空"}`));
    }
    feet.appendChild(box);
    feet.appendChild(el("p", "muted small", "開關接 GND 才算著地。感測器還沒接時永遠顯示「懸空」。"));
  }
  const pi = $("#pi");
  pi.replaceChildren();
  const p = s.pi;
  const up = p.uptime_s ?? null;
  pi.appendChild(
    kv([
      ["電源 get_throttled", p.throttled ? `${p.throttled}${p.throttled_flags?.length ? "：" + p.throttled_flags.join("、") : "（正常）"}` : "—"],
      ["CPU 溫度", fmt(p.cpu_temp_c, 1, " °C")],
      ["負載（1/5/15 分）", p.load ? p.load.join(" / ") : "—"],
      ["記憶體", p.mem_used_mb != null && p.mem_total_mb != null ? `${p.mem_used_mb} / ${p.mem_total_mb} MB` : "—"],
      ["開機時間", up === null ? "—" : `${Math.floor(up / 3600)} 小時 ${Math.floor((up % 3600) / 60)} 分`],
    ]),
  );
}

// ---------------------------------------------------------------- 電力
const BATT_LO = 6.0; // 電力條的左端：自動停止門檻
const BATT_HI = 8.4; // 右端：2S 滿電
let powerHistory: HistorySample[] = [];
let historyAt = 0;

function pct(v: number): string {
  return `${Math.min(100, Math.max(0, ((v - BATT_LO) / (BATT_HI - BATT_LO)) * 100)).toFixed(1)}%`;
}

function renderPower(s: ConsoleState): void {
  const p = s.power;
  const batt = $("#battery");
  batt.replaceChildren();
  if (!p.available || p.battery_v === undefined) {
    batt.appendChild(el("p", "muted small", "還沒連線匯流排，沒有舵機回報的電壓與電流。按上方「連線匯流排」（只讀取，不會改扭力）。"));
  } else {
    batt.appendChild(el("div", "muted small", "電池電壓（由舵機回報推估）"));
    batt.appendChild(el("div", "big-num", `${p.battery_v.toFixed(1)} V`));
    batt.appendChild(el("div", "muted small", `每顆電芯約 ${p.cell_v!.toFixed(2)} V · 舵機最低 ${p.servo_v_min!.toFixed(1)} V／最高 ${p.servo_v_max!.toFixed(1)} V`));
    const bar = el("div", "vbar");
    bar.style.setProperty("--stop", pct(s.limits.volt_stop_v));
    bar.style.setProperty("--warn", pct(s.limits.volt_warn_v));
    const needle = el("div", "needle");
    needle.style.left = pct(p.battery_v);
    bar.appendChild(needle);
    for (const [v, label] of [
      [BATT_LO, `${BATT_LO} V 停止`],
      [s.limits.volt_warn_v, `${s.limits.volt_warn_v} V 警告`],
      [BATT_HI, `${BATT_HI} V 滿電`],
    ] as const) {
      const t = el("span", "tick", label);
      t.style.left = pct(v);
      if (v === BATT_HI) t.style.transform = "translateX(-100%)";
      if (v === BATT_LO) t.style.transform = "none";
      bar.appendChild(t);
    }
    batt.appendChild(bar);
  }
  const totals = $("#power-totals");
  totals.replaceChildren(
    kv([
      ["舵機總電流", p.available && p.current_a != null ? `${p.current_a.toFixed(2)} A` : "—"],
      ["舵機總功率（估計）", p.available && p.power_w != null ? `${p.power_w.toFixed(1)} W` : "—"],
      ["舵機最高溫度", p.available && p.temp_max_c != null ? `${p.temp_max_c} °C` : "—"],
      ["出力中", p.available ? `${p.torque_on}／14` : "—"],
      ["回報異常", p.available ? (p.flagged?.length ? p.flagged.map((i) => `ID ${i}`).join("、") : "沒有") : "—"],
    ]),
  );

  const table = el("table", "ptable");
  const head = el("tr");
  for (const h of ["舵機", "V", "mA", "W", "°C", "負載%", "旗標"]) head.appendChild(el("th", undefined, h));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const j of s.joints) {
    const tr = el("tr");
    const w = j.voltage !== null && j.current_ma !== null ? (j.voltage * j.current_ma) / 1000 : null;
    tr.append(
      el("td", undefined, `${j.id} ${j.zh}`),
      el("td", undefined, j.voltage === null ? "—" : j.voltage.toFixed(1)),
      el("td", undefined, j.current_ma === null ? "—" : j.current_ma.toFixed(0)),
      el("td", undefined, w === null ? "—" : w.toFixed(2)),
      el("td", undefined, j.temperature === null ? "—" : String(j.temperature)),
      el("td", undefined, j.load === null ? "—" : j.load.toFixed(1)),
      el("td", j.status.length ? "flag" : undefined, j.status.length ? j.status.join("、") : "—"),
    );
    body.appendChild(tr);
  }
  table.appendChild(body);
  if (p.available) {
    const foot = el("tr");
    foot.append(
      el("td", undefined, "合計"),
      el("td", undefined, ""),
      el("td", undefined, p.current_a == null ? "—" : (p.current_a * 1000).toFixed(0)),
      el("td", undefined, p.power_w == null ? "—" : p.power_w.toFixed(2)),
      el("td", undefined, ""),
      el("td", undefined, ""),
      el("td", undefined, ""),
    );
    table.appendChild(el("tfoot")).appendChild(foot);
  }
  $("#servo-power").replaceChildren(table);

  const pi = s.pi;
  const v = pi.volts ?? {};
  const vs = (k: string) => (v[k] == null ? "—" : `${v[k]!.toFixed(3)} V`);
  $("#pi-power").replaceChildren(
    kv([
      ["get_throttled", pi.throttled ? `${pi.throttled}${pi.throttled_flags?.length ? "：" + pi.throttled_flags.join("、") : "（正常）"}` : "—"],
      ["5 V 輸入", "Pi 4 量不到，只能看上面的電壓不足旗標"],
      ["核心電壓", vs("core")],
      ["SDRAM 電壓 c／i／p", `${vs("sdram_c")} / ${vs("sdram_i")} / ${vs("sdram_p")}`],
      ["ARM 時脈", pi.arm_mhz == null ? "—" : `${pi.arm_mhz} MHz`],
      ["CPU 溫度", fmt(pi.cpu_temp_c, 1, " °C")],
    ]),
  );
  drawPowerCharts(s);
}

function drawPowerCharts(s: ConsoleState): void {
  if ($('[data-pane="power"]').hidden) return;
  const t = powerHistory.map((h) => h.t);
  drawChart($<HTMLCanvasElement>("#chart-volt"), t, [{ label: "電池", values: powerHistory.map((h) => h.battery_v), color: "--accent", band: { lo: powerHistory.map((h) => h.v_min), hi: powerHistory.map((h) => h.v_max) } }], {
    unit: "V",
    digits: 1,
    minSpan: 0.6,
    marks: [
      { value: s.limits.volt_warn_v, color: "--warn-ink", label: "警告" },
      { value: s.limits.volt_stop_v, color: "--danger", label: "停止" },
    ],
  });
  drawChart($<HTMLCanvasElement>("#chart-current"), t, [{ label: "電流", values: powerHistory.map((h) => h.current_a), color: "--current" }], { unit: "A", digits: 2, minSpan: 0.2 });
  drawChart(
    $<HTMLCanvasElement>("#chart-temp"),
    t,
    [
      { label: "舵機最高", values: powerHistory.map((h) => h.temp_max_c), color: "--current" },
      { label: "Pi CPU", values: powerHistory.map((h) => h.cpu_temp_c), color: "--ok" },
    ],
    { unit: "°C", digits: 0, minSpan: 10, marks: [{ value: s.limits.temp_warn_c, color: "--warn-ink", label: "舵機警告" }] },
  );
  const undervolt = powerHistory.filter((h) => h.throttled !== null && (h.throttled & 0x1) !== 0).length;
  const first = powerHistory[0];
  $("#history-note").textContent = powerHistory.length
    ? `歷史 ${powerHistory.length} 筆（每秒一筆，從 ${new Date(first.t * 1000).toLocaleTimeString("zh-TW", { hour12: false })} 起）；Pi 電壓不足的秒數：${undervolt}`
    : "還沒有歷史資料";
}

async function pollHistory(): Promise<void> {
  if ($('[data-pane="power"]').hidden || Date.now() - historyAt < 2000) return;
  historyAt = Date.now();
  try {
    const res = await request<{ samples: HistorySample[] }>("/api/history");
    powerHistory = res.samples;
    if (state) drawPowerCharts(state);
  } catch {
    /* 下次再試 */
  }
}

function renderSounds(s: ConsoleState): void {
  const box = $("#sound-list");
  const key = s.sounds.join(",");
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.replaceChildren();
  if (!s.sounds.length) box.appendChild(el("p", "muted small", "找不到音效檔"));
  for (const name of s.sounds) {
    const b = el("button", "btn", `▶ ${name}`);
    b.type = "button";
    b.addEventListener("click", () => void send("sound", { name }));
    box.appendChild(b);
  }
}

function renderLog(s: ConsoleState): void {
  const list = $("#log-list");
  const key = s.events.length ? `${s.events.length}:${s.events[s.events.length - 1].t}` : "0";
  if (list.dataset.key === key) return;
  list.dataset.key = key;
  list.replaceChildren();
  for (const e of [...s.events].reverse()) {
    const li = el("li", e.level);
    const time = el("time", undefined, new Date(e.t * 1000).toLocaleTimeString("zh-TW", { hour12: false }));
    li.append(time, document.createTextNode(e.message));
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------- 上方列
function renderTop(s: ConsoleState): void {
  const chip = $("#conn-chip");
  chip.textContent = s.connected ? "已連線匯流排" : "未連線（不碰硬體）";
  chip.className = "chip " + (s.connected ? "ok" : "warn");
  $("#mode-chip").hidden = !s.mock;
  $("#auth-chip").hidden = s.auth;
  const btn = $<HTMLButtonElement>("#btn-connect");
  btn.textContent = s.connected ? "釋放硬體" : "連線匯流排";
  for (const id of ["#btn-torque-on", "#btn-torque-off", "#btn-hold", "#kp-all"]) $<HTMLButtonElement>(id).disabled = !s.connected;
  $<HTMLButtonElement>("#btn-torque-on").disabled = !s.connected || !!s.estop;
  const speed = $<HTMLSelectElement>("#speed");
  if (speed.options.length !== s.speed_choices.length) {
    speed.replaceChildren(...s.speed_choices.map((v) => new Option(`${v}°/s`, String(v))));
  }
  if (document.activeElement !== speed) speed.value = String(s.speed_deg);
  const kpAll = $<HTMLSelectElement>("#kp-all");
  if (kpAll.options.length === 1) for (const k of s.kp_choices) kpAll.append(new Option(String(k), String(k)));
  const bar = $("#estop-bar");
  bar.hidden = !s.estop;
  $("#estop-text").textContent = s.estop ? `緊急停止中：${s.estop}。全部扭力已關。` : "";
  const alarms = $("#alarm-bar");
  const warn = s.alarms.filter((a) => a.level === "warn");
  alarms.hidden = !warn.length;
  alarms.textContent = warn.map((a) => `⚠ ${a.message}`).join("　");
}

function render(s: ConsoleState): void {
  if (!rows.size) buildRows(s.joints);
  renderTop(s);
  updateRows(s);
  renderSelected(s);
  renderPoses(s);
  renderOffsets(s);
  renderSensors(s);
  renderPower(s);
  renderSounds(s);
  renderLog(s);
  if (viewer) {
    const angles: Record<string, number | null> = {};
    for (const j of s.joints) {
      const deg = show3d === "target" ? (j.target_deg ?? j.actual_deg) : j.actual_deg;
      angles[j.name] = deg === null ? null : deg * RAD;
    }
    viewer.setAngles(angles);
    viewer.setLimp(s.joints.filter((j) => j.torque !== true).map((j) => j.id));
    viewer.setSelected(s.joints.find((j) => j.name === selected)?.id ?? null);
  }
}

let polling = false;
let failCount = 0;
async function poll(): Promise<void> {
  if (polling) return;
  polling = true;
  try {
    state = await request<ConsoleState>("/api/state");
    failCount = 0;
    render(state);
    void pollHistory();
  } catch (err) {
    failCount++;
    if (err instanceof HttpError && err.status === 401) askToken();
    else if (failCount >= 3) {
      const chip = $("#conn-chip");
      chip.textContent = "連不到 Pi";
      chip.className = "chip bad";
    }
  } finally {
    polling = false;
  }
}

// ---------------------------------------------------------------- 啟動
function bindControls(): void {
  $("#btn-connect").addEventListener("click", () => void send(state?.connected ? "release" : "connect"));
  $("#btn-torque-on").addEventListener("click", () => void send("torque", { joints: "all", on: true }));
  $("#btn-torque-off").addEventListener("click", () => {
    if (confirm("全部放鬆？懸空或站著的鴨子會垮下來，請先扶好。")) void send("torque", { joints: "all", on: false });
  });
  $("#btn-hold").addEventListener("click", () => void send("hold"));
  $("#btn-estop").addEventListener("click", () => void send("estop"));
  $("#btn-reset-estop").addEventListener("click", () => void send("reset_estop"));
  $<HTMLSelectElement>("#speed").addEventListener("change", (e) => void send("speed", { deg_s: Number((e.target as HTMLSelectElement).value) }));
  const kpAll = $<HTMLSelectElement>("#kp-all");
  kpAll.addEventListener("change", () => {
    if (kpAll.value) void send("kp", { joints: "all", kp: Number(kpAll.value) }).then(() => (kpAll.value = ""));
  });
  $("#btn-offsets-save").addEventListener("click", () => void send("offsets_save").then((r) => r && toast(`已存檔${r.backup ? `，備份 ${r.backup}` : ""}`)));
  $("#btn-offsets-reload").addEventListener("click", () => void send("offsets_reload"));
  $<HTMLFormElement>("#pose-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $<HTMLInputElement>("#pose-name");
    void send("pose_save", { name: input.value }).then((r) => r && (input.value = ""));
  });
  document.querySelectorAll<HTMLButtonElement>(".tabbar [data-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      selectTab(b.dataset.tab!);
      historyAt = 0;
      void pollHistory();
      if (state) drawPowerCharts(state);
    }),
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      void send("estop");
    }
  });
  $<HTMLFormElement>("#token-form").addEventListener("submit", () => {
    token = $<HTMLInputElement>("#token-input").value.trim();
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* 存不了就只用這次 */
    }
    void poll();
  });
  const show = (mode: "actual" | "target") => {
    show3d = mode;
    $("#show-actual").setAttribute("aria-pressed", String(mode === "actual"));
    $("#show-target").setAttribute("aria-pressed", String(mode === "target"));
    if (state) render(state);
  };
  $("#show-actual").addEventListener("click", () => show("actual"));
  $("#show-target").addEventListener("click", () => show("target"));
}

async function main(): Promise<void> {
  bindControls();
  const bundle = readBundle();
  $("#build-info").textContent = `控制台建置 ${bundle.build.built_at} · commit ${bundle.build.git_commit} · three.js ${bundle.build.three_version}`;
  void poll();
  window.setInterval(() => void poll(), POLL_MS);
  try {
    const meshBin = await readMeshBin(bundle.scene.summary.meshes_bin_bytes);
    viewer = new PoseViewer($("#stage-canvas"), bundle.scene, meshBin);
    viewer.onPickServo = (id) => {
      const j = state?.joints.find((x) => x.id === id);
      if (j) select(j.name);
    };
    $<HTMLInputElement>("#xray").addEventListener("change", (e) => viewer?.setXray((e.target as HTMLInputElement).checked));
    $<HTMLInputElement>("#labels").addEventListener("change", (e) => viewer?.setLabels((e.target as HTMLInputElement).checked));
    document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((b) => b.addEventListener("click", () => viewer?.setView(b.dataset.view as CameraView)));
    if (state) render(state);
  } catch (err) {
    const f = $("#fatal");
    f.hidden = false;
    f.textContent = `3D 模型載入失敗：${err instanceof Error ? err.message : String(err)}（控制功能仍可使用）`;
  } finally {
    document.body.classList.remove("is-loading");
  }
}

void main();
