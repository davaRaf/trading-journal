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
/* Дві палітри. Темна — звичайна, її бачать усі. Світла — оформлення
   спільноти Black Swan: коли знімком діляться в їхньому стилі, картинка
   має виглядати так само, як журнал у їхній темі.
   Кольори задані явно, а не з теми: картинку побачать люди, у яких
   ніякої нашої теми немає. */
const DARK = {
  bg: "#0b0b0c", panel: "#111112", line: "rgba(255,255,255,.09)",
  soft: "rgba(255,255,255,.05)",
  text: "#f2f2f3", dim: "#8c8c90", faint: "#5c5c61",
  up: "#40e094", down: "#ff6e60", be: "#efc258",
  upBg: "rgba(64,224,148,.14)", downBg: "rgba(255,110,96,.13)", beBg: "rgba(239,194,88,.12)",
  mark: "#40e094",
};
const SWAN = {
  bg: "#ffffff", panel: "#f4f6f8", line: "rgba(0,0,0,.13)",
  soft: "rgba(0,0,0,.06)",
  text: "#000000", dim: "#2b2e33", faint: "#585c63",
  up: "#0b7a42", down: "#c42b1c", be: "#0066ff",
  upBg: "rgba(11,122,66,.12)", downBg: "rgba(196,43,28,.10)", beBg: "rgba(0,102,255,.10)",
  mark: "#40e094",              /* наш знак лишається зеленим і тут */
};
let C = DARK;

/* Оформлення їде в самому знімку — те саме поле, що читає сторінка
   за посиланням. */
function pick(data){ C = (data && data.skin === "blackswan") ? SWAN : DARK; }
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
    ctx.fillStyle = i === 0 ? C.mark : C.text;
    try{ ctx.fill(new Path2D(p.getAttribute("d"))); }catch(e){}
  });
  ctx.restore();
}

/* Шапка. Тримаємо її низькою: головне на картинці — сітка днів, і саме
   їй потрібна висота. Тому знак і назва в один рядок, а період і підсумок
   у наступний. */
/* Знак спільноти Black Swan. Контури теж лежать у документі — <symbol
   id="swanmark">, — тож координати граней тут не дублюємо. */
function drawSwan(ctx, x, y, size){
  const sym = document.getElementById("swanmark");
  if (!sym) return 0;
  const shapes = [...sym.querySelectorAll("polygon")];
  if (!shapes.length) return 0;
  const k = size / 100;                  /* viewBox 0 0 80 100 */
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k, k);
  shapes.forEach(pg => {
    const pts = (pg.getAttribute("points") || "").trim().split(/\s+/)
      .map(pair => pair.split(",").map(Number))
      .filter(p => p.length === 2 && !isNaN(p[0]) && !isNaN(p[1]));
    if (pts.length < 3) return;
    ctx.beginPath();
    pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.closePath();
    /* одна грань синя — вона підписана їхнім кольором просто в symbol */
    ctx.fillStyle = /swan-blue/.test(pg.getAttribute("fill") || "") ? "#0066ff" : C.text;
    ctx.fill();
    /* білі шви між гранями — інакше на такому розмірі знак злипається
       в одну пляму */
    ctx.strokeStyle = C.bg; ctx.lineWidth = 2.6; ctx.lineJoin = "round";
    ctx.stroke();
  });
  ctx.restore();
  return 80 * k;                         /* ширина знака */
}

/* Підпис угорі картинки: наш знак, назва, а в оформленні спільноти ще
   «×» і їхній лебідь. Живе окремо, бо тим самим підписом користується й
   картинка дня з tradeimg.js — щоб він був один на всі картинки.

   col — кольори тієї картинки, куди малюємо (у дня своя палітра);
   swan — чи показувати колаборацію. Повертає нижню межу підпису. */
function brand(ctx, x, y, size, col, swan){
  const keep = C;
  C = col || C;                          /* drawMark і drawSwan читають C */
  const base = y + size * 0.78;          /* лінія шрифту під знаком */

  drawMark(ctx, x, y, size);
  ctx.textBaseline = "alphabetic";

  const tx = x + size * 902 / 1315 + 14;
  ctx.font = "500 " + Math.round(size * 0.58) + "px " + MONO;
  ctx.fillStyle = C.text;
  ctx.fillText("Stats", tx, base);
  const w = ctx.measureText("Stats").width;
  ctx.fillStyle = C.mark;                /* «AI» — наш зелений, а не колір плюса */
  ctx.fillText("AI", tx + w, base);

  if (swan){
    const after = tx + w + ctx.measureText("AI").width;
    ctx.font = "400 " + Math.round(size * 0.41) + "px " + MONO;
    ctx.fillStyle = C.faint;
    ctx.fillText("×", after + 16, base - 3);
    drawSwan(ctx, after + 42, y, size);
  }

  C = keep;
  return y + size;
}

/* Знаки спільноти на тлі картинки: великі, напівпрозорі, і їх мало —
   це фактура, а не малюнок. Малюємо одразу після заливки тла, тому
   картки й текст лягають зверху й лишаються читними.

   Розмір рахуємо від ширини, а розкидаємо по висоті: картинка дня буває
   в кілька екранів заввишки, і прив'язка до висоти роздула б знак. */
function watermark(ctx, w, h, col){
  const keep = C;
  C = col || C;
  const size = w * 0.54;
  const wide = size * 0.8;               /* знак 80 на 100 */
  /* за край виходимо трохи: силует має читатись, а не бути смугою */
  const spots = [
    {x: w - wide * 0.88, y: h * 0.06},
    {x: -wide * 0.16,    y: h * 0.54},
    {x: w - wide * 0.72, y: h * 0.80},
  ];
  /* на короткій картинці двох досить, на довгій ставимо третій */
  const n = h > w * 2.2 ? 3 : 2;
  ctx.save();
  ctx.globalAlpha = 0.07;
  spots.slice(0, n).forEach(p => drawSwan(ctx, p.x, p.y, size));
  ctx.restore();
  C = keep;
}

function header(ctx, kindFull, title, total){
  /* В оформленні спільноти знаки більші, і поруч із ними стоїть наша
     назва — а вже за нею «×» і їхній лебідь. Так видно, чий це журнал
     і з ким колаборація. */
  const swan = C === SWAN;
  const size = swan ? 46 : 34;

  brand(ctx, 64, swan ? 36 : 40, size, C, swan);
  ctx.textBaseline = "alphabetic";

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
  pick(data);
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

/* Підсумки по місяцях беремо з того самого блоку, що йде в посилання. */
function monthItems(data){
  const b = (data.blocks || []).find(x => x && (x.items || []).length
    && (x.items || []).every(i => typeof i.value === "number"));
  return b ? b.items : [];
}

/* Місяці стовпчиками: нуль посередині, зелене вгору, червоне вниз. */
function months(ctx, items, top, bottom){
  if (!items.length) return;
  const left = 64, right = W - 64;
  const gap = 12;
  const cw = Math.min(96, (right - left - gap * (items.length - 1)) / items.length);
  const wide = items.length * cw + gap * (items.length - 1);
  const x0 = left + (right - left - wide) / 2;

  const labH = 34;                       /* під підпис місяця знизу */
  const zone = bottom - top - labH;
  const mid = top + zone / 2;
  const max = Math.max(0.001, ...items.map(i => Math.abs(i.value)));

  ctx.strokeStyle = C.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(left, mid); ctx.lineTo(right, mid); ctx.stroke();

  items.forEach((it, i) => {
    const x = x0 + i * (cw + gap);
    const h = Math.max(3, Math.abs(it.value) / max * (zone / 2 - 10));
    const up = it.value >= 0;
    ctx.fillStyle = up ? C.up : C.down;
    ctx.globalAlpha = .85;
    roundRect(ctx, x, up ? mid - h : mid, cw, h, 5);
    ctx.fill();
    ctx.globalAlpha = 1;

    ctx.font = "500 17px " + MONO;
    ctx.fillStyle = up ? C.up : C.down;
    ctx.textAlign = "center";
    ctx.fillText((it.value > 0 ? "+" : "") + it.value.toFixed(1),
                 x + cw / 2, up ? mid - h - 10 : mid + h + 24);

    ctx.font = "400 15px " + SANS;
    ctx.fillStyle = C.faint;
    ctx.fillText(String(it.name).slice(0, 3), x + cw / 2, bottom - 8);
    ctx.textAlign = "left";
  });
}

/* ---------- картинка періоду ---------- */
function period(data){
  pick(data);
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);

  header(ctx, data.kindFull || data.kind, data.title, data.total);
  ctx.strokeStyle = C.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(64, 164); ctx.lineTo(W - 64, 164); ctx.stroke();

  if (data.calendar){
    const wd = (T.shCalWd || ["пн","вт","ср","чт","пт","сб","нд"]);
    grid(ctx, data.calendar, wd, 182, H - 104);
  }else{
    /* У року календаря немає: 365 клітинок тут не прочитати. Замість
       нього — місяці стовпчиками, видно, де рік заробив, а де віддав. */
    months(ctx, monthItems(data), 182, H - 104);
  }

  ctx.beginPath(); ctx.moveTo(64, H - 90); ctx.lineTo(W - 64, H - 90); ctx.stroke();
  kpiRow(ctx, data.kpis, H - 58);

  return cv.toDataURL("image/png");
}

window.OgCal = {period, system, brand, watermark};

})();
