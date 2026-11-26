// 頁面互動：步驟面板、零件清單與搜尋、零件資訊、檢視控制。
import { readBundle, readMeshBin } from "./data";
import type { Part, Servo, Step } from "./types";
import { type CameraView, type PartState, Viewer } from "./viewer";

const JOINT_ZH: Record<string, string> = {
  hip_yaw: "髖偏航",
  hip_roll: "髖側擺",
  hip_pitch: "髖俯仰",
  knee: "膝",
  ankle: "踝",
  neck_pitch: "頸俯仰",
  head_pitch: "頭俯仰",
  head_yaw: "頭偏航",
  head_roll: "頭側擺",
};
const SIDE_ZH = { left: "左", right: "右", center: "中" } as const;
const KIND_ZH: Record<Part["kind"], string> = {
  printed: "列印件",
  servo_part: "舵機",
  electronics: "電子",
  power: "電源",
  bearing: "軸承",
  other: "其他",
};
const KIND_ORDER: Part["kind"][] = ["servo_part", "printed", "electronics", "power", "bearing", "other"];
const STORE_KEY = "nous-duck-viewer:v1:done";

interface Item {
  key: string;
  kind: Part["kind"];
  label: string;
  sub: string;
  ids: string[];
  servo?: Servo;
  sample: Part;
  search: string;
}

const $ = <T extends HTMLElement = HTMLElement>(sel: string): T => {
  const el = document.querySelector<T>(sel);
  if (!el) throw new Error(`頁面缺少元素 ${sel}`);
  return el;
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** 把 `code` 片段轉成 <code>，其他文字一律當純文字。 */
function richText(parent: HTMLElement, text: string): void {
  text.split(/(`[^`]+`)/).forEach((chunk) => {
    if (chunk.startsWith("`") && chunk.endsWith("`") && chunk.length > 2) parent.appendChild(el("code", undefined, chunk.slice(1, -1)));
    else if (chunk) parent.appendChild(document.createTextNode(chunk));
  });
}

function jointZh(joint: string): string {
  const side = joint.startsWith("left_") ? "左" : joint.startsWith("right_") ? "右" : "";
  const base = joint.replace(/^(left|right)_/, "");
  return side + (JOINT_ZH[base] ?? base);
}

function loadDone(): Set<string> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function saveDone(done: Set<string>): boolean {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify([...done]));
    return true;
  } catch {
    return false;
  }
}

async function main(): Promise<void> {
  const bundle = readBundle();
  const { scene, steps, build } = bundle;
  const parts = new Map(scene.parts.map((p) => [p.id, p]));
  const servoOfPart = new Map<string, Servo>();
  for (const s of scene.servos) for (const id of s.parts) servoOfPart.set(id, s);
  const stepOfPart = new Map<string, number>();
  steps.steps.forEach((s, i) => s.adds.forEach((id) => stepOfPart.set(id, i)));

  $("#build-info").textContent = `資料：上游 CAD（robot.xml sha256 ${Object.values(scene.sources)[0].slice(0, 12)}…）· 建置 ${build.built_at} · commit ${build.git_commit} · three.js ${build.three_version}`;
  $("#stat-height").textContent = `${scene.summary.height_mm} mm`;
  $("#stat-parts").textContent = String(scene.summary.part_instances);
  $("#stat-printed").textContent = `${scene.summary.printed_pieces} 件／${scene.summary.print_stl_types} 種`;
  $("#stat-servos").textContent = String(scene.summary.servos);

  const meshBin = await readMeshBin(scene.summary.meshes_bin_bytes);
  const viewer = new Viewer($("#stage-canvas"), scene, meshBin);
  document.body.classList.remove("is-loading");
  (window as unknown as { duckViewer: Viewer }).duckViewer = viewer;

  // ---------- 狀態 ----------
  const state = {
    mode: "steps" as "steps" | "all",
    step: 0,
    future: "hidden" as "hidden" | "ghost",
    selection: [] as string[],
    selectedKey: null as string | null,
    isolate: false,
    done: loadDone(),
  };

  // ---------- 零件清單 ----------
  const items: Item[] = [];
  for (const s of scene.servos) {
    const sample = parts.get(s.parts[0])!;
    const j = jointZh(s.joint);
    items.push({
      key: `servo:${s.id}`,
      kind: "servo_part",
      label: `ID ${s.id}　${j}舵機`,
      sub: `STS3215 · ${s.joint}`,
      ids: s.parts,
      servo: s,
      sample,
      search: `id ${s.id} id${s.id} ${s.id} ${j} ${s.joint} sts3215 舵機 servo`.toLowerCase(),
    });
  }
  const groups = new Map<string, Part[]>();
  for (const p of scene.parts) {
    if (p.kind === "servo_part") continue;
    const k = `${p.mesh}|${p.name_zh}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(p);
  }
  for (const [k, ps] of groups) {
    const p = ps[0];
    items.push({
      key: `mesh:${k}`,
      kind: p.kind,
      label: p.name_zh,
      sub: `${p.name_en}${ps.length > 1 ? ` · ×${ps.length}` : ""}`,
      ids: ps.map((x) => x.id),
      sample: p,
      search: `${p.name_zh} ${p.name_en} ${p.mesh} ${p.print_stl ?? ""} ${KIND_ZH[p.kind]}`.toLowerCase(),
    });
  }
  items.sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || (a.servo?.id ?? 0) - (b.servo?.id ?? 0));
  const itemByKey = new Map(items.map((i) => [i.key, i]));
  const itemOfPart = (id: string): Item => {
    const s = servoOfPart.get(id);
    if (s) return itemByKey.get(`servo:${s.id}`)!;
    const p = parts.get(id)!;
    return itemByKey.get(`mesh:${p.mesh}|${p.name_zh}`)!;
  };

  const list = $("#part-list");
  const search = $<HTMLInputElement>("#part-search");
  function renderList(): void {
    const q = search.value.trim().toLowerCase().replace(/^id\s*/, "id ");
    const words = q.split(/\s+/).filter(Boolean);
    list.replaceChildren();
    let lastKind: string | null = null;
    let shown = 0;
    for (const it of items) {
      if (words.length && !words.every((w) => it.search.includes(w) || it.label.toLowerCase().includes(w))) continue;
      if (it.kind !== lastKind) {
        lastKind = it.kind;
        list.appendChild(el("li", "part-group", KIND_ZH[it.kind]));
      }
      const li = el("li");
      const btn = el("button", "part-row");
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(state.selectedKey === it.key));
      const sw = el("span", "swatch");
      sw.style.background = it.sample.color;
      const text = el("span", "part-text");
      text.append(el("span", "part-name", it.label), el("span", "part-sub", it.sub));
      btn.append(sw, text);
      if (it.sample.placement === "print_frame") btn.appendChild(el("span", "tag tag-warn", "推得位置"));
      else if (it.sample.identification) btn.appendChild(el("span", "tag", "推定"));
      btn.addEventListener("click", () => select(it.key, it.ids, true));
      li.appendChild(btn);
      list.appendChild(li);
      shown++;
    }
    if (!shown) list.appendChild(el("li", "empty", "沒有符合的零件。試試「ID 24」、「膝」或「foot_top」。"));
  }
  search.addEventListener("input", renderList);

  // ---------- 零件資訊 ----------
  const info = $("#part-info");
  function renderInfo(): void {
    info.replaceChildren();
    const it = state.selectedKey ? itemByKey.get(state.selectedKey) : null;
    if (!it) {
      info.appendChild(el("p", "muted", "點 3D 模型或清單裡的零件，這裡會顯示它是什麼、裝在哪一步。"));
      $("#isolate-btn").setAttribute("disabled", "");
      return;
    }
    $("#isolate-btn").removeAttribute("disabled");
    const p = it.sample;
    info.appendChild(el("h3", undefined, it.label));
    info.appendChild(el("p", "muted", it.servo ? "STS3215 舵機" : p.name_en));
    const dl = el("dl");
    const row = (k: string, v: string) => dl.append(el("dt", undefined, k), el("dd", undefined, v));
    if (it.servo) {
      row("舵機 ID", String(it.servo.id));
      row("關節", `${jointZh(it.servo.joint)}（${it.servo.joint}）`);
      row("位置", `鴨子的${SIDE_ZH[it.servo.side]}側`);
    } else {
      row("類別", KIND_ZH[p.kind]);
      row("數量", `${it.ids.length} 件（CAD 中）`);
      if (p.print_stl) row("列印檔", `print/${p.print_stl}`);
    }
    row("所在 body", p.body);
    info.appendChild(dl);
    if (p.placement === "print_frame") {
      info.appendChild(el("p", "note note-warn", "CAD 裡沒有這件的擺放位置。畫面上的位置是借頭殼座標推得的，只供參考。"));
    }
    if (p.identification) info.appendChild(el("p", "note", `推定依據：${p.identification}`));
    if (p.mesh === "antenna") info.appendChild(el("p", "note note-warn", "上游列印清單與 BOM 都沒有這個零件，材質與取得方式未說明。"));
    const stepIdx = [...new Set(it.ids.map((id) => stepOfPart.get(id)).filter((x): x is number => x !== undefined))];
    if (stepIdx.length) {
      const p2 = el("p", "step-links", "裝在：");
      for (const i of stepIdx) {
        const b = el("button", "link-btn", `第 ${i + 1} 步 ${steps.steps[i].title}`);
        b.type = "button";
        b.addEventListener("click", () => goStep(i));
        p2.appendChild(b);
      }
      info.appendChild(p2);
    }
  }

  function select(key: string | null, ids: string[], frame: boolean): void {
    state.selectedKey = key;
    state.selection = ids;
    if (!key) state.isolate = false;
    viewer.setSelection(state.selection, state.isolate);
    $("#isolate-btn").setAttribute("aria-pressed", String(state.isolate));
    renderList();
    renderInfo();
    if (frame && ids.length) viewer.frameParts(ids);
    if (key && window.matchMedia("(max-width: 900px)").matches) showTab("parts");
  }

  viewer.onPick = (id) => {
    if (!id) return select(null, [], false);
    const it = itemOfPart(id);
    select(it.key, it.servo ? it.servo.parts : [id], false);
  };

  $("#isolate-btn").addEventListener("click", () => {
    state.isolate = !state.isolate;
    viewer.setSelection(state.selection, state.isolate);
    $("#isolate-btn").setAttribute("aria-pressed", String(state.isolate));
  });
  $("#clear-btn").addEventListener("click", () => {
    search.value = "";
    select(null, [], false);
  });

  // ---------- 步驟 ----------
  const stepList = $("#step-list");
  const stepDetail = $("#step-detail");

  function computeStates(): Map<string, PartState> {
    const m = new Map<string, PartState>();
    if (state.mode === "all") return m;
    const cur = steps.steps[state.step];
    if (cur.show_all) {
      for (const p of scene.parts) m.set(p.id, "done");
      for (const id of cur.focus) m.set(id, "focus");
      return m;
    }
    steps.steps.forEach((s, i) => {
      const st: PartState = i < state.step ? "done" : i === state.step ? "current" : state.future;
      for (const id of s.adds) m.set(id, st);
    });
    for (const id of cur.focus) m.set(id, "focus");
    return m;
  }

  function renderStepList(): void {
    stepList.replaceChildren();
    steps.steps.forEach((s, i) => {
      const li = el("li");
      const b = el("button", "step-row");
      b.type = "button";
      b.setAttribute("aria-current", String(state.mode === "steps" && i === state.step));
      const n = el("span", "step-num", String(i + 1));
      if (state.done.has(s.id)) n.classList.add("is-done");
      b.append(n, el("span", "step-title", s.title));
      if (s.optional) b.appendChild(el("span", "tag", "選配"));
      b.addEventListener("click", () => goStep(i));
      li.appendChild(b);
      stepList.appendChild(li);
    });
    const doneCount = steps.steps.filter((s) => state.done.has(s.id)).length;
    $("#progress").textContent = `已完成 ${doneCount}／${steps.steps.length} 步`;
  }

  function sourceHref(s: { path?: string; url?: string }): string {
    return s.url ?? `${build.repo_url}/blob/v2/${s.path}`;
  }

  function renderStepDetail(): void {
    stepDetail.replaceChildren();
    if (state.mode === "all") {
      stepDetail.appendChild(el("p", "muted", "整機檢視：顯示全部零件。點「依步驟」回到組裝步驟。"));
      return;
    }
    const s: Step = steps.steps[state.step];
    const head = el("div", "step-head");
    head.append(el("span", "step-kicker", `第 ${state.step + 1} 步／共 ${steps.steps.length} 步${s.optional ? " · 選配" : ""}`));
    head.append(el("h2", undefined, s.title));
    stepDetail.appendChild(head);
    stepDetail.appendChild(el("p", "step-summary", s.summary));
    if (s.warnings.length) {
      const w = el("ul", "warnings");
      for (const t of s.warnings) {
        const li = el("li");
        richText(li, t);
        w.appendChild(li);
      }
      stepDetail.appendChild(w);
    }
    const ol = el("ol", "tasks");
    for (const t of s.tasks) {
      const li = el("li");
      richText(li, t);
      ol.appendChild(li);
    }
    stepDetail.appendChild(ol);
    const chk = el("p", "check");
    chk.append(el("strong", undefined, "驗收："));
    richText(chk, s.check);
    stepDetail.appendChild(chk);

    const legend = el("p", "legend");
    if (s.adds.length) legend.append(el("span", "dot dot-current"), `本步裝上 ${s.adds.length} 個網格零件`);
    if (s.focus.length) legend.append(el("span", "dot dot-focus"), `要注意的零件 ${s.focus.length} 個`);
    if (!s.adds.length && !s.focus.length) legend.append("這一步沒有新增 3D 零件。");
    stepDetail.appendChild(legend);

    if (s.sources.length) {
      const src = el("p", "sources", "參考：");
      for (const x of s.sources) {
        const a = el("a", undefined, x.label);
        a.href = sourceHref(x);
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        src.appendChild(a);
      }
      stepDetail.appendChild(src);
    }

    const done = el("label", "done-toggle");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = state.done.has(s.id);
    cb.addEventListener("change", () => {
      if (cb.checked) state.done.add(s.id);
      else state.done.delete(s.id);
      const ok = saveDone(state.done);
      $("#store-note").hidden = ok;
      renderStepList();
    });
    done.append(cb, " 這一步完成了");
    stepDetail.appendChild(done);
    $<HTMLButtonElement>("#prev-step").disabled = state.step === 0;
    $<HTMLButtonElement>("#next-step").disabled = state.step === steps.steps.length - 1;
  }

  function applyStates(): void {
    viewer.setStates(computeStates());
  }

  function goStep(i: number): void {
    state.mode = "steps";
    state.step = Math.max(0, Math.min(steps.steps.length - 1, i));
    syncModeButtons();
    applyStates();
    renderStepList();
    renderStepDetail();
    const s = steps.steps[state.step];
    const target = s.show_all ? [] : s.adds.length ? s.adds : s.focus;
    if (target.length) viewer.frameParts(target);
    else viewer.setView("iso");
    if (window.matchMedia("(max-width: 900px)").matches) showTab("steps");
  }

  $("#prev-step").addEventListener("click", () => goStep(state.step - 1));
  $("#next-step").addEventListener("click", () => goStep(state.step + 1));

  function syncModeButtons(): void {
    $("#mode-steps").setAttribute("aria-pressed", String(state.mode === "steps"));
    $("#mode-all").setAttribute("aria-pressed", String(state.mode === "all"));
    $("#step-nav").hidden = state.mode !== "steps";
  }
  $("#mode-steps").addEventListener("click", () => goStep(state.step));
  $("#mode-all").addEventListener("click", () => {
    state.mode = "all";
    syncModeButtons();
    applyStates();
    renderStepList();
    renderStepDetail();
    viewer.setView("iso");
  });

  // ---------- 檢視控制 ----------
  const explode = $<HTMLInputElement>("#explode");
  explode.addEventListener("input", () => {
    viewer.setExplode(Number(explode.value) / 100);
    $("#explode-value").textContent = `${explode.value}%`;
  });
  $<HTMLInputElement>("#xray").addEventListener("change", (e) => viewer.setXray((e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("#labels").addEventListener("change", (e) =>
    viewer.setServoLabels((e.target as HTMLInputElement).checked),
  );
  $<HTMLInputElement>("#ghost").addEventListener("change", (e) => {
    state.future = (e.target as HTMLInputElement).checked ? "ghost" : "hidden";
    applyStates();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((b) =>
    b.addEventListener("click", () => viewer.setView(b.dataset.view as CameraView)),
  );

  // ---------- 手機分頁 ----------
  function showTab(tab: "steps" | "parts"): void {
    document.body.dataset.tab = tab;
    document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.tab === tab)),
    );
  }
  document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((b) =>
    b.addEventListener("click", () => showTab(b.dataset.tab as "steps" | "parts")),
  );
  showTab("steps");

  document.addEventListener("keydown", (e) => {
    if ((e.target as HTMLElement).closest("input, textarea")) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") goStep(state.step + 1);
    else if (e.key === "ArrowLeft" || e.key === "PageUp") goStep(state.step - 1);
    else if (e.key === "Escape") select(null, [], false);
  });

  renderList();
  renderInfo();
  goStep(0);
  viewer.setView("iso", false);
  document.body.dataset.ready = "true";
}

main().catch((err: unknown) => {
  console.error(err);
  document.body.classList.remove("is-loading");
  document.body.dataset.ready = "error";
  const box = document.getElementById("fatal");
  if (box) {
    box.hidden = false;
    box.textContent = `無法載入檢視器：${err instanceof Error ? err.message : String(err)}`;
  }
});
