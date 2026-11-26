// 簡單的時間序列折線圖（canvas，不用圖表函式庫）：電力頁的電池電壓、電流、溫度趨勢。
export interface Series {
  label: string;
  values: (number | null)[];
  color: string; // CSS 變數名稱（例如 --accent）或顏色
  band?: { lo: (number | null)[]; hi: (number | null)[] }; // 範圍帶（例如舵機電壓最低～最高）
}

export interface ChartOptions {
  unit: string;
  digits: number;
  minSpan: number; // y 軸最小跨度，避免雜訊被放大成大起伏
  marks?: { value: number; color: string; label: string }[]; // 門檻線
}

function cssColor(el: Element, c: string): string {
  return c.startsWith("--") ? getComputedStyle(el).getPropertyValue(c).trim() || "#888" : c;
}

export function drawChart(canvas: HTMLCanvasElement, times: number[], series: Series[], opt: ChartOptions): void {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const ink = cssColor(canvas, "--muted");
  const line = cssColor(canvas, "--line");
  ctx.font = "11px system-ui, sans-serif";

  const all: number[] = [];
  for (const s of series) {
    for (const v of s.values) if (v !== null) all.push(v);
    for (const v of [...(s.band?.lo ?? []), ...(s.band?.hi ?? [])]) if (v !== null) all.push(v);
  }
  for (const m of opt.marks ?? []) all.push(m.value);
  const padL = 40;
  const padR = 8;
  const padT = 8;
  const padB = 16;
  const pw = w - padL - padR;
  const ph = h - padT - padB;
  if (!all.length || times.length < 2) {
    ctx.fillStyle = ink;
    ctx.fillText("還沒有資料（要連線匯流排）", padL, padT + ph / 2);
    return;
  }
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < opt.minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - opt.minSpan / 2;
    hi = mid + opt.minSpan / 2;
  }
  if (lo < 0 && Math.min(...all) >= 0) {
    // 電流、溫度這類不會是負的：y 軸從 0 開始
    hi -= lo;
    lo = 0;
  }
  const t0 = times[0];
  const t1 = times[times.length - 1];
  const x = (t: number) => padL + ((t - t0) / Math.max(t1 - t0, 1)) * pw;
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * ph;

  // 格線與 y 軸
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  ctx.fillStyle = ink;
  for (const v of [lo, (lo + hi) / 2, hi]) {
    ctx.beginPath();
    ctx.moveTo(padL, y(v));
    ctx.lineTo(w - padR, y(v));
    ctx.stroke();
    ctx.fillText(v.toFixed(opt.digits), 2, y(v) + 4);
  }
  const minutes = Math.round((t1 - t0) / 60);
  ctx.fillText(minutes >= 1 ? `${minutes} 分鐘前` : `${Math.round(t1 - t0)} 秒前`, padL, h - 3);
  ctx.textAlign = "right";
  ctx.fillText("現在", w - padR, h - 3);
  ctx.textAlign = "left";

  for (const m of opt.marks ?? []) {
    if (m.value < lo || m.value > hi) continue;
    ctx.strokeStyle = cssColor(canvas, m.color);
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, y(m.value));
    ctx.lineTo(w - padR, y(m.value));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = cssColor(canvas, m.color);
    ctx.fillText(m.label, padL + 4, y(m.value) - 3);
  }

  for (const s of series) {
    const color = cssColor(canvas, s.color);
    if (s.band) {
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.18;
      ctx.beginPath();
      let started = false;
      const pts: [number, number][] = [];
      times.forEach((t, i) => {
        const a = s.band!.lo[i];
        const b = s.band!.hi[i];
        if (a === null || b === null) return;
        pts.push([x(t), y(b)]);
      });
      for (const [px, py] of pts) {
        if (!started) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
        started = true;
      }
      for (let i = times.length - 1; i >= 0; i--) {
        const a = s.band.lo[i];
        if (a === null || s.band.hi[i] === null) continue;
        ctx.lineTo(x(times[i]), y(a));
      }
      if (started) ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let pen = false;
    times.forEach((t, i) => {
      const v = s.values[i];
      if (v === null) {
        pen = false;
        return;
      }
      if (!pen) ctx.moveTo(x(t), y(v));
      else ctx.lineTo(x(t), y(v));
      pen = true;
    });
    ctx.stroke();
  }
}
