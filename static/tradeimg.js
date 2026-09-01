/* ============================================================
   Картинка однієї угоди — щоб скопіювати й кинути в чат.

   Посилання показує лише пораховані цифри. Тут навпаки: усе, як воно
   є в журналі — як заходив, що записав, і самі графіки. Малюємо на
   canvas, бо картинку можна покласти в буфер, а сторінку — ні.

   Кольори беруться з поточної теми, тому картинка виглядає так само,
   як журнал на екрані.
   ============================================================ */
(function(){

const W = 1080;
const PAD = 56;
const MONO = '"Geist Mono","IBM Plex Mono",ui-monospace,Consolas,monospace';
const SANS = '"Geist","IBM Plex Sans","Segoe UI",system-ui,sans-serif';

/* ---------- дрібниці малювання ---------- */
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

/* ---------- сам малюнок ---------- */
async function buildTradeImage(t){
  await document.fonts.ready;
  const C = themeColors();
  const r = netR(t);
  const dark = document.documentElement.getAttribute("data-theme") !== "light";

  /* скріншоти вантажимо заздалегідь: без них не порахувати висоту */
  const shots = (t.screenshots || []).slice()
    .sort((a,b) => TF_ORDER.indexOf(a.tf) - TF_ORDER.indexOf(b.tf))
    .slice(0, 4);
  const imgs = [];
  for (const s of shots){
    const im = await loadImg(shotSrc(s));
    if (im) imgs.push({im, tf: s.tf || ""});
  }

  /* ---- рахуємо висоту ---- */
  const probe = document.createElement("canvas").getContext("2d");
  const inner = W - PAD * 2;

  /* інструмент, напрямок і дата вже стоять у шапці — не повторюємо */
  const facts = [["Сесія", t.session || "—"], ["Біас", t.bias || "—"],
    ["Модель входу", t.entry_model || "—"], ["Сетап", t.setup || "—"],
    ["Прод. / Розв.", dirType(t) || "—"]];
  const rows = Math.ceil(facts.length / 2);

  const texts = [["Як заходив", t.entry_details], ["Нотатки", t.notes],
                 ["Помилки", t.mistakes], ["Коментар", t.comments]]
    .filter(x => (x[1] || "").trim());
  probe.font = "26px " + SANS;
  const blocks = texts.map(([k, v]) => ({k, lines: wrap(probe, v.trim(), inner)}));

  /* картинки кладемо по дві в ряд */
  const cols = imgs.length > 1 ? 2 : 1;
  const cw = imgs.length ? (inner - (cols - 1) * 18) / cols : 0;
  let shotsH = 0;
  const geom = imgs.map((g, i) => {
    const h = Math.round(cw * g.im.height / g.im.width);
    return {h, col: i % cols, row: Math.floor(i / cols)};
  });
  for (let row = 0; row * cols < imgs.length; row++){
    const inRow = geom.filter(g => g.row === row);
    shotsH += Math.max(...inRow.map(g => g.h)) + 30 + 18;   // +подпись +отступ
  }

  let H = PAD + 120            /* шапка */
        + 132                  /* три цифри */
        + rows * 58 + 34       /* як торгував */
        + blocks.reduce((a, b) => a + 34 + b.lines.length * 38 + 18, 0)
        + (imgs.length ? 44 + shotsH : 0)
        + 74;                  /* підпис знизу */

  const cv = document.createElement("canvas");
  const dpr = 2;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);

  /* ---- тло ---- */
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = C.panel;
  roundRect(ctx, PAD - 26, PAD - 26, W - (PAD - 26) * 2, H - (PAD - 26) * 2, 26);
  ctx.fill();
  ctx.strokeStyle = C.lineSoft; ctx.lineWidth = 1; ctx.stroke();

  let y = PAD + 24;

  /* ---- шапка: інструмент, напрямок, дата, підсумок ---- */
  ctx.textBaseline = "alphabetic";
  ctx.font = "600 46px " + SANS; ctx.fillStyle = C.text;
  const pair = t.pair || "Угода";
  ctx.fillText(pair, PAD, y + 18);
  const pw = ctx.measureText(pair).width;

  if (t.position){
    const long = t.position === "Long";
    const col = long ? C.up : C.down;
    ctx.font = "500 20px " + MONO;
    const label = t.position.toUpperCase();
    const bw = ctx.measureText(label).width + 30;
    ctx.fillStyle = withAlpha(col, .14);
    roundRect(ctx, PAD + pw + 20, y - 8, bw, 34, 17); ctx.fill();
    ctx.fillStyle = col;
    ctx.fillText(label, PAD + pw + 35, y + 16);
  }

  ctx.font = "500 42px " + MONO;
  ctx.fillStyle = r > 0 ? C.up : r < 0 ? C.down : C.be;
  ctx.textAlign = "right";
  ctx.fillText(fmtR(r), W - PAD, y + 16);
  ctx.textAlign = "left";

  y += 46;
  ctx.font = "22px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText((t.date || "").replace("T", " ").slice(0, 16), PAD, y + 18);

  y += 62;
  ctx.strokeStyle = C.lineSoft; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();

  /* ---- три цифри ---- */
  y += 44;
  const nums = [["Результат", resLabel(t.result) || "—"],
                ["RR", (t.rr != null && t.rr !== "") ? String(r1(t.rr)) : "—"],
                ["Ризик", (t.risk != null && t.risk !== "") ? r1(t.risk) + "%" : "—"]];
  nums.forEach(([k, v], i) => {
    const x = PAD + i * (inner / 3);
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(k.toUpperCase(), x, y);
    ctx.font = "500 40px " + MONO; ctx.fillStyle = C.text;
    ctx.fillText(v, x, y + 48);
  });
  y += 88;
  ctx.strokeStyle = C.lineSoft; ctx.beginPath();
  ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();

  /* ---- як торгував ---- */
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
    ctx.textAlign = "right";
    ctx.fillText(v, x + inner / 2 - 10, yy + 26);
    ctx.textAlign = "left";
    ctx.strokeStyle = C.lineSoft; ctx.beginPath();
    ctx.moveTo(x, yy + 44); ctx.lineTo(x + inner / 2 - 10, yy + 44); ctx.stroke();
  });
  y += rows * 58 + 12;

  /* ---- записи ---- */
  for (const b of blocks){
    y += 22;
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(b.k.toUpperCase(), PAD, y);
    y += 30;
    ctx.font = "26px " + SANS; ctx.fillStyle = C.dim;
    for (const line of b.lines){ ctx.fillText(line, PAD, y + 26); y += 38; }
    y += 4;
  }

  /* ---- графіки ---- */
  if (imgs.length){
    y += 32;
    ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
    ctx.fillText(T.tiCharts, PAD, y);
    y += 24;
    let rowTop = y, row = 0;
    imgs.forEach((g, i) => {
      const gm = geom[i];
      if (gm.row !== row){
        const prev = geom.filter(x => x.row === row);
        rowTop += Math.max(...prev.map(x => x.h)) + 30 + 18;
        row = gm.row;
      }
      const x = PAD + gm.col * (cw + 18);
      ctx.font = "500 20px " + MONO; ctx.fillStyle = C.accent;
      ctx.fillText((g.tf || "chart").toUpperCase(), x, rowTop + 20);
      ctx.save();
      roundRect(ctx, x, rowTop + 30, cw, gm.h, 10); ctx.clip();
      ctx.drawImage(g.im, x, rowTop + 30, cw, gm.h);
      ctx.restore();
      ctx.strokeStyle = C.line; ctx.lineWidth = 1;
      roundRect(ctx, x, rowTop + 30, cw, gm.h, 10); ctx.stroke();
    });
    const last = geom.filter(x => x.row === row);
    y = rowTop + Math.max(...last.map(x => x.h)) + 30 + 18;
  }

  /* ---- підпис ---- */
  ctx.font = "20px " + MONO; ctx.fillStyle = C.faint;
  ctx.fillText(T.tiMadeIn, PAD, H - PAD + 6);

  return cv;
}

/* ---------- вікно ---------- */
async function openTradeImage(id){
  const t = (S.all.length ? S.all : S.trades).find(x => x.id === id);
  if (!t) return;

  openModal('<div class="m-head"><b>' + T.tiTitle + '</b><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">Закрити</button></div>'
    + '<div class="m-body"><div class="sharewrap" id="tiWrap">'
    + '<div class="empty">' + T.tiDrawing + '</div></div></div>'
    + '<div class="m-foot"><button class="btn go" id="tiCopy">' + T.tiCopy + '</button>'
    + '<button class="btn" id="tiSave">' + T.tiSave + '</button>'
    + '<span class="sp"></span><span class="hint" id="tiMsg"></span></div>');

  let cv;
  try{ cv = await buildTradeImage(t); }
  catch(e){
    const w = document.getElementById("tiWrap");
    if (w) w.innerHTML = '<div class="empty">' + T.tiFail + esc(e.message) + "</div>";
    return;
  }
  const wrap = document.getElementById("tiWrap");
  if (!wrap) return;
  wrap.innerHTML = "";
  cv.style.width = "100%"; cv.style.height = "auto"; cv.style.display = "block";
  cv.style.borderRadius = "10px";
  wrap.appendChild(cv);

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
    a.download = "trade-" + (t.pair || "") + "-" + (t.date || "").slice(0, 10) + ".png";
    a.click();
    msg(T.tiSaved);
  };
}

window.__tradeImg = {open: openTradeImage};

})();
