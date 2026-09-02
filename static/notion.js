/* ============================================================
   Перенесення журналу з Notion.

   Людина рік вела журнал у Notion — руками сюди вона його не
   перенесе. Тут майстер на три кроки: посилання → звірка
   колонок → перенесення разом зі скрінами й нотатками.

   Ніяких ключів і інтеграцій: потрібне звичайне посилання на
   опубліковану сторінку. Живе окремим файлом, у чужий код
   не лізе — підмінює глобальну openImport() і додає в те саме
   вікно другу вкладку.
   ============================================================ */
(function(){

const PAIRS_KEY = "statsai_pairs";     // інструменти, що приїхали з імпорту
const SEEN_KEY  = "statsai_import_offered";

let state = null;      // що сервер пам'ятає з минулого разу
let link = "";         // посилання на базу
let title = "";        // як база зветься в Notion
let mapping = {};      // наше поле -> колонка Notion
let columns = [];      // колонки бази
let sample = [];       // перші рядки для перегляду
let total = 0;
let poll = 0;
let tables = [];       // усі таблиці, які знайшли за посиланням
let picked = [];       // які з них переносимо
let chosen = null;     // за якою звіряємо колонки
let batch = null;      // остання партія — її можна скасувати
let connected = false; // чи вже підключали Notion раніше — міняє статус у рядку «Підключення»

/* Рядок у розділі «Підключення»: статус текстом (Підключено/Не
   підключено), без блимаючих індикаторів. Викликається і звідси, і з
   i18n.js після зміни мови, щоб статус лишався правильним. */
function paintBtn(){
  const nb = document.getElementById("notionBtn");
  if (!nb) return;
  const st = document.getElementById("notionStatus");
  nb.classList.toggle("connected", connected);
  if (st) st.textContent = connected ? T.connConnected : T.connNotConnected;
  nb.setAttribute("data-tip", connected ? T.sdNotionConnectedTip : T.sdNotionTip);
}

/* ---- інструменти з імпорту показуємо в підказках форми ---- */
function rememberPairs(list){
  if (!list || !list.length) return;
  let saved = [];
  try{ saved = JSON.parse(localStorage.getItem(PAIRS_KEY) || "[]"); }catch(e){}
  const all = [...new Set([...saved, ...list])];
  try{ localStorage.setItem(PAIRS_KEY, JSON.stringify(all)); }catch(e){}
  applyPairs(all);
}
/* Той самий розбір, що й на сервері: «US100 (1)» і «US100 (2)» — це один
   інструмент. Інакше у формі нової угоди підказки роздвоюються. */
function tidyPair(v){
  let s = String(v || "").trim().replace(/\\/g, "/").replace(/\s+/g, " ");
  let prev = null;
  while (prev !== s){
    prev = s;
    s = s.replace(/\s*[([]\s*\d{1,2}\s*[)\]]\s*$|\s+#\d{1,2}\s*$|\s+\d\s*$/, "").trim();
  }
  /* кириличні двійники латинських літер: «USD\САD» оком не відрізнити,
     а це вже інший інструмент. Міняємо лише коли виходить тикер. */
  const LOOK = {"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P",
                "С":"C","Т":"T","У":"Y","Х":"X","І":"I","а":"a","е":"e","о":"o",
                "р":"p","с":"c","у":"y","х":"x","і":"i"};
  const swapped = [...s].map(ch => LOOK[ch] || ch).join("");
  const ticker = /^[A-Za-z0-9./-]{2,12}$/;
  if (ticker.test(swapped)) s = swapped;
  return ticker.test(s) ? s.toUpperCase() : s;
}

function applyPairs(list){
  if (typeof PAIRS_ACTIVE === "undefined") return;
  for (const raw of list){
    const p = tidyPair(raw);
    if (p && !PAIRS_ACTIVE.includes(p)) PAIRS_ACTIVE.push(p);
  }
}

/* Підказки будуємо з журналу, а не лише зі старого списку: якщо в базі
   назви вже звели докупи, підказки підуть слідом самі. */
function pairsFromJournal(){
  if (typeof S === "undefined" || !S.all) return [];
  return [...new Set(S.all.map(t => tidyPair(t.pair)).filter(Boolean))];
}

try{
  const saved = JSON.parse(localStorage.getItem(PAIRS_KEY) || "[]");
  const tidy = [...new Set(saved.map(tidyPair).filter(Boolean))];
  if (tidy.length !== saved.length || tidy.some((v, i) => v !== saved[i]))
    localStorage.setItem(PAIRS_KEY, JSON.stringify(tidy));   // чистимо старий список
  applyPairs(tidy);
}catch(e){}

window.addEventListener("load", () => setTimeout(() => applyPairs(pairsFromJournal()), 1500));

/* ---------- звернення до сервера ---------- */
async function call(method, url, body){
  const res = await fetch(url, {
    method,
    headers: {"Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try{ data = await res.json(); }catch(e){}
  if (!res.ok) throw new Error(data.error || (T.ntServerReplied + " " + res.status));
  return data;
}

/* ---------- каркас вікна ---------- */
function box(){ return document.getElementById("modalBox"); }

function paint(bodyHtml, footHtml){
  const b = box(); if (!b) return;
  b.querySelector(".m-body").innerHTML = bodyHtml;
  b.querySelector(".m-foot").innerHTML = footHtml;
}

function err(msg){
  const b = box(); if (!b) return;
  let n = b.querySelector(".nt-err");
  if (!n){
    n = document.createElement("div");
    n.className = "nt-err";
    b.querySelector(".m-body").prepend(n);
  }
  n.textContent = msg;
}

function busy(sel, text){
  const el = document.querySelector(sel);
  if (el){ el.disabled = true; el.textContent = text; }
}

/* ---------- крок 1: посилання ---------- */
function stepLink(){
  paint(
    '<div class="nt">'
    + '<p class="nt-lead">' + T.ntStep1Lead + '</p>'
    + '<ol class="nt-steps">'
    + '<li>' + T.ntStep1Li1 + '</li>'
    + '<li>' + T.ntStep1Li2 + '</li>'
    + '</ol>'
    + '<label class="nt-lab">' + T.ntLinkLabel + '</label>'
    + '<input id="ntUrl" class="nt-inp" type="url" autocomplete="off" spellcheck="false"'
    +   ' value="' + esc(link) + '" placeholder="https://…notion.site/…">'
    + '<p class="nt-note">' + T.ntLinkNote + '</p>'
    + lastHtml()
    + '</div>',
    '<span class="sp"></span><button class="btn" onclick="closeModal()">' + T.fmCancel + '</button>'
    + '<button class="btn primary" id="ntGo">' + T.ntReadBtn + '</button>'
  );
  const input = document.getElementById("ntUrl");
  const go = () => read((input.value || "").trim());
  document.getElementById("ntGo").onclick = go;
  input.onkeydown = e => { if (e.key === "Enter") go(); };
  input.focus();
}

async function read(url){
  if (!url) return err(T.ntPasteLink);
  busy("#ntGo", T.ntReading);
  let r;
  try{
    r = await call("POST", "/api/notion/preview", {url});
  }catch(e){
    err(e.message);
    const b = document.getElementById("ntGo");
    if (b){ b.disabled = false; b.textContent = T.ntReadBtn; }
    return;
  }
  link = url;
  soak(r);
  tables = r.tables || [];
  picked = tables.filter(t => t.matched >= 3);
  if (!picked.length && tables.length) picked = [tables[0]];
  /* Журнал часто розбитий по місяцях: один рік — дванадцять таблиць.
     Тоді спершу показуємо, що знайшли, і даємо обрати. */
  if (tables.length > 1) return stepTables(r.notes || []);
  drawMap();
}

function soak(r){
  title = r.title || "";
  mapping = r.mapping || {};
  columns = r.columns || [];
  sample = r.rows || [];
  total = r.total || 0;
  chosen = r.chosen || chosen;
  if (r.fields) state = Object.assign(state || {}, {fields: r.fields});
}

/* Останнє перенесення можна скасувати — і зараз, і згодом.
   Без цього будь-яка помилка у звірці колонок необоротна. */
function lastHtml(){
  const l = state && state.last;
  if (!l || !l.id) return "";
  return '<div class="nt-safe"><p>' + T.ntLastImportPrefix + ' <b>' + (l.count || 0)
    + "</b> " + T.wordTradeMany + (l.when ? ", " + esc(l.when) : "") + ". " + T.ntLastImportUndo + "</p>"
    + '<button class="btn" onclick="__notion.undo(\'' + l.id + '\')">' + T.ntCancelImport + '</button></div>';
}

/* Скільки вже лежить у журналі — щоб перенесені не змішалися з чужими
   непомітно. Найчастіше це демо-угоди, з якими журнал приїхав. */
function haveHtml(){
  const n = (typeof S !== "undefined" && S.all) ? S.all.length : 0;
  if (!n) return "";
  return '<p class="nt-note">' + T.ntHaveAlready + ' <b>' + n + "</b> " + T.wordTradeMany + " " + T.ntHaveWillAdd + "</p>";
}

/* ---------- крок 2: яку таблицю переносимо ---------- */
function stepTables(notes){
  const same = (a, b) => a && b && a.collection === b.collection;
  const rows = tables.map((t, i) => {
    const on = picked.some(p => same(p, t));
    const name = esc(t.title || T.ntNoTitle)
      + (t.path && t.path !== t.title ? ' <em>' + esc(t.path) + "</em>" : "");
    return '<label class="nt-tbl-row' + (on ? " on" : "") + '">'
      + '<input type="checkbox"' + (on ? " checked" : "")
      + ' onchange="__notion.pickTable(' + i + ', this.checked)">'
      + '<b>' + name + "</b>"
      + '<span>' + (t.rows || 0) + " " + T.ntRowsWord + "</span>"
      + '<i>' + (t.matched >= 3 ? T.ntLooksLikeJournal : T.ntFieldsWord + ": " + t.matched) + "</i></label>";
  }).join("");

  paint(
    '<div class="nt">'
    + '<p class="nt-lead">' + T.ntFoundTablesPrefix + ' <b>' + tables.length
    + "</b>. " + T.ntFoundTablesHint + "</p>"
    + (notes.length ? '<p class="nt-note">' + notes.map(esc).join(". ") + ".</p>" : "")
    + '<div class="nt-tbls">' + rows + "</div>"
    + '</div>',
    '<button class="btn ghost" onclick="__notion.back()">' + T.ntOtherLink + '</button>'
    + '<span class="sp"></span><button class="btn" onclick="__notion.allTables()">' + T.ntMarkAll + '</button>'
    + '<button class="btn primary" id="ntNext" onclick="__notion.toMap()">' + T.ntNext + '</button>'
  );
}

async function toMap(){
  if (!picked.length) return err(T.ntMarkOneTable);
  busy("#ntNext", T.ntReading);
  const best = picked.slice().sort((a, b) => b.matched - a.matched)[0];
  try{
    soak(await call("POST", "/api/notion/preview", {url: link, table: best}));
  }catch(e){ return err(e.message); }
  drawMap();
}

/* ---------- крок 2: звірка колонок ---------- */
function drawMap(){
  const fields = (state && state.fields) || [];
  const opts = (cur) => '<option value="">' + T.ntDontTransfer + '</option>'
    + columns.map(c => '<option value="' + esc(c.name) + '"'
        + (c.name === cur ? " selected" : "") + ">" + esc(c.name)
        + " · " + esc(c.type) + "</option>").join("");

  const rowsHtml = fields.map(f =>
    '<div class="nt-row"><span>' + esc(f.label) + "</span>"
    + '<select data-f="' + f.k + '" onchange="__notion.setMap(this)">' + opts(mapping[f.k]) + "</select></div>"
  ).join("");

  const found = fields.filter(f => mapping[f.k]).length;
  const what = (title ? "«" + esc(title) + "»" : T.ntTableWord)
             + (total ? ", " + T.ntRowsWord + ": " + total : "");

  /* Показуємо, що лишилось поза журналом — щоб було видно, що нічого
     не загубилось, і за потреби можна це кудись покласти. */
  const taken = new Set(fields.map(f => mapping[f.k]).filter(Boolean));
  const left = columns.filter(c => !taken.has(c.name)).map(c => c.name);
  const leftHtml = left.length
    ? '<p class="nt-note">' + T.ntNotIncluded + ' ' + left.map(esc).join(", ")
      + ". " + T.ntNotIncludedHint + "</p>"
    : "";

  const many = picked.length > 1
    ? '<p class="nt-note">' + T.ntTransferFromPrefix + ' ' + picked.length
      + " " + T.ntTablesWord + ". " + T.ntColumnsMatchedBy + " «" + esc(title)
      + "»; " + T.ntColumnsMatchedByRest + "</p>"
    : "";

  paint(
    '<div class="nt">'
    + '<p class="nt-lead">' + what + ". " + T.ntColumnsAutoMatched + " <b>" + found + " " + T.ntOfWord + " "
    + fields.length + "</b>. " + T.ntCheckAndFix + "</p>"
    + many
    + '<div class="nt-map">' + rowsHtml + "</div>"
    + leftHtml
    + '<div class="nt-sub">' + T.ntPreviewTitle + '</div>'
    + '<div class="nt-prev">' + preview() + "</div>"
    + haveHtml()
    + safeHtml()
    + '<div class="nt-opts">'
    +   optChk("ntNotes", T.ntOptNotes, true)
    +   optChk("ntShots", T.ntOptShots, true)
    +   optChk("ntSkip",  T.ntOptSkip, true)
    + "</div></div>",
    '<button class="btn ghost" onclick="__notion.' + (tables.length > 1 ? "toTables" : "back")
    + '()">' + (tables.length > 1 ? T.ntOtherTable : T.ntOtherLink) + "</button>"
    + '<span class="sp"></span><button class="btn" onclick="closeModal()">' + T.fmCancel + '</button>'
    + '<button class="btn primary" id="ntRun" onclick="__notion.run()">' + T.ntTransferAll + '</button>'
  );
}

/* Відкату в імпорту немає, тому копію журналу пропонуємо саме тут —
   за крок до того, як вона знадобиться. */
function safeHtml(){
  if (typeof exportData !== "function") return "";
  return '<div class="nt-safe"><p>' + T.ntBackupHint + "</p>"
    + '<button class="btn" onclick="exportData()">' + T.ntSaveBackup + '</button></div>';
}

function optChk(id, label, on){
  return '<label class="nt-chk"><input type="checkbox" id="' + id + '"'
       + (on ? " checked" : "") + "><span>" + esc(label) + "</span></label>";
}

function preview(){
  if (!sample.length) return '<div class="nt-empty">' + T.ntNoRowsInTable + '</div>';
  const cell = v => esc(v === null || v === undefined || v === "" ? "—" : String(v));
  return '<table class="nt-tbl"><thead><tr>'
    + "<th>" + T.fDate + "</th><th>" + T.fPair + "</th><th>" + T.fPosition + "</th><th>" + T.fResult + "</th><th>RR</th><th>" + T.fRisk + "</th>"
    + "</tr></thead><tbody>"
    + sample.map(t => "<tr><td>" + cell((t.date || "").replace("T", " "))
        + "</td><td>" + cell(t.pair) + "</td><td>" + cell(t.position)
        + "</td><td>" + cell(t.result) + "</td><td>" + cell(t.rr)
        + "</td><td>" + cell(t.risk) + "</td></tr>").join("")
    + "</tbody></table>";
}

/* ---------- крок 3: перенесення ---------- */
async function run(){
  if (!mapping.pair) return err(T.ntNeedPairColumn);
  const opts = {
    notes: document.getElementById("ntNotes").checked,
    shots: document.getElementById("ntShots").checked,
    skipExisting: document.getElementById("ntSkip").checked,
  };
  busy("#ntRun", T.ntTransferring);
  let job;
  try{
    job = await call("POST", "/api/notion/import",
      {url: link, title, mapping, tables: picked, options: opts});
  }catch(e){ return err(e.message); }
  batch = job.batch || job.id;
  watch(job.id);
}

function watch(jid){
  drawProgress({state: "running", step: T.ntPreparing, done: 0, total: 0});
  clearInterval(poll);
  poll = setInterval(async () => {
    let j;
    try{ j = await call("GET", "/api/notion/job/" + jid); }
    catch(e){ clearInterval(poll); return err(e.message); }
    if (j.state === "running") return drawProgress(j);
    clearInterval(poll);
    if (j.state === "error") return drawProgress(j);
    await finish(j);
  }, 700);
}

function drawProgress(j){
  const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
  const bad = j.state === "error";
  paint(
    '<div class="nt">'
    + (bad ? '<div class="nt-err">' + esc(j.error) + "</div>"
           : '<p class="nt-lead">' + T.ntTransferringHint + "</p>")
    + '<div class="nt-bar"><i style="width:' + pct + '%"></i></div>'
    + '<div class="nt-prog"><b>' + (j.total ? j.done + " " + T.ntOfWord + " " + j.total : "…") + "</b>"
    + "<span>" + esc(j.step || "") + "</span></div>"
    + '</div>',
    bad ? '<span class="sp"></span><button class="btn" onclick="__notion.back()">' + T.ntTryAgain + '</button>'
        : '<span class="sp"></span><button class="btn" disabled>' + T.ntInProgress + '</button>'
  );
}

async function finish(j){
  rememberPairs(j.newAssets);
  connected = true; paintBtn();
  try{ await reload(); render(); }catch(e){}

  const line = (k, v) => '<div class="nt-stat"><b>' + v + "</b><span>" + k + "</span></div>";
  const warn = (j.warnings || []).length
    ? '<div class="nt-sub">' + T.ntWhatFailed + '</div><ul class="nt-warn">'
      + j.warnings.map(w => "<li>" + esc(w) + "</li>").join("") + "</ul>"
    : "";
  const assets = (j.newAssets || []).length
    ? '<div class="nt-sub">' + T.ntNewAssets + '</div><div class="nt-tags">'
      + j.newAssets.map(a => "<i>" + esc(a) + "</i>").join("") + "</div>"
      + '<p class="nt-note">' + T.ntNewAssetsHint + '</p>'
    : "";

  const back = (j.batch && j.added)
    ? '<button class="btn ghost" onclick="__notion.undo(\'' + j.batch + '\')">' + T.ntCancelImport + '</button>'
    : "";

  paint(
    '<div class="nt"><p class="nt-lead">' + T.ntDone + '.</p>'
    + '<div class="nt-stats">' + line(T.ntTransferred, j.added)
      + line(T.ntSkipped, j.skipped) + line(T.ntShotsWord, j.shots) + "</div>"
    + assets + warn
    + (j.added ? '<p class="nt-note">' + T.ntSomethingWrong + "</p>" : "")
    + "</div>",
    back + '<span class="sp"></span>'
    + '<button class="btn primary" onclick="closeModal()">' + T.mrClose + '</button>'
  );
}

/* ---------- вкладки у вікні імпорту ---------- */
let fileHtml = null;

function remember(){
  const b = box();
  if (b) fileHtml = {body: b.querySelector(".m-body").innerHTML,
                     foot: b.querySelector(".m-foot").innerHTML};
}

function tabs(active){
  const b = box(); if (!b) return;
  const head = b.querySelector(".m-head");
  if (!head) return;
  let t = head.querySelector(".nt-tabs");
  if (!t){
    t = document.createElement("div");
    t.className = "nt-tabs";
    t.innerHTML = '<button data-t="file" onclick="__notion.tab(\'file\')">' + T.ntTabFile + '</button>'
                + '<button data-t="notion" onclick="__notion.tab(\'notion\')">Notion</button>';
    head.querySelector("h2").after(t);
  }
  t.querySelectorAll("button").forEach(x => x.classList.toggle("on", x.dataset.t === active));
}

function tab(which){
  const b = box(); if (!b) return;
  tabs(which);
  if (which === "file"){
    clearInterval(poll);
    if (fileHtml){
      b.querySelector(".m-body").innerHTML = fileHtml.body;
      b.querySelector(".m-foot").innerHTML = fileHtml.foot;
      const f = document.getElementById("impFile");
      if (f) f.addEventListener("change", onImpFile);
    }
    return;
  }
  openNotion();
}

/* ---------- вхід ---------- */
async function openNotion(){
  if (typeof DEMO !== "undefined" && DEMO){
    return paint('<div class="nt"><div class="nt-err">' + T.ntDemoUnavailable + '</div></div>',
      '<span class="sp"></span><button class="btn" onclick="closeModal()">' + T.ntGotIt + '</button>');
  }
  paint('<div class="nt"><p class="nt-lead">' + T.ntOneMoment + '</p></div>', "");
  try{
    state = await call("GET", "/api/notion/state");
    link = state.url || link;
  }catch(e){
    return paint('<div class="nt"><div class="nt-err">' + esc(e.message) + "</div></div>",
      '<span class="sp"></span><button class="btn" onclick="closeModal()">' + T.mrClose + '</button>');
  }
  stepLink();
}

function open(){
  if (typeof openImport !== "function") return;
  openImport();          // малює рідне вікно імпорту
  remember();
  tab("notion");
}

async function undo(id){
  if (!await Ask.yes(T.ntConfirmUndo, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
  let r;
  try{ r = await call("POST", "/api/notion/undo/" + id, {}); }
  catch(e){ return err(e.message); }
  batch = null;
  try{ state = await call("GET", "/api/notion/state"); }catch(e){}
  try{ await reload(); render(); }catch(e){}
  paint('<div class="nt"><p class="nt-lead">' + T.ntUndoneCount + ' <b>' + (r.removed || 0)
    + "</b>. " + T.ntUndoneHint + "</p></div>",
    '<span class="sp"></span>'
    + '<button class="btn" onclick="__notion.back()">' + T.ntTryAgain + '</button>'
    + '<button class="btn primary" onclick="closeModal()">' + T.mrClose + '</button>');
}

window.__notion = {
  open, tab, run, toMap, undo,
  back: stepLink,
  toTables(){ stepTables([]); },
  pickTable(i, on){
    const t = tables[i];
    picked = picked.filter(p => p.collection !== t.collection);
    if (on) picked.push(t);
  },
  allTables(){ picked = tables.slice(); stepTables([]); },
  setMap(sel){ const f = sel.dataset.f; if (sel.value) mapping[f] = sel.value; else delete mapping[f]; },
  refreshBtn: paintBtn,
  refreshState: checkState,
};

/* Рідну кнопку «Імпорт» лишаємо на місці — просто додаємо в те саме
   вікно другу вкладку. */
const origOpenImport = window.openImport;
window.openImport = function(){
  origOpenImport.apply(this, arguments);
  remember();
  tabs("file");
};

/* Один раз після реєстрації пропонуємо перенести журнал — щоб новачок не
   сидів перед порожнім екраном і не забивав угоди руками. Раніше рішення
   трималось лише на localStorage — на новому браузері чи після його
   очищення вікно вилазило знов, навіть якщо угоди вже давно перенесені.
   Тепер головний критерій — чи є в акаунті хоч одна угода: є хоч одна —
   людина вже не новачок, більше не пропонуємо, з якого б пристрою вона
   не зайшла. Кнопка в сайдбарі водночас оновлює підпис на «підключено». */
/* Перевірка стану на сервері — і для кнопки/статусу, і для рішення
   про автопоказ вікна нижче. Викликається також вручну (refreshState),
   коли розділ «Підключення» розкривають — раптом підключили деінде. */
async function checkState(){
  if (typeof DEMO !== "undefined" && DEMO) return;
  try{
    state = await call("GET", "/api/notion/state");
    link = state.url || link;
    connected = !!(state.url || (state.last && state.last.id) || state.imported);
    paintBtn();
  }catch(e){}
}

window.addEventListener("load", () => {
  setTimeout(async () => {
    await checkState();

    let seen = "1";
    try{ seen = localStorage.getItem(SEEN_KEY) || ""; }catch(e){}
    if (seen === "1") return;
    if (typeof S !== "undefined" && S.trades && S.trades.length){
      try{ localStorage.setItem(SEEN_KEY, "1"); }catch(e){}
      return;
    }
    try{ localStorage.setItem(SEEN_KEY, "1"); }catch(e){}
    open();
  }, 1200);
});

})();
