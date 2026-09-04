/* ============================================================
   Картинка для превью посилання.

   Коли людина кидає посилання в Telegram чи Discord, месенджер тягне
   те, що вказано в og:image. Для однієї угоди туди йде її ж скрін — це
   правильно. А для тижня чи місяця раніше теж підставлявся випадковий
   скрін якоїсь угоди: незрозуміло, за що ця зведення й що всередині.

   Тому для періоду малюємо свою картинку — календар: клітинки днів із
   результатом, зелені й червоні. Видно період цілком, ще не відкривши
   посилання.

   Малюємо на canvas у браузері, коли створюється посилання, і кладемо
   поруч зі знімком. Сервер потім просто віддає її як og:image.

   Кольори тут задані явно, а не з теми: картинку побачать люди, у яких
   ніякої нашої теми немає.
   ============================================================ */
(function(){

const W = 1200, H = 630;
const C = {
  bg: "#0b0b0c", panel: "#111112", line: "rgba(255,255,255,.09)",
  soft: "rgba(255,255,255,.05)",
  text: "#f2f2f3", dim: "#8c8c90", faint: "#5c5c61",
  up: "#40e094", down: "#ff6e60", be: "#efc258",
  upBg: "rgba(64,224,148,.14)", downBg: "rgba(255,110,96,.13)", beBg: "rgba(239,194,88,.12)",
};
const SANS = '"Geist","Segoe UI",system-ui,sans-serif';
const MONO = '"Archivo","Geist",system-ui,sans-serif';

function roundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

const pct = v => (v == null || isNaN(v)) ? "—" : (v > 0 ? "+" : "") + (Math.round(v * 100) / 100) + "%";
const tone = v => v > 0.0001 ? "up" : v < -0.0001 ? "down" : "be";

/* Знак StatsAI. Беремо ті самі контури, що й на сторінці, — вони лежать
   у <symbol id="logomark">, тож дублювати їх тут не треба. */
function drawMark(ctx, x, y, size){
  const sym = document.getElementById("logomark");
  if (!sym) return;
  const paths = [...sym.querySelectorAll("path")];
  if (!paths.length) return;
  const k = size / 1315;                 /* viewBox 573 366 902 1315 */
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k, k);
  ctx.translate(-573, -366);
  paths.forEach((p, i) => {
    ctx.fillStyle = i === 0 ? C.up : C.text;
    try{ ctx.fill(new Path2D(p.getAttribute("d"))); }catch(e){}
  });
  ctx.restore();
}

/* Шапка. Тримаємо її низькою: головне на картинці — сітка днів, і саме
   їй потрібна висота. Тому знак і назва в один рядок, а період і підсумок
   у наступний. */
function header(ctx, kindFull, title, total){
  drawMark(ctx, 64, 40, 34);
  ctx.textBaseline = "alphabetic";
  ctx.font = "500 24px " + MONO;
  ctx.fillStyle = C.text;
  ctx.fillText("Stats", 96, 66);
  const w = ctx.measureText("Stats").width;
  ctx.fillStyle = C.up;
  ctx.fillText("AI", 96 + w, 66);

  ctx.font = "500 18px " + MONO;
  ctx.fillStyle = C.faint;
  ctx.textAlign = "right";
  ctx.fillText(String(kindFull || "").toUpperCase(), W - 64, 66);
  ctx.textAlign = "left";

  ctx.font = "600 46px " + SANS;
  ctx.fillStyle = C.text;
  ctx.fillText(String(title || ""), 64, 136);

  if (total != null){
    const t = tone(total);
    ctx.font = "500 46px " + MONO;
    ctx.fillStyle = t === "up" ? C.up : t === "down" ? C.down : C.be;
    ctx.textAlign = "right";
    ctx.fillText(pct(total), W - 64, 136);
    ctx.textAlign = "left";
  }
}

/* підсумкові цифри під календарем */
function kpiRow(ctx, kpis, y){
  const list = (kpis || []).slice(0, 4).filter(k => k && k.v);
  if (!list.length) return;
  const gap = 46;
  let x = 64;
  list.forEach(k => {
    ctx.font = "500 17px " + MONO;
    ctx.fillStyle = C.faint;
    ctx.fillText(String(k.k).toUpperCase(), x, y);
    ctx.font = "500 30px " + MONO;
    ctx.fillStyle = k.cls === "pos" ? C.up : k.cls === "neg" ? C.down : C.text;
    ctx.fillText(String(k.v), x, y + 38);
    const w = Math.max(ctx.measureText(String(k.v)).width,
                       (ctx.font = "500 17px " + MONO, ctx.measureText(String(k.k).toUpperCase()).width));
    x += w + gap;
  });
}

/* сітка днів */
function grid(ctx, cal, wd, top, bottom){
  const days = cal.days || [];
  if (!days.length) return;
  const first = new Date(days[0].date + "T00:00");
  const pad = (first.getDay() + 6) % 7;
  const cols = 7;
  const rows = Math.ceil((pad + days.length) / cols);

  const left = 64, right = W - 64;
  const gapX = 8, gapY = 8;
  const cw = (right - left - gapX * (cols - 1)) / cols;
  const headH = 26;
  const avail = bottom - top - headH - 10;
  const ch = Math.min((avail - gapY * (rows - 1)) / rows, 118);
  const tight = ch < 62;                 /* у місяці рядків шість — місця мало */

  /* підписи днів тижня */

  /* Коли рядок один (тиждень), сітка не має тулитись до верху й лишати
     півкартинки порожньою — ставимо її по центру вільного місця. */
  const gridH = rows * ch + gapY * (rows - 1);
  const gridTop = top + headH + 10 + Math.max(0, (avail - gridH) / 2);

  /* підписи днів тижня — рівно над сіткою */
  ctx.font = "500 15px " + MONO;
  ctx.fillStyle = C.faint;
  ctx.textAlign = "center";
  for (let i = 0; i < cols; i++){
    ctx.fillText(String(wd[i] || "").toUpperCase(), left + i * (cw + gapX) + cw / 2, gridTop - 14);
  }
  ctx.textAlign = "left";
  days.forEach((d, i) => {
    const n = pad + i;
    const x = left + (n % cols) * (cw + gapX);
    const y = gridTop + Math.floor(n / cols) * (ch + gapY);
    const has = d.n > 0;
    const t = has ? tone(d.net) : null;

    ctx.fillStyle = !has ? C.panel
      : t === "up" ? C.upBg : t === "down" ? C.downBg : C.beBg;
    roundRect(ctx, x, y, cw, ch, 12);
    ctx.fill();
    if (!has){
      ctx.strokeStyle = C.soft; ctx.lineWidth = 1;
      roundRect(ctx, x, y, cw, ch, 12); ctx.stroke();
    }

    if (tight){
      /* число ліворуч, результат праворуч — в один рядок */
      const mid = y + ch / 2 + 7;
      ctx.font = "500 16px " + MONO;
      ctx.fillStyle = has ? C.dim : C.faint;
      ctx.fillText(String(Number(d.date.slice(8))), x + 11, mid);
      if (has){
        ctx.font = "500 21px " + MONO;
        ctx.fillStyle = t === "up" ? C.up : t === "down" ? C.down : C.be;
        ctx.textAlign = "right";
        ctx.fillText(pct(d.net), x + cw - 11, mid);
        ctx.textAlign = "left";
      }
    } else {
      ctx.font = "500 17px " + MONO;
      ctx.fillStyle = has ? C.dim : C.faint;
      ctx.fillText(String(Number(d.date.slice(8))), x + 12, y + 28);
      if (has){
        ctx.font = "500 " + (ch > 88 ? 30 : 24) + "px " + MONO;
        ctx.fillStyle = t === "up" ? C.up : t === "down" ? C.down : C.be;
        ctx.fillText(pct(d.net), x + 12, y + ch - 18);
      }
    }
  });
}

/* Ряд «чіпів» — коротких плашок. Повертає, скільки висоти зайняв.
   Що не влізло в один рядок, згортається в «+ще 3»: картинка має
   лишатись читабельною, а не перетворюватись на список. */
function chipRow(ctx, x, y, maxW, items, opt){
  const o = opt || {};
  const fs = o.font || 22, pad = o.pad || 14, h = o.h || 44, gap = 9;
  if (!items.length) return 0;
  ctx.font = "500 " + fs + "px " + MONO;

  const fit = [];
  let used = 0;
  for (const it of items){
    const w = ctx.measureText(it).width + pad * 2;
    /* лишаємо місце під «+ще N», якщо це не останній, що влазить */
    if (used + w > maxW && fit.length) break;
    fit.push({t: it, w: w});
    used += w + gap;
  }
  const rest = items.length - fit.length;
  if (rest > 0){
    const more = "+" + rest;
    const w = ctx.measureText(more).width + pad * 2;
    while (fit.length > 1 && used + w > maxW){
      used -= fit.pop().w + gap;
    }
    fit.push({t: more, w: w, dim: true});
  }

  let cx = x;
  fit.forEach(c => {
    ctx.fillStyle = c.dim ? C.panel : "rgba(64,224,148,.10)";
    roundRect(ctx, cx, y, c.w, h, 11);
    ctx.fill();
    ctx.strokeStyle = c.dim ? C.line : "rgba(64,224,148,.30)";
    ctx.lineWidth = 1;
    roundRect(ctx, cx, y, c.w, h, 11);
    ctx.stroke();

    ctx.font = "500 " + fs + "px " + MONO;
    ctx.fillStyle = c.dim ? C.faint : C.up;
    ctx.fillText(c.t, cx + pad, y + h / 2 + fs * 0.36);
    cx += c.w + gap;
  });
  return h;
}

/* підпис розділу */
function label(ctx, x, y, text){
  ctx.font = "500 16px " + MONO;
  ctx.fillStyle = C.faint;
  ctx.fillText(String(text || "").toUpperCase(), x, y);
}

/* Тло: рідкий ряд свічок у самому низу, ледь помітний. Дає картинці
   тему, не забираючи уваги в тексту. */
function candles(ctx, x, y, w, h){
  const seed = [.30,.38,.34,.46,.42,.54,.5,.62,.58,.68,.64,.76,.72,.82];
  const n = seed.length, cw = w / n, bw = Math.round(cw * .4);
  ctx.globalAlpha = .16;
  for (let i = 0; i < n; i++){
    const o = seed[i], cl = i + 1 < n ? seed[i + 1] : seed[i] + .04;
    const yo = y + h - o * h, yc = y + h - cl * h;
    const top = Math.min(yo, yc), bh = Math.max(5, Math.abs(yc - yo));
    const cx = x + i * cw + cw / 2;
    const col = cl >= o ? C.up : C.down;
    ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(cx, top - 12); ctx.lineTo(cx, top + bh + 12); ctx.stroke();
    ctx.fillStyle = col;
    roundRect(ctx, cx - bw / 2, top, bw, bh, 3); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

/* ---------- картинка торгової системи ---------- */
function system(data){
  const t = data.ts || {};
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  candles(ctx, 640, 300, 520, 250);

  header(ctx, data.kindFull || data.kind, data.title, null);
  ctx.strokeStyle = C.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(64, 164); ctx.lineTo(W - 64, 164); ctx.stroke();

  const x = 64, maxW = W - 128;
  let y = 212;

  const rows = [
    [T.tsShAssets, (t.assets || [])],
    [T.tsShTfs, (t.tfs || []).map(r => r.tf).filter(Boolean)],
    [T.tsShModels, (t.models || []).map(m => m.name).filter(Boolean)],
  ].filter(r => r[1].length);

  rows.forEach(r => {
    label(ctx, x, y, r[0]);
    y += 20;
    y += chipRow(ctx, x, y, maxW, r[1]) + 34;
  });

  /* Якщо в системі майже нічого не заповнено — не лишаємо порожнечу:
     пишемо, що всередині, словами. */
  if (!rows.length){
    ctx.font = "400 28px " + SANS;
    ctx.fillStyle = C.dim;
    ctx.fillText(T.tsShTitle, x, 250);
  }

  ctx.beginPath(); ctx.moveTo(64, H - 90); ctx.lineTo(W - 64, H - 90); ctx.stroke();
  kpiRow(ctx, data.kpis, H - 58);

  return cv.toDataURL("image/png");
}

/* ---------- картинка періоду ---------- */
function period(data){
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);

  header(ctx, data.kindFull || data.kind, data.title, data.total);
  ctx.strokeStyle = C.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(64, 164); ctx.lineTo(W - 64, 164); ctx.stroke();

  const wd = (T.shCalWd || ["пн","вт","ср","чт","пт","сб","нд"]);
  grid(ctx, data.calendar, wd, 182, H - 104);

  ctx.beginPath(); ctx.moveTo(64, H - 90); ctx.lineTo(W - 64, H - 90); ctx.stroke();
  kpiRow(ctx, data.kpis, H - 58);

  return cv.toDataURL("image/png");
}

window.OgCal = {period, system};

})();
