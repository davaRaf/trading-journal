/* ============================================================
   Картинка угоди й картинка дня — щоб скопіювати й кинути в чат.

   Посилання показує лише пораховані цифри. Тут навпаки: усе, як воно
   є в журналі — як заходив, що записав, і самі графіки. Малюємо на
   canvas, бо картинку можна покласти в буфер, а сторінку — ні.

   Графік входу (наймолодший таймфрейм) іде окремо й на всю ширину:
   на маленькій плитці не видно того, заради чого картинку й шлють —
   як набиралась позиція.

   Кольори беруться з поточної теми, тому картинка виглядає так само,
   як журнал на екрані.
   ============================================================ */
(function(){

const W = 1080;
const PAD = 56;
const GAP = 16;
const MONO = '"Geist Mono","IBM Plex Mono",ui-monospace,Consolas,monospace';
const SANS = '"Geist","IBM Plex Sans","Segoe UI",system-ui,sans-serif';

/* ---------- дрібниці ----------
   Кольори беремо з теми, тому картинка виглядає так само, як журнал на
   екрані. Раніше ці три жили в share.js, поруч із картинкою місяця; той
   файл пішов разом зі своєю кнопкою, і малювання впало на порожньому
   місці — тепер вони тут, і файл ні від кого не залежить. */
/* Стиль, у якому малюємо картинку: "" — поточна тема журналу, або id
   теми спільноти, коли людина вибрала поділитись у їхньому оформленні. */
let forceSkin = "";

/* Чи це оформлення спільноти — байдуже, вибрали його для знімка чи журнал
   і так у їхній темі. Від цього залежить підпис угорі картинки. */
function collabMode(){
  const skin = forceSkin || document.documentElement.getAttribute("data-skin");
  return skin === "blackswan";
}

/* Підпис угорі: наш знак, назва, «×» і лебідь спільноти. Малює OgCal —
   той самий підпис стоїть на зведенні за період, другого не заводимо. */
const BRAND_H = 78;
function drawBrand(ctx, C, x, y){
  if (window.OgCal && typeof OgCal.brand === "function")
    OgCal.brand(ctx, x, y, 46, C, true);
}

/* Знаки спільноти на тлі — теж із OgCal, щоб малюнок був один на всі
   картинки.

   Кладемо одразу після заливки тла, під увесь вміст: так знак не лізе
   на графіки угод, а сам залишається тлом. Щоб його було видно крізь
   картки, у цій темі вони йдуть без заливки — див. нижче. */
function drawWatermark(ctx, C, w, h){
  if (window.OgCal && typeof OgCal.watermark === "function")
    OgCal.watermark(ctx, w, h, C);
}

function themeColors(){
  const root = document.documentElement;
  const prevSkin = root.getAttribute("data-skin");
  const prevBase = root.getAttribute("data-theme");
  /* Підміняємо тему на час зчитування: так кольори беруться з тих самих
     змінних, що й на екрані, і другого списку кольорів у коді не заводимо.
     Все синхронно, тому інтерфейс не встигає перемалюватись. */
  const swap = forceSkin && forceSkin !== prevSkin;
  if (swap){
    root.setAttribute("data-skin", forceSkin);
    root.setAttribute("data-theme", "light");   /* тема спільноти світла */
  }
  const cs = getComputedStyle(root);
  const g = n => cs.getPropertyValue(n).trim();
  const out = {
    bg:g("--bg"), panel:g("--panel"), panel2:g("--panel-2"),
    line:g("--line"), lineSoft:g("--line-soft"),
    text:g("--text"), dim:g("--dim"), faint:g("--faint"),
    accent:g("--accent"), up:g("--up"), down:g("--down"), be:g("--be"),
    /* наш фірмовий зелений — ним підписується «AI» в назві */
    mark:g("--logo-green") || "#40e094",
  };
  if (swap){
    if (prevSkin) root.setAttribute("data-skin", prevSkin);
    else root.removeAttribute("data-skin");
    if (prevBase) root.setAttribute("data-theme", prevBase);
  }
  return out;
}

function withAlpha(hex, a){
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.replace("#",""));
  if(!m) return hex;
  const n = parseInt(m[1],16);
  return "rgba("+((n>>16)&255)+","+((n>>8)&255)+","+(n&255)+","+a+")";
}

function roundRect(ctx,x,y,w,h,r){
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.quadraticCurveTo(x+w,y,x+w,y+r);
  ctx.lineTo(x+w,y+h-r); ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
  ctx.lineTo(x+r,y+h); ctx.quadraticCurveTo(x,y+h,x,y+h-r);
  ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath();
}

function wrap(ctx, text, maxW){
  const out = [];
  for (const para of String(text || "").split("\n")){
    if (!para.trim()){ out.push(""); continue; }
    let line = "";
    for (const word of para.split(/\s+/)){
      const probe = line ? line + " " + word : word;
      if (ctx.measureText(probe).width > maxW && line){ out.push(line); line = word; }
      else line = probe;
    }
    if (line) out.push(line);
  }
  return out;
}

function loadImg(src){
  return new Promise(res => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => res(null);
    im.src = src;
  });
}

/* Скріншоти впорядковані від старшого таймфрейму до молодшого.
   Останній — це вхід: саме його показуємо великим.

   Обрізаємо не з кінця, а з середини: раніше зайві відкидались після
   сортування, і першим вилітав якраз вхід — той графік, заради якого
   картинку й роблять. */
async function shotsOf(t, limit, srcOf){
  let list = (t.screenshots || []).slice()
    .sort((a, b) => TF_ORDER.indexOf(a.tf) - TF_ORDER.indexOf(b.tf));
  if (list.length > limit){
    const entry = list[list.length - 1];
    list = list.slice(0, limit - 1).concat([entry]);
  }
  const out = [];
  for (const s of list){
    const im = await loadImg((srcOf || shotSrc)(s));
    if (im) out.push({im, tf: s.tf || "", note: (s.note || "").trim()});
  }
  return out;
}

/* Підпис під скріном — те, чому людина бачить на цьому графіку саме це.
   На картинці місця менше, ніж у журналі, тож довгий підпис ріжемо: у сітці
   до трьох рядків, під великим графіком до чотирьох. Міряємо тим самим
   шрифтом, яким малюємо, — інакше висота полотна розійдеться з текстом і
   підпис або наліз би на наступний блок, або лишив би порожнечу. */
const NOTE_FONT = "22px " + SANS;
const NOTE_LH = 30;                  /* висота рядка підпису */
const NOTE_TOP = 10;                 /* відступ від картинки до першого рядка */
const GRID_NOTE = 3, BIG_NOTE = 4;   /* скільки рядків лишаємо */
let noteProbe = null;

function noteLines(note, maxW, maxLines){
  const text = String(note || "").trim();
  if (!text) return [];
  if (!noteProbe) noteProbe = document.createElement("canvas").getContext("2d");
  noteProbe.font = NOTE_FONT;
  const all = wrap(noteProbe, text, maxW).filter(l => l !== "");
  if (all.length <= maxLines) return all;
  const cut = all.slice(0, maxLines);
  cut[maxLines - 1] = cut[maxLines - 1].replace(/[\s.,;:—-]+$/, "") + "…";
  return cut;
}
/* скільки місця з'їдають рядки підпису — нуль, коли підпису немає */
function noteBox(lines){
  return lines.length ? NOTE_TOP + lines.length * NOTE_LH : 0;
}
function drawNote(ctx, C, lines, x, y){
  if (!lines.length) return 0;
  ctx.font = NOTE_FONT; ctx.fillStyle = C.dim;
  lines.forEach((l, i) => ctx.fillText(l, x, y + NOTE_TOP + (i + 1) * NOTE_LH - 8));
  return noteBox(lines);
}

function split(imgs){
  if (imgs.length <= 1) return {grid: [], big: imgs[0] || null};
  return {grid: imgs.slice(0, -1), big: imgs[imgs.length - 1]};
}

function shotsHeight(imgs, w){
  const {grid, big} = split(imgs);
  const iw = (w - GAP) / 2;
  let h = 0;
  for (let r = 0; r * 2 < grid.length; r++){
    const row = grid.slice(r * 2, r * 2 + 2);
    /* у ряду два скріни, підписи різної довжини — ряд росте за вищим */
    const note = Math.max(...row.map(g => noteBox(noteLines(g.note, iw, GRID_NOTE))));
    h += Math.max(...row.map(g => Math.round(iw * g.im.height / g.im.width))) + 28 + 14 + note;
  }
  if (big) h += Math.round(w * big.im.height / big.im.width) + 32 + 14
             + noteBox(noteLines(big.note, w, BIG_NOTE));
  return h;
}

function drawShots(ctx, C, imgs, x, w, y){
  const {grid, big} = split(imgs);
  const iw = (w - GAP) / 2;
  for (let r = 0; r * 2 < grid.length; r++){
    const row = grid.slice(r * 2, r * 2 + 2);
    const rh = Math.max(...row.map(g => Math.round(iw * g.im.height / g.im.width)));
    let note = 0;
    row.forEach((g, i) => {
      const gx = x + i * (iw + GAP);
      const gh = Math.round(iw * g.im.height / g.im.width);
      ctx.font = "500 19px " + MONO; ctx.fillStyle = C.faint;
      ctx.fillText((g.tf || "chart").toUpperCase(), gx, y + 14);
      ctx.save(); roundRect(ctx, gx, y + 28, iw, gh, 10); ctx.clip();
      ctx.drawImage(g.im, gx, y + 28, iw, gh); ctx.restore();
      ctx.strokeStyle = C.line; ctx.lineWidth = 1;
      roundRect(ctx, gx, y + 28, iw, gh, 10); ctx.stroke();
      /* підпис під своїм скріном, від низу ряду — щоб сусідні починались рівно */
      note = Math.max(note, drawNote(ctx, C, noteLines(g.note, iw, GRID_NOTE), gx, y + 28 + rh));
    });
    y += rh + 28 + 14 + note;
  }
  if (big){
    const gh = Math.round(w * big.im.height / big.im.width);
    ctx.font = "500 21px " + MONO; ctx.fillStyle = C.accent;
    /* «Вхід» пишемо, лише коли графіків кілька: якщо він один, то це просто
       єдиний графік, а не наймолодший таймфрейм */
    ctx.fillText(grid.length
      ? T.tiEntryShot + (big.tf ? "  ·  " + big.tf.toUpperCase() : "")
      : (big.tf || "chart").toUpperCase(), x, y + 15);
    ctx.save(); roundRect(ctx, x, y + 32, w, gh, 12); ctx.clip();
    ctx.drawImage(big.im, x, y + 32, w, gh); ctx.restore();
    ctx.strokeStyle = withAlpha(C.accent, .5); ctx.lineWidth = 1.5;
    roundRect(ctx, x, y + 32, w, gh, 12); ctx.stroke(); ctx.lineWidth = 1;
    y += gh + 32 + 14 + drawNote(ctx, C, noteLines(big.note, w, BIG_NOTE), x, y + 32 + gh);
  }
  return y;
}

/* ============================ одна угода ============================ */
async function buildTradeImage(t){
  await document.fonts.ready;
  const C = themeColors();
  const r = netR(t);
  const inner = W - PAD * 2;
  const imgs = await shotsOf(t, 5);

  const probe = document.createElement("canvas").getContext("2d");
  probe.font = "26px " + SANS;

  const facts = [[T.fSession, t.session], [T.fBias, t.bias],
    [T.fEntryModel, t.entry_model], [T.fSetup, t.setup],
    [T.fDirTypeFilter, dirType(t)]].map(([k, v]) => [k, v || "—"]);
  const rows = Math.ceil(facts.length / 2);

  const blocks = [[T.tiHowEntered, t.entry_details], [T.tiNotes, t.notes],
                  [T.tiMistakes, t.mistakes]]
    .filter(x => (x[1] || "").trim())
    .map(([k, v]) => ({k, lines: wrap(probe, v.trim(), inner)}));

  /* Висота рахується рівно за тим, що малюємо нижче: до першого рядка
     фактів іде 346px, кожен блок тексту з'їдає 56 + рядки. Раніше тут
     стояли приблизні числа — і на угодах із нотатками підпис унизу
     налізав на останній рядок. */
  let H = PAD + 346 + rows * 58
        + blocks.reduce((a, b) => a + 56 + b.lines.length * 38, 0)
        + (imgs.length ? 56 + shotsHeight(imgs, inner) : 0)
        + 96;

  const cv = document.createElement("canvas");
  const dpr = 2;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = C.panel;
  roundRect(ctx, PAD - 26, PAD - 26, W - (PAD - 26) * 2, H - (PAD - 26) * 2, 26);
  ctx.fill();
  ctx.strokeStyle = C.lineSoft; ctx.lineWidth = 1; ctx.stroke();

  let y = PAD + 24;
  ctx.font = "600 46px " + SANS; ctx.fillStyle = C.text;
  const pair = t.pair || "—";
  ctx.fillText(pair, PAD, y + 18);
  const pw = ctx.measureText(pair).width;

  if (t.position){
    const col = t.position === "Long" ? C.up : C.down;
    ctx.font = "500 20px " + MONO;
    const label = t.position.toUpperCase();
    const bw = ctx.measureText(label).width + 30;
    ctx.fillStyle = withAlpha(col, .14);
    roundRect(ctx, PAD + pw + 20, y - 8, bw, 34, 17); ctx.fill();
    ctx.fillStyle = col; ctx.fillText(label, PAD + pw + 35, y + 16);
  }

  ctx.font = "500 42px " + MONO;
  ctx.fillStyle = r > 0 ? C.up : r < 0 ? C.down : C.be;
  ctx.textAlign = "right"; ctx.fillText(fmtR(r), W - PAD, y + 16); ctx.textAlign = "left";

  y += 46;
  ctx.font = "22px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText((t.date || "").replace("T", " ").slice(0, 16), PAD, y + 18);

  y += 62;
  ctx.strokeStyle = C.lineSoft; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();

  y += 44;
  [[T.fResult, resLabel(t.result) || "—"],
   ["RR", (t.rr != null && t.rr !== "") ? String(r1(t.rr)) : "—"],
   [T.tiRisk, (t.risk != null && t.risk !== "") ? r1(t.risk) + "%" : "—"]
  ].forEach(([k, v], i) => {
    const x = PAD + i * (inner / 3);
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(String(k).toUpperCase(), x, y);
    ctx.font = "500 40px " + MONO; ctx.fillStyle = C.text;
    ctx.fillText(v, x, y + 48);
  });
  y += 88;
  ctx.strokeStyle = C.lineSoft; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();

  y += 40;
  ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText(T.tiHowTraded, PAD, y);
  y += 30;
  facts.forEach(([k, v], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = PAD + col * (inner / 2 + 10);
    const yy = y + row * 58;
    ctx.font = "24px " + SANS; ctx.fillStyle = C.faint;
    ctx.fillText(k, x, yy + 26);
    ctx.font = "500 25px " + SANS;
    ctx.fillStyle = v === "—" ? C.faint : C.text;
    ctx.textAlign = "right"; ctx.fillText(v, x + inner / 2 - 10, yy + 26); ctx.textAlign = "left";
    ctx.strokeStyle = C.lineSoft; ctx.beginPath();
    ctx.moveTo(x, yy + 44); ctx.lineTo(x + inner / 2 - 10, yy + 44); ctx.stroke();
  });
  y += rows * 58 + 12;

  for (const b of blocks){
    y += 22;
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(String(b.k).toUpperCase(), PAD, y);
    y += 30;
    ctx.font = "26px " + SANS;
    ctx.fillStyle = b.k === T.tiMistakes ? C.down : C.dim;
    for (const line of b.lines){ ctx.fillText(line, PAD, y + 26); y += 38; }
    y += 4;
  }

  if (imgs.length){
    y += 32;
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(T.tiCharts, PAD, y);
    y = drawShots(ctx, C, imgs, PAD, inner, y + 24);
  }

  ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText(T.tiMadeIn, PAD, H - PAD + 6);
  return cv;
}

/* ============================== день ============================== */
async function buildDayImage(dk){
  await document.fonts.ready;
  const C = themeColors();
  const list = sortAsc(S.all.filter(t => dayKey(t) === dk));
  const st = calc(list);
  const d = new Date(dk + "T00:00");
  const title = d.getDate() + " " + T.monthsGen[d.getMonth()] + " " + d.getFullYear();

  const inner = W - PAD * 2;
  const CW = inner - 40;
  const probe = document.createElement("canvas").getContext("2d");

  const cards = [];
  for (const t of list){
    probe.font = "24px " + SANS;
    const texts = [[T.tiHowEntered, t.entry_details], [T.tiNotes, t.notes],
                   [T.tiMistakes, t.mistakes]]
      .filter(x => (x[1] || "").trim())
      .map(([k, v]) => ({k, lines: wrap(probe, v.trim(), CW)}));
    /* у дні з шістьма угодами всі графіки дали б полотно на кілька екранів */
    const imgs = await shotsOf(t, 4);
    let h = 92 + texts.reduce((a, b) => a + 30 + b.lines.length * 34 + 12, 0);
    if (imgs.length) h += shotsHeight(imgs, CW) + 12;
    cards.push({t, texts, imgs, h: h + 26});
  }

  /* в оформленні спільноти зверху додається підпис із двома знаками */
  const brandH = collabMode() ? BRAND_H : 0;
  let H = PAD + brandH + 108 + 118 + 20 + cards.reduce((a, c) => a + c.h + 18, 0) + 74;

  const cv = document.createElement("canvas");
  const dpr = 2;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  if (brandH) drawWatermark(ctx, C, W, H);
  ctx.textBaseline = "alphabetic";

  if (brandH) drawBrand(ctx, C, PAD, PAD - 4);

  let y = PAD + brandH + 20;
  ctx.font = "600 46px " + SANS; ctx.fillStyle = C.text;
  ctx.fillText(title, PAD, y + 18);
  ctx.font = "500 44px " + MONO;
  ctx.fillStyle = st.net > 0 ? C.up : st.net < 0 ? C.down : C.be;
  ctx.textAlign = "right"; ctx.fillText(fmtR(st.net), W - PAD, y + 18); ctx.textAlign = "left";

  y += 62;
  ctx.strokeStyle = C.line; ctx.lineWidth = 1; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();

  y += 44;
  [[T.slTradesTitle, String(st.n)], ["WIN RATE", fmtPct(st.wr)],
   ["RR", st.avgRR != null ? String(r1(st.avgRR)) : "—"],
   ["TP / SL / BE", st.wins + " / " + st.losses + " / " + st.be]
  ].forEach(([k, v], i) => {
    const x = PAD + i * (inner / 4);
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(String(k).toUpperCase(), x, y);
    ctx.font = "500 36px " + MONO; ctx.fillStyle = C.text;
    ctx.fillText(v, x, y + 46);
  });
  y += 78;

  for (const c of cards){
    const t = c.t, r = netR(t);
    /* В оформленні спільноти картку не заливаємо: у цій темі її колір і
       так дорівнює тлу, а без заливки крізь неї видно знак позаду. Межа
       й смуга результату лишаються на місці. */
    roundRect(ctx, PAD, y, inner, c.h, 18);
    if (!brandH){ ctx.fillStyle = C.panel; ctx.fill(); }
    ctx.strokeStyle = C.lineSoft; ctx.stroke();

    ctx.fillStyle = r > 0 ? C.up : r < 0 ? C.down : C.be;
    ctx.save(); roundRect(ctx, PAD, y, inner, c.h, 18); ctx.clip();
    ctx.fillRect(PAD, y, 5, c.h); ctx.restore();

    let iy = y + 22;
    const ix = PAD + 20;

    ctx.font = "22px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText((t.date || "").slice(11, 16), ix, iy + 24);
    ctx.font = "600 30px " + SANS; ctx.fillStyle = C.text;
    ctx.fillText(t.pair || "—", ix + 80, iy + 24);
    ctx.font = "500 26px " + MONO;
    ctx.fillStyle = r > 0 ? C.up : r < 0 ? C.down : C.be;
    ctx.textAlign = "right"; ctx.fillText(fmtR(r), PAD + inner - 20, iy + 24);
    ctx.font = "22px " + MONO; ctx.fillStyle = C.dim;
    ctx.fillText(resLabel(t.result) || "", PAD + inner - 130, iy + 24);
    ctx.textAlign = "left";

    iy += 40;
    ctx.font = "22px " + SANS; ctx.fillStyle = C.faint;
    ctx.fillText([t.position, t.session, t.entry_model, t.setup,
      (t.rr != null && t.rr !== "") ? "RR " + r1(t.rr) : "",
      (t.risk != null && t.risk !== "") ? T.tiRisk + " " + r1(t.risk) + "%" : ""
    ].filter(Boolean).join("  ·  "), ix, iy + 20);
    iy += 44;

    for (const b of c.texts){
      ctx.font = "19px " + MONO; ctx.fillStyle = C.faint;
      ctx.fillText(String(b.k).toUpperCase(), ix, iy + 14);
      iy += 30;
      ctx.font = "24px " + SANS;
      ctx.fillStyle = b.k === T.tiMistakes ? C.down : C.dim;
      for (const line of b.lines){ ctx.fillText(line, ix, iy + 20); iy += 34; }
      iy += 12;
    }

    if (c.imgs.length) drawShots(ctx, C, c.imgs, ix, CW, iy);
    y += c.h + 18;
  }

  ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText(T.tiMadeIn, PAD, H - PAD + 6);
  return cv;
}

/* ============================ розбір дня ============================ */
/* Картинку розбору малював загальний шаблон зведення за період — той, що
   вміє лише календар, стовпчики місяців і рядок показників. У розбору
   немає ні першого, ні другого, а все, заради чого його шлють, лежить у
   data.review, куди той шаблон не заглядає: виходила шапка й порожнеча
   під нею. Тепер у розбору свій малюнок — той самий, що й на сторінці за
   посиланням: по активу картка з графіками, рівнями, планами й вечірнім
   записом, а під ними правила дня й висновок. */

/* Скріни розбору лежать не там, де скріни угод, і віддаються іншою
   адресою: /dnshot/ замість /shots/. Через /shots/ сервер відповідав 404
   (він шукає файл серед скріншотів угод), картинка мовчки лишалась без
   графіків — саме тих, заради яких розбір і показують. */
function dayShotSrc(s){
  if (!s.file) return s.data || "";
  return /^data:/.test(s.file) ? s.file : "/dnshot/" + s.file;
}

const H_TITLE = 26;   /* підпис розділу всередині картки */
const H_LINE  = 34;   /* рядок тексту */
const H_ROW   = 36;   /* рядок рівня або плану */

async function buildReviewImage(data){
  await document.fonts.ready;
  const C = themeColors();
  const rv = (data && data.review) || {};
  const assets = rv.assets || [];

  const inner = W - PAD * 2;
  const CW = inner - 40;
  const probe = document.createElement("canvas").getContext("2d");

  /* Спершу міряємо: висота полотна має бути відома до першого штриха. */
  const cards = [];
  for (const a of assets){
    const parts = [];
    const imgs = await shotsOf({screenshots: a.shots || []}, 4, dayShotSrc);
    if (imgs.length) parts.push({t: T.shRvCharts, imgs, h: shotsHeight(imgs, CW)});

    probe.font = "24px " + SANS;
    if ((a.why || "").trim()){
      const lines = wrap(probe, a.why.trim(), CW);
      parts.push({t: T.shRvWhere, lines, h: lines.length * H_LINE});
    }
    if ((a.levels || []).length)
      parts.push({t: T.shRvLevels, levels: a.levels, h: a.levels.length * H_ROW});
    if ((a.plans || []).length){
      const rows = a.plans.map(pl => ({k: pl.k, lines: wrap(probe, pl.tx || "", CW - 46)}));
      parts.push({t: T.shRvPlans, plans: rows,
                  h: rows.reduce((acc, r) => acc + Math.max(H_ROW, r.lines.length * H_LINE) + 8, 0)});
    }
    const eve = a.eve || {};
    const eveImgs = await shotsOf({screenshots: eve.shots || []}, 2, dayShotSrc);
    if ((eve.text || "").trim() || eveImgs.length){
      const lines = (eve.text || "").trim() ? wrap(probe, eve.text.trim(), CW) : [];
      parts.push({t: T.shRvEvening, lines, imgs: eveImgs,
                  h: lines.length * H_LINE + (eveImgs.length ? shotsHeight(eveImgs, CW) + 10 : 0)});
    }

    const marks = [[T.shRvMatch, (a.marks || {}).match], [T.shRvHold, (a.marks || {}).hold]]
      .filter(m => (m[1] || "").trim());

    let h = 64;                                    /* шапка картки */
    for (const pt of parts) h += H_TITLE + pt.h + 20;
    if (marks.length) h += 34;
    cards.push({a, parts, marks, h: h + 18});
  }

  const notes = [[T.shRvSkip, rv.skip], [T.shRvLesson, rv.lesson]]
    .filter(n => (n[1] || "").trim())
    .map(function(n){
      probe.font = "24px " + SANS;
      const lines = wrap(probe, String(n[1]).trim(), inner - 40);
      return {k: n[0], lines, h: 30 + lines.length * H_LINE + 30};
    });

  const brandH = collabMode() ? BRAND_H : 0;
  const kpis = data.kpis || [];
  const kpiH = kpis.length ? 78 : 0;
  const bodyH = cards.reduce((acc, c) => acc + c.h + 18, 0)
              + notes.reduce((acc, n) => acc + n.h + 18, 0);
  /* порожній розбір — щоб замість дірки був чесний рядок */
  const H = PAD + brandH + 108 + kpiH + 20 + (bodyH || 60) + 74;

  const cv = document.createElement("canvas");
  const dpr = 2;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  if (brandH) drawWatermark(ctx, C, W, H);
  ctx.textBaseline = "alphabetic";
  if (brandH) drawBrand(ctx, C, PAD, PAD - 4);

  let y = PAD + brandH + 20;
  ctx.font = "600 46px " + SANS; ctx.fillStyle = C.text;
  ctx.fillText(data.title || "", PAD, y + 18);
  if (data.total != null){
    ctx.font = "500 44px " + MONO;
    ctx.fillStyle = data.total > 0 ? C.up : data.total < 0 ? C.down : C.be;
    ctx.textAlign = "right"; ctx.fillText(fmtR(data.total), W - PAD, y + 18); ctx.textAlign = "left";
  }

  y += 62;
  ctx.strokeStyle = C.line; ctx.lineWidth = 1; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();
  y += 26;

  if (kpis.length){
    y += 18;
    kpis.slice(0, 4).forEach(function(k, i){
      const x = PAD + i * (inner / 4);
      ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
      ctx.fillText(String(k.k != null ? k.k : (k[0] || "")).toUpperCase(), x, y);
      ctx.font = "500 36px " + MONO; ctx.fillStyle = C.text;
      ctx.fillText(String(k.v != null ? k.v : (k[1] != null ? k[1] : "")), x, y + 46);
    });
    y += 72;
  }

  if (!cards.length && !notes.length){
    ctx.font = "26px " + SANS; ctx.fillStyle = C.faint;
    ctx.fillText(T.tiReviewEmpty, PAD, y + 34);
  }

  for (const c of cards){
    const a = c.a;
    roundRect(ctx, PAD, y, inner, c.h, 18);
    if (!brandH){ ctx.fillStyle = C.panel; ctx.fill(); }
    ctx.strokeStyle = C.lineSoft; ctx.stroke();

    let iy = y + 22;
    const ix = PAD + 20;

    ctx.font = "600 30px " + SANS; ctx.fillStyle = C.text;
    ctx.fillText(a.nm || "—", ix, iy + 24);
    if ((a.side || "").trim()){
      const w0 = ctx.measureText(a.nm || "—").width;
      ctx.font = "22px " + MONO; ctx.fillStyle = C.faint;
      ctx.fillText(a.side, ix + w0 + 16, iy + 24);
    }
    if (a.net != null){
      ctx.font = "500 26px " + MONO;
      ctx.fillStyle = a.net > 0 ? C.up : a.net < 0 ? C.down : C.be;
      ctx.textAlign = "right"; ctx.fillText(fmtR(a.net), PAD + inner - 20, iy + 24);
      ctx.textAlign = "left";
    }
    iy += 42;

    for (const pt of c.parts){
      ctx.font = "19px " + MONO; ctx.fillStyle = C.faint;
      ctx.fillText(String(pt.t).toUpperCase(), ix, iy + 14);
      iy += H_TITLE;

      if (pt.levels){
        for (const l of pt.levels){
          ctx.font = "500 23px " + MONO; ctx.fillStyle = C.text;
          ctx.fillText(l.p || "—", ix, iy + 22);
          ctx.font = "22px " + SANS; ctx.fillStyle = C.dim;
          ctx.fillText([l.t, l.n].filter(Boolean).join(" · "), ix + 150, iy + 22);
          if ((l.did || "").trim()){
            ctx.fillStyle = l.cls === "ok" ? C.up : l.cls === "no" ? C.down : C.faint;
            ctx.textAlign = "right";
            ctx.fillText(l.did, PAD + inner - 20, iy + 22);
            ctx.textAlign = "left";
          }
          iy += H_ROW;
        }
      }else if (pt.plans){
        for (const r of pt.plans){
          ctx.font = "600 22px " + MONO; ctx.fillStyle = C.accent;
          ctx.fillText(r.k, ix, iy + 22);
          ctx.font = "24px " + SANS; ctx.fillStyle = C.dim;
          let ly = iy;
          for (const line of r.lines){ ctx.fillText(line, ix + 46, ly + 22); ly += H_LINE; }
          iy += Math.max(H_ROW, r.lines.length * H_LINE) + 8;
        }
      }else{
        if (pt.lines && pt.lines.length){
          ctx.font = "24px " + SANS; ctx.fillStyle = C.dim;
          for (const line of pt.lines){ ctx.fillText(line, ix, iy + 20); iy += H_LINE; }
        }
        if (pt.imgs && pt.imgs.length){
          if (pt.lines && pt.lines.length) iy += 10;
          iy = drawShots(ctx, C, pt.imgs, ix, CW, iy);
        }
      }
      iy += 20;
    }

    if (c.marks.length){
      ctx.font = "22px " + SANS; ctx.fillStyle = C.faint;
      ctx.fillText(c.marks.map(m => m[0] + ": " + m[1]).join("     "), ix, iy + 18);
    }
    y += c.h + 18;
  }

  for (const n of notes){
    roundRect(ctx, PAD, y, inner, n.h, 18);
    if (!brandH){ ctx.fillStyle = C.panel; ctx.fill(); }
    ctx.strokeStyle = C.lineSoft; ctx.stroke();
    let iy = y + 20;
    ctx.font = "19px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(String(n.k).toUpperCase(), PAD + 20, iy + 14);
    iy += 30;
    ctx.font = "24px " + SANS; ctx.fillStyle = C.dim;
    for (const line of n.lines){ ctx.fillText(line, PAD + 20, iy + 20); iy += H_LINE; }
    y += n.h + 18;
  }

  ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText(T.tiMadeIn, PAD, H - PAD + 6);
  return cv;
}

/* ============================== вікно ============================== */
/* Картинку з готового зображення переносимо в canvas: далі однаково
   працюють і «скопіювати», і «завантажити». */
async function canvasOf(url){
  const im = await loadImg(url);
  const cv = document.createElement("canvas");
  cv.width = im.naturalWidth || im.width;
  cv.height = im.naturalHeight || im.height;
  cv.getContext("2d").drawImage(im, 0, 0);
  return cv;
}

/* Угода й день малюються тут: у них є скріни, і саме заради них картинку
   й шлють. Тиждень, місяць, рік і торгова система — тим самим, чим
   малюється картинка до посилання: там нема чого показувати, крім
   підсумків, і однаковий вигляд у посилання й у картинки на краще. */
async function build(kind, arg, data){
  if (kind === "trade"){
    const t = (S.all.length ? S.all : S.trades).find(x => x.id === arg);
    if (!t) throw new Error(T.tiFailNoTrade || "угоду не знайшли");
    return await buildTradeImage(t);
  }
  if (kind === "day") return await buildDayImage(arg);
  if (kind === "review"){
    if (!data) throw new Error(T.tiFailNoData || "нема з чого малювати");
    return await buildReviewImage(data);
  }
  if (!window.OgCal || !data) throw new Error(T.tiFailNoData || "нема з чого малювати");
  return await canvasOf(kind === "ts" ? OgCal.system(data) : OgCal.period(data));
}

function fileName(kind, arg, data){
  const safe = String((data && data.title) || arg || kind)
    .replace(/[^0-9a-zA-Zа-яА-Яіїєґ_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  return (kind === "trade" ? "trade" : kind) + "-" + (safe || "statsai") + ".png";
}

/* skin — id теми, у якій малювати. Порожньо — поточна тема журналу. */
async function openImage(kind, arg, data, skin){
  forceSkin = skin || "";
  openModal('<div class="m-head"><b>'
    + ((data && (data.kindFull || data.kind)) || (kind === "day" ? T.tiTitleDay : T.tiTitle))
    + '</b><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + T.mrClose + '</button></div>'
    + '<div class="m-body"><div class="sharewrap" id="tiWrap">'
    + '<div class="empty">' + T.tiDrawing + '</div></div></div>'
    + '<div class="m-foot"><button class="btn primary" id="tiCopy">' + T.tiCopy + '</button>'
    + '<button class="btn" id="tiSave">' + T.tiSave + '</button>'
    + '<span class="sp"></span><span class="hint" id="tiMsg"></span></div>');

  let cv;
  try{ cv = await build(kind, arg, data); }
  catch(e){
    forceSkin = "";
    const w = document.getElementById("tiWrap");
    if (w) w.innerHTML = '<div class="empty">' + T.tiFail + esc(e.message) + "</div>";
    return;
  }
  forceSkin = "";                       /* далі малюють у своїй темі */
  const wrapEl = document.getElementById("tiWrap");
  if (!wrapEl) return;
  wrapEl.innerHTML = "";
  cv.style.width = "100%"; cv.style.height = "auto"; cv.style.display = "block";
  cv.style.borderRadius = "10px";
  wrapEl.appendChild(cv);

  const msg = s => { const m = document.getElementById("tiMsg"); if (m) m.textContent = s; };
  document.getElementById("tiCopy").onclick = async () => {
    try{
      const blob = await new Promise(res => cv.toBlob(res, "image/png"));
      await navigator.clipboard.write([new ClipboardItem({"image/png": blob})]);
      msg(T.tiCopied);
    }catch(e){ msg(T.tiNoCopy); }
  };
  document.getElementById("tiSave").onclick = () => {
    const a = document.createElement("a");
    a.href = cv.toDataURL("image/png");
    a.download = fileName(kind, arg, data);
    document.body.appendChild(a);
    a.click();
    a.remove();
    msg(T.tiSaved);
  };
}

window.__tradeImg = {open: openImage};

})();
