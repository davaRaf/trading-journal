/* ============================================================
   Розділ «Аналіз дня».

   Не цифри дня, а розбір: що людина побачила на графіку зранку,
   який був план — і як ринок це відпрацював.

   Живе окремим файлом і сам додає себе у VIEWS, як «Новини» й
   «Моя ТС».

   Активів у дні може бути кілька: US100 і GER40 зранку розбирають
   окремо, і план у кожного свій. Тому запис дня — це список карток
   активів, у кожної свої скріни по таймфреймах, напрям, рівні,
   сценарії, а ввечері — свій факт і свої оцінки. Спільне на день
   лише одне — правила «чого не робити» і висновок.

   Два вигляди одного дня:
     • день іде   — картки активів одна під одною, під ними правила
                    дня і кнопка «записати підсумок»;
     • день закрито — кожна картка стає розворотом: ліворуч план як
                    був, праворуч факт; унизу підсумок по активах.

   Усе, що набрано, лягає в базу (day_store.py). Оцінки «ринок пішов
   за планом» і «тримався плану» ставляться по кожному активу, а для
   статистики за місяць зводяться в одну оцінку дня.

   Старі записи (один актив без назви) читаються як є: при завантаженні
   вони загортаються в одну картку.
   ============================================================ */
(function(){

let DATE = null;        /* який день дивимось, YYYY-MM-DD */
let N = undefined;      /* розбір дня: undefined — ще не питали, null — немає */
let STATS = null;       /* підсумок за 30 днів */
let DAYS = null;        /* які дні розібрані — для календаря */
let hotShot = null;
let calOpen = false, calMonth = null;   /* міні-календар: відкритий? який місяць */
let popOpen = false;                    /* вибір активу */
let tfEdit = null;                      /* який таймфрейм зараз вибирають (шлях) */
let armed = null;                       /* слот, куди піде Ctrl+V (шлях) */

/* На телефоні буфера обміну для картинок немає, тому там дотик має одразу
   відкривати файли. На комп'ютері — навпаки: один клік націлює слот. */
function touchOnly(){
  return window.matchMedia && matchMedia("(hover: none)").matches;
}

const TFS = ["1W", "1D", "4H", "1H", "30M", "15M", "5M", "3M", "1M"];

function D(){ return DICT[window.LANG] || DICT.uk; }
function iso(d){
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
       + "-" + String(d.getDate()).padStart(2, "0");
}
function shift(days){
  const [y, m, d] = DATE.split("-").map(Number);
  goto(iso(new Date(y, m - 1, d + days)));
}
function goto(date){
  DATE = date; N = undefined; calOpen = false; popOpen = false; tfEdit = null;
  render();
}

/* ---------------- форма запису ---------------- */
function blank(){
  return {closed: false, assets: [], skip: "", fact: {}, marks: {}, trades: {}};
}
function blankAsset(nm, fromTs){
  return {nm: nm || "", ts: !!fromTs, side: "", why: "", shots: [],
          levels: [{}, {}], plans: [{}, {}], eve: {shots: [], text: ""}, marks: {}};
}
function fixAsset(a){
  a.shots = a.shots || []; a.levels = a.levels || []; a.plans = a.plans || [{}, {}];
  a.eve = a.eve || {}; a.eve.shots = a.eve.shots || []; a.marks = a.marks || {};
  return a;
}
/* Запис, зроблений до появи активів, — це один актив без назви.
   Загортаємо його в картку, нічого не втрачаючи. */
function normalize(n){
  if (!n) return n;
  if (Array.isArray(n.assets)){ n.assets.forEach(fixAsset); return n; }
  const a = fixAsset({nm: "", ts: false,
    side: (n.bias || {}).side || "", why: (n.bias || {}).why || "",
    shots: [], levels: n.levels || [], plans: n.plans || [{}, {}],
    eve: {shots: [], text: (n.fact || {}).text || ""},
    marks: {match: (n.marks || {}).match || "", hold: (n.marks || {}).hold || ""}});
  const sh = n.shots || {};
  if (sh.plan) a.shots.push({tf: "", file: sh.plan});
  if (sh.fact) a.eve.shots.push({tf: "", file: sh.fact});
  n.assets = [a];
  delete n.bias; delete n.levels; delete n.plans; delete n.shots;
  if (n.fact) delete n.fact.text;
  return n;
}

/* Оцінка дня для статистики: усі активи «так» — день «так», усі «ні» —
   «ні», інакше «частково». Саме це лягає в колонки match_mark/hold_mark. */
function rollMarks(){
  const d = D();
  const roll = k => {
    const v = (N.assets || []).map(a => (a.marks || {})[k]).filter(Boolean);
    if (!v.length) return "";
    if (v.every(x => x === d.yes)) return d.yes;
    if (v.every(x => x === d.no)) return d.no;
    return d.partly;
  };
  N.marks = {match: roll("match"), hold: roll("hold")};
}

/* У публічному демо сервера немає — розбори дня живуть у браузері,
   як і угоди. Скрін там лишається картинкою всередині запису:
   класти його нікуди. */
const DEMO_KEY = "statsai_day_demo";
function demo(){ return typeof DEMO !== "undefined" && DEMO; }
function demoAll(){
  try{ return JSON.parse(localStorage.getItem(DEMO_KEY) || "{}"); }catch(e){ return {}; }
}

async function load(){
  const want = DATE;
  if (demo()){
    N = normalize(demoAll()[want] || null);
    /* Перемальовуємо не одразу: у демо дані лежать у браузері й читаються
       миттєво, тому виклик прилітає всередину того самого render(), який
       нас і покликав, — і його результат затирає наш. Через таймер розділ
       домальовується вже після нього. */
    setTimeout(() => { if (S.view === "day") render(); }, 0);
    return;
  }
  try{
    const r = await api("GET", "/api/day/" + want);
    if (DATE !== want) return;                 /* встигли перегорнути далі */
    N = normalize(r.day || null);
  }catch(e){ N = null; }
  if (S.view === "day") render();
}

async function loadStats(){
  if (demo()){
    const all = demoAll();
    STATS = Object.keys(all).map(k => ({date: k, data: all[k],
      match: (all[k].marks || {}).match || "", hold: (all[k].marks || {}).hold || ""}));
    setTimeout(() => { if (S.view === "day") render(); }, 0);
    return;
  }
  try{
    const r = await api("GET", "/api/day/stats");
    STATS = r.notes || [];
  }catch(e){ STATS = []; }
  if (S.view === "day") render();
}

/* Які дні вже розібрані — щоб календар знав, де ставити крапки. */
async function loadDays(){
  if (demo()){
    const all = demoAll();
    DAYS = Object.keys(all).map(k => ({date: k, match: (all[k].marks || {}).match || ""}));
    setTimeout(() => { if (S.view === "day") render(); }, 0);
    return;
  }
  try{
    const r = await api("GET", "/api/day/list");
    DAYS = r.days || [];
  }catch(e){ DAYS = []; }
  if (S.view === "day") render();
}

let saveTimer = null;
function save(){
  /* гість може все розглядати, але не записувати: щойно він спробував
     зберегти значення — кличемо завести свій журнал */
  if (window.Guest && Guest.block(T.gsGateTitle)) return;
  rollMarks();
  STATS = null; DAYS = null;                   /* підсумок і календар перерахуються */
  if (demo()){
    const all = demoAll();
    all[DATE] = N;
    try{ localStorage.setItem(DEMO_KEY, JSON.stringify(all)); }catch(e){}
    return;
  }
  clearTimeout(saveTimer);
  const date = DATE, body = N;
  saveTimer = setTimeout(() => {
    api("POST", "/api/day/" + date, {day: body}).catch(() => {});
  }, 400);
}

/* ---------------- шлях до поля ---------------- */
function get(path){
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), N);
}
function set(path, val){
  const keys = path.split(".");
  let o = N;
  for (let i = 0; i < keys.length - 1; i++){
    if (o[keys[i]] == null) o[keys[i]] = /^\d+$/.test(keys[i + 1]) ? [] : {};
    o = o[keys[i]];
  }
  o[keys[keys.length - 1]] = val;
}

function ed(path, ph, multi){
  const v = get(path);
  return '<span class="dv-f' + (v ? "" : " blank") + (multi ? " wide" : "")
    + '" data-p="' + path + '"' + (multi ? ' data-multi="1"' : "") + ">"
    + (v ? esc(v).replace(/\n/g, "<br>") : esc(ph)) + "</span>";
}

/* ---------------- скріни по таймфреймах ---------------- */
/* Одна комірка: чіп таймфрейму зверху, під ним слот. Шлях веде до
   об'єкта {tf, file} у списку скрінів активу. */
function shotCell(path, cap, readOnly){
  const d = D();
  const s = get(path) || {};
  const tfPath = path + ".tf";
  let chip;
  if (readOnly){
    chip = '<span class="dv-tfc' + (s.tf ? "" : " pick") + '">' + esc(s.tf || "—") + "</span>";
  } else if (tfEdit === tfPath){
    /* список звичних таймфреймів, а поруч поле — вписати свій: у людей
       трапляються і 2H, і 45m, і назва словом */
    chip = '<span class="dv-tfpick">' + TFS.map(t =>
        '<button type="button" onclick="__dv.tf(\'' + tfPath + "','" + t + '\')">' + t + "</button>").join("")
      + '<input class="own" id="dvTf" value="' + esc(s.tf || "") + '" placeholder="' + esc(d.tfOwn)
      + '" aria-label="' + esc(d.tfOwn) + '">'
      + '<button type="button" class="x" onclick="__dv.tf(\'' + tfPath + '\',null)">×</button></span>';
  } else {
    chip = '<button type="button" class="dv-tfc' + (s.tf ? "" : " pick") + '" onclick="__dv.tfEdit(\''
      + tfPath + '\')">' + esc(s.tf || d.tfPick) + "</button>";
  }
  const f = s.file;
  const slot = path + ".file";
  const on = armed === slot;
  return '<div class="dv-tf"><div class="cap">' + chip + "</div>"
    + '<div class="dv-shot' + (f ? " has" : "") + (readOnly ? " ro" : "") + (on ? " armed" : "")
    + '" data-shot="' + slot + '">'
    + (f ? '<img alt="" src="' + esc(/^data:/.test(f) ? f : "/dnshot/" + f) + '">'
           + (readOnly ? "" : '<button class="rm" type="button">×</button>')
         : '<div class="ph"><b>+</b>' + esc(cap) + "<em>"
           + esc(on ? d.shotArmed : d.shotHint) + "</em></div>")
    + "</div></div>";
}
/* Порожня комірка «ще один таймфрейм»: вставиш скрін — з'явиться запис. */
function shotAdd(listPath, cap){
  const d = D();
  const slot = listPath + ".+";
  const on = armed === slot;
  return '<div class="dv-tf add"><div class="cap"><span class="dv-tfc pick">+ ' + esc(d.addTf) + "</span></div>"
    + '<div class="dv-shot' + (on ? " armed" : "") + '" data-shot="' + slot + '">'
    + '<div class="ph"><b>+</b>' + esc(cap) + "<em>"
    + esc(on ? d.shotArmed : d.shotHint) + "</em></div></div></div>";
}
function shotsRow(listPath, cap, readOnly){
  const list = get(listPath) || [];
  const cells = list.map((_, i) => shotCell(listPath + "." + i, cap, readOnly));
  if (!readOnly) cells.push(shotAdd(listPath, cap));
  if (readOnly && !cells.length) return '<div class="hint">' + esc(D().noShots) + "</div>";
  return '<div class="dv-tfs">' + cells.join("") + "</div>";
}

function shrink(url, cb){
  const im = new Image();
  im.onload = () => {
    const k = Math.min(1, 1400 / im.width);
    const c = document.createElement("canvas");
    c.width = Math.round(im.width * k);
    c.height = Math.round(im.height * k);
    c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
    try{ cb(c.toDataURL("image/jpeg", .86)); }catch(e){ cb(url); }
  };
  im.onerror = () => cb(url);
  im.src = url;
}

/* Куди кладемо файл: або в наявний запис (…shots.2.file), або в новий
   (…shots.+) — тоді запис створюємо. */
function place(path, file){
  if (path.endsWith(".+")){
    const listPath = path.slice(0, -2);
    if (!Array.isArray(get(listPath))) set(listPath, []);
    get(listPath).push({tf: "", file: file});
  } else {
    set(path, file);
  }
}
function removeShot(path){
  /* path = …shots.2.file → прибираємо сам запис 2 */
  const m = path.match(/^(.*)\.(\d+)\.file$/);
  if (m){
    const arr = get(m[1]);
    if (Array.isArray(arr)) arr.splice(Number(m[2]), 1);
  } else {
    set(path, "");
  }
}

async function upload(el, dataUrl){
  const path = el.dataset.shot;
  armed = null;
  if (demo()){
    place(path, dataUrl);
    save(); render();
    return;
  }
  el.classList.add("busy");
  try{
    const r = await api("POST", "/api/day/shot", {data: dataUrl});
    place(path, r.file);
    save();
  }catch(e){}
  el.classList.remove("busy");
  render();
}
function takeFile(file, el){
  if (!file || !/^image\//.test(file.type)) return;
  const fr = new FileReader();
  fr.onload = () => shrink(fr.result, u => upload(el, u));
  fr.readAsDataURL(file);
}

const filePick = document.createElement("input");
filePick.type = "file"; filePick.accept = "image/*"; filePick.style.display = "none";
document.body.appendChild(filePick);
filePick.onchange = () => {
  if (filePick._to && filePick.files[0]) takeFile(filePick.files[0], filePick._to);
  filePick.value = "";
};

/* ---------------- активи: звідки брати назви ---------------- */
function normPair(s){ return String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, ""); }

/* Спершу те, що людина сама записала в «Моїй ТС»: журнал не вигадує
   список інструментів, а бере її ж слова. Потім те, що вже траплялось
   у журналі. */
let TSA = null;          /* інструменти з ТС: null — ще не питали */
function tsAssets(){
  const live = (window.__ts && typeof __ts.assets === "function") ? __ts.assets() : [];
  if (live.length) return live;
  if (TSA !== null) return TSA;
  /* «Моя ТС» ще не відкривалась і своїх даних не має — беремо самі */
  TSA = [];
  if (demo()){
    try{
      const t = JSON.parse(localStorage.getItem("statsai_ts_demo") || "null");
      TSA = (t && Array.isArray(t.assets)) ? t.assets.filter(Boolean) : [];
    }catch(e){}
    return TSA;
  }
  api("GET", "/api/ts").then(r => {
    TSA = (r && r.ts && Array.isArray(r.ts.assets)) ? r.ts.assets.filter(Boolean) : [];
    if (S.view === "day" && popOpen) render();
  }).catch(() => {});
  return TSA;
}

function assetSources(){
  const ts = tsAssets();
  const seen = {}; ts.forEach(a => seen[normPair(a)] = 1);
  const freq = {};
  (S.all || S.trades || []).forEach(t => {
    const p = String(t.pair || "").trim();
    if (!p || seen[normPair(p)]) return;
    freq[p] = (freq[p] || 0) + 1;
  });
  const journal = Object.keys(freq).sort((a, b) => freq[b] - freq[a]).slice(0, 8);
  return {ts: ts, journal: journal};
}

function assetPop(){
  const d = D(), src = assetSources();
  const taken = {}; (N.assets || []).forEach(a => taken[normPair(a.nm)] = 1);
  const chips = (list, fromTs) => list.length
    ? list.map((nm, i) => '<button type="button" data-nm="' + esc(nm) + '" data-ts="' + (fromTs ? 1 : 0)
        + '" onclick="__dv.addAsset(this.dataset.nm, this.dataset.ts)"'
        + (taken[normPair(nm)] ? " disabled" : "") + ">" + esc(nm) + "</button>").join("")
    : '<span class="none">' + esc(fromTs ? d.noTsAssets : d.noJournalAssets) + "</span>";
  return '<div class="dv-pop">'
    + '<div class="grp"><div class="lbl"><em>◆</em>' + esc(d.fromTs) + "</div>"
    +   '<div class="chips">' + chips(src.ts, true) + "</div></div>"
    + '<div class="grp"><div class="lbl">' + esc(d.fromJournal) + "</div>"
    +   '<div class="chips">' + chips(src.journal, false) + "</div></div>"
    + '<div class="grp"><div class="lbl">' + esc(d.ownAsset) + '</div><div class="own">'
    +   '<input id="dvOwn" placeholder="' + esc(d.phOwnAsset) + '" aria-label="' + esc(d.ownAsset) + '">'
    +   '<button type="button" onclick="__dv.addOwn()">' + esc(d.add) + "</button></div></div>"
    + "</div>";
}

/* ---------------- шматки картки ---------------- */
function biasEd(i){
  const d = D(), a = N.assets[i], cur = a.side || "";
  const b = (val, cls) => '<button class="' + (cur === val ? "on " + (cls || "") : "")
    + '" onclick="__dv.side(' + i + ',this.dataset.v)" data-v="' + val + '">' + esc(val) + "</button>";
  return '<div class="dv-bias"><div class="dv-pick">'
    + b(d.long) + b(d.short, "down") + b(d.flat, "flat") + "</div></div>"
    + ed("assets." + i + ".why", d.phWhy, true);
}
function biasRead(a){
  const d = D();
  const cls = a.side === d.short ? "down" : a.side === d.flat ? "flat" : "";
  return (a.side ? '<div class="dv-bias"><div class="dv-pick"><button class="on ' + cls + '" disabled>'
      + esc(a.side) + "</button></div></div>" : "")
    + '<div class="dv-say">' + (a.why ? esc(a.why).replace(/\n/g, "<br>") : "—") + "</div>";
}

function levelsEd(i){
  const d = D(), base = "assets." + i + ".levels.";
  const rows = (N.assets[i].levels || []).map((l, j) =>
    '<div class="dv-lvr"><span class="p">' + ed(base + j + ".p", d.phPrice) + "</span>"
    + '<span class="t">' + ed(base + j + ".t", d.phWhat) + "</span>"
    + '<span class="n">' + ed(base + j + ".n", d.phWhy2) + "</span>"
    + '<button class="dv-add" style="margin:0" onclick="__dv.delLevel(' + i + "," + j + ')">×</button>'
    + "</div>").join("");
  return '<div class="dv-lv">' + rows + "</div>"
    + '<button class="dv-add" onclick="__dv.addLevel(' + i + ')">+ ' + esc(d.addLevel) + "</button>";
}
function levelsRead(a){
  const list = (a.levels || []).filter(l => l.p || l.t || l.n);
  if (!list.length) return '<div class="hint">—</div>';
  return '<div class="dv-lv">' + list.map(l =>
    '<div class="dv-lvr"><span class="p">' + esc(l.p || "—") + "</span>"
    + '<span class="t">' + esc(l.t || "") + "</span>"
    + '<span class="n">' + esc(l.n || "") + "</span></div>").join("") + "</div>";
}
function levelsDone(i){
  const d = D(), base = "assets." + i + ".levels.";
  const list = N.assets[i].levels || [];
  if (!list.some(l => l.p || l.t)) return '<div class="hint">—</div>';
  return '<div class="dv-lvd">' + list.map((l, j) =>
    '<div class="dv-lvr2 ' + (l.dcls || "") + '"><span class="p">' + esc(l.p || "—") + "</span>"
    + '<button class="dv-hit" type="button" title="' + esc(d.hitTip)
    + '" onclick="__dv.hit(' + i + "," + j + ')"></button>'
    + '<span class="n">' + ed(base + j + ".did", d.phDid) + "</span></div>").join("")
    + "</div>";
}

function plansEd(i){
  const d = D(), base = "assets." + i + ".plans.";
  return '<div class="dv-sc">'
    + '<div class="dv-scr main"><span class="k">A</span><span class="tx">'
    +   ed(base + "0.tx", d.phPlanA, true) + "</span></div>"
    + '<div class="dv-scr"><span class="k">Б</span><span class="tx">'
    +   ed(base + "1.tx", d.phPlanB, true) + "</span></div>"
    + "</div>";
}
function plansRead(a){
  const p = a.plans || [];
  const row = (k, tx, main) => tx ? '<div class="dv-scr' + (main ? " main" : "") + '"><span class="k">' + k
    + '</span><span class="tx">' + esc(tx).replace(/\n/g, "<br>") + "</span></div>" : "";
  const h = row("A", (p[0] || {}).tx, true) + row("Б", (p[1] || {}).tx);
  return h ? '<div class="dv-sc">' + h + "</div>" : '<div class="hint">—</div>';
}

function skipEd(){
  const d = D();
  return ed("skip", d.phSkip, true)
    + '<div class="dv-auto"><b>' + esc(d.autoTag) + "</b>" + esc(d.newsAuto) + "</div>";
}

function dayTrades(){
  /* у дати угоди може стояти й час — порівнюємо лише день */
  return (S.trades || []).filter(t => String(t.date || "").slice(0, 10) === DATE && !t.hidden);
}
function tradesFor(a){
  const key = normPair(a.nm);
  return key ? dayTrades().filter(t => normPair(t.pair) === key) : [];
}
function tradesOrphan(){
  const keys = {}; (N.assets || []).forEach(a => { if (a.nm) keys[normPair(a.nm)] = 1; });
  return dayTrades().filter(t => !keys[normPair(t.pair)]);
}

function tradesHtml(list, note){
  const d = D();
  if (!list.length) return '<div class="hint">' + esc(d.noTrades) + "</div>";
  const flags = N.trades || {};
  return '<div class="dv-trs">' + list.map(t => {
    const f = flags[t.id] || "";
    const r = netR(t);
    return '<div class="dv-tr' + (f === "off" ? " off" : "") + '">'
      + '<span class="nm">' + esc(t.pair || "—")
      +   (t.position ? " <i>· " + esc(t.position) + "</i>" : "")
      +   (t.entry_model ? " <i>· " + esc(t.entry_model) + "</i>" : "") + "</span>"
      + '<button class="fl ' + f + '" onclick="__dv.flag(\'' + t.id + '\')">'
      +   esc(f === "plan" ? d.byPlan : f === "off" ? d.offPlan : d.markIt) + "</button>"
      + '<span class="r ' + clsR(r) + '">' + fmtR(r) + "</span>"
      /* поділитись саме цією угодою, а не всім днем */
      + '<button class="dv-sh" type="button" title="' + esc(d.shareTip)
      +   '" onclick="__dv.share(\'' + t.id + '\')">'
      +   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none">'
      +   '<rect x="3" y="4" width="18" height="14" rx="2.5" stroke="currentColor" stroke-width="1.7"/>'
      +   '<path d="M3 14.5l4.5-4 3.5 3 4-4.5L21 14" stroke="currentColor" stroke-width="1.7" '
      +   'stroke-linecap="round" stroke-linejoin="round"/>'
      +   '<circle cx="8.5" cy="8.5" r="1.4" fill="currentColor"/></svg></button>'
      + "</div>";
  }).join("") + "</div>"
    + (note ? '<div class="dv-auto"><b>' + esc(d.autoTag) + "</b>" + esc(note) + "</div>" : "");
}

function marksEd(i){
  const d = D();
  const one = (key, label) => {
    const cur = (N.assets[i].marks || {})[key] || "";
    const b = t => '<button class="' + (cur === t ? "on" : "") + '" data-k="' + key
      + '" data-v="' + t + '" onclick="__dv.mark(' + i + ',this.dataset.k, this.dataset.v)">' + esc(t) + "</button>";
    return "<div><div class=\"k\">" + esc(label) + '</div><div class="dv-pick">'
      + b(d.yes) + b(d.partly) + b(d.no) + "</div></div>";
  };
  return '<div class="dv-marks">' + one("match", d.markMatch) + one("hold", d.markHold) + "</div>";
}

function sumR(list){ return list.reduce((s, t) => s + netR(t), 0); }

/* ---------------- підсумок за місяць ---------------- */
function strip(){
  const d = D();
  if (STATS === null){
    loadStats();
    return "";
  }
  if (!STATS.length) return "";
  const byId = {};
  (S.trades || []).forEach(t => byId[t.id] = t);

  let played = 0, off = 0, cost = 0;
  STATS.forEach(n => {
    if (n.match === d.yes) played++;
    const flags = (n.data && n.data.trades) || {};
    Object.keys(flags).forEach(id => {
      if (flags[id] !== "off") return;
      off++;
      if (byId[id]) cost += netR(byId[id]);
    });
  });

  const s = (k, v, cls, note) => '<div class="s"><div class="k">' + esc(k) + '</div>'
    + '<div class="v ' + (cls || "") + '">' + esc(v) + '</div>'
    + '<div class="n">' + esc(note) + "</div></div>";

  return '<div class="dv-strip">'
    + s(d.stPlayed, played + " / " + STATS.length, played ? "pos" : "", d.stPlayedNote)
    + s(d.stOff, String(off), "", d.stOffNote)
    + s(d.stCost, fmtR(cost), cost < 0 ? "neg" : "", d.stCostNote)
    + "</div>";
}

/* ---------------- шапка, календар ---------------- */
function head(){
  const d = D();
  const today = iso(new Date());
  const nice = human(DATE);
  return '<div class="vhead"><h1>' + esc(d.title) + "</h1>"
    + '<span class="sub">' + esc(nice) + (DATE === today ? " · " + esc(d.today) : "") + "</span>"
    + '<span class="dv-nav">'
    +   '<span class="dv-seg">'
    +     '<button class="' + (N.closed ? "" : "on") + '" onclick="__dv.reopen()">' + esc(d.morning) + "</button>"
    +     '<button class="' + (N.closed ? "on" : "") + '" onclick="__dv.close()">' + esc(d.evening) + "</button>"
    +   "</span>"
    +   '<button onclick="__dv.go(-1)" title="' + esc(d.prevDay) + '">←</button>'
    +   '<span class="dv-calwrap">'
    +     '<button class="day" onclick="__dv.cal()">'
    +       '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="17" rx="3" stroke="currentColor" stroke-width="1.7"/><path d="M3 9h18M8 3v3M16 3v3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'
    +       esc(DATE) + "</button>"
    +     (calOpen ? calendar() : "")
    +   "</span>"
    +   '<button onclick="__dv.go(1)" title="' + esc(d.nextDay) + '">→</button>'
    +   (DATE === today ? "" : '<button onclick="__dv.today()">' + esc(d.today) + "</button>")
    +   ((N.assets || []).length
          ? '<button class="dv-share" onclick="__dv.shareDay()" title="' + esc(d.shareTip2) + '">'
            + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none">'
            + '<path d="M12 3v12M8 7l4-4 4 4" stroke="currentColor" stroke-width="1.8" '
            + 'stroke-linecap="round" stroke-linejoin="round"/>'
            + '<path d="M5 14v4a2 2 0 002 2h10a2 2 0 002-2v-4" stroke="currentColor" '
            + 'stroke-width="1.8" stroke-linecap="round"/></svg>'
            + '<span>' + esc(d.shareDay) + "</span></button>"
          : "")
    + "</span></div>";
}

/* Місяць крапками: зелена — план збігся, жовта — частково, червона — ні,
   порожній кружок — план є, вечір не записаний. Клік по дню відкриває його. */
function calendar(){
  const d = D();
  if (DAYS === null){ loadDays(); }
  const [y, m] = (calMonth || DATE.slice(0, 7)).split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const days = new Date(y, m, 0).getDate();
  const pad = (first.getDay() + 6) % 7;                 /* понеділок — перший */
  const today = iso(new Date());
  const marks = {};
  (DAYS || []).forEach(x => { marks[x.date] = x; });
  const dot = x => {
    if (!x) return "";
    const v = x.match;
    const cls = v === d.yes ? "ok" : v === d.partly ? "part" : v === d.no ? "no" : "open";
    return '<i class="' + cls + '"></i>';
  };
  let cells = "";
  for (let i = 0; i < pad; i++) cells += '<span class="d pad"></span>';
  for (let n = 1; n <= days; n++){
    const key = y + "-" + String(m).padStart(2, "0") + "-" + String(n).padStart(2, "0");
    const x = marks[key];
    cells += '<button type="button" class="d' + (x ? " has" : "") + (key === DATE ? " cur" : "")
      + (key > today ? " future" : "") + '" onclick="__dv.goto(\'' + key + '\')">' + n + dot(x) + "</button>";
  }
  const loc = {uk: "uk-UA", ru: "ru-RU", en: "en-GB"}[window.LANG] || "uk-UA";
  const monthName = first.toLocaleDateString(loc, {month: "long", year: "numeric"});
  const wd = d.weekdays.map(w => "<span>" + w + "</span>").join("");
  return '<div class="dv-cal">'
    + '<div class="mh"><button type="button" onclick="__dv.calMove(-1)">‹</button>'
    +   "<b>" + esc(monthName) + "</b>"
    +   '<button type="button" onclick="__dv.calMove(1)">›</button></div>'
    + '<div class="wd">' + wd + "</div>"
    + '<div class="grid">' + cells + "</div>"
    + '<div class="lg"><span><i class="ok"></i>' + esc(d.lgOk) + '</span><span><i class="part"></i>' + esc(d.lgPart)
    +   '</span><span><i class="no"></i>' + esc(d.lgNo) + '</span><span><i class="open"></i>' + esc(d.lgOpen) + "</span></div>"
    + "</div>";
}

function human(dt){
  const [y, m, dd] = dt.split("-").map(Number);
  const date = new Date(y, m - 1, dd);
  const loc = {uk: "uk-UA", ru: "ru-RU", en: "en-GB"}[window.LANG] || "uk-UA";
  return date.toLocaleDateString(loc, {weekday: "short", day: "numeric", month: "long"});
}

/* ---------------- вигляд: день іде ---------------- */
function assetHead(a, i, extra){
  const d = D();
  const cls = a.side === d.short ? "short" : a.side === d.long ? "long" : "";
  return '<div class="dv-ah">'
    + '<span class="nm">' + (N.closed ? esc(a.nm || d.phAsset) : ed("assets." + i + ".nm", d.phAsset)) + "</span>"
    + (a.ts ? '<span class="from">' + esc(d.fromTsTag) + "</span>" : "")
    + (a.side ? '<span class="tag ' + cls + '">' + esc(a.side) + "</span>" : "")
    + '<span class="sp"></span>' + (extra || "")
    + (N.closed ? "" : '<button class="x" type="button" title="' + esc(d.dropAsset) + '" onclick="__dv.dropAsset(' + i + ')">×</button>')
    + "</div>";
}

function cardOpen(a, i){
  const d = D();
  return '<div class="dv-card">' + assetHead(a, i)
    + '<div class="dv-cb">'
    +   '<div class="dv-blk"><div class="dv-pt"><b>01</b>' + esc(d.p1) + "<i>" + esc(d.p1s) + "</i></div>"
    +     shotsRow("assets." + i + ".shots", d.shotPlan) + "</div>"
    +   '<div class="dv-blk"><div class="dv-pt"><b>02</b>' + esc(d.p2) + "<i>" + esc(d.p2s) + "</i></div>"
    +     biasEd(i) + "</div>"
    +   '<div class="dv-blk"><div class="dv-pt"><b>03</b>' + esc(d.p3) + "<i>" + esc(d.p3s) + "</i></div>"
    +     levelsEd(i) + "</div>"
    +   '<div class="dv-blk"><div class="dv-pt"><b>04</b>' + esc(d.p4) + "<i>" + esc(d.p4s) + "</i></div>"
    +     plansEd(i) + "</div>"
    + "</div></div>";
}

function ready(){
  return (N.assets || []).some(a => a.side || ((a.plans || [])[0] && a.plans[0].tx)
    || (a.levels || []).some(l => l.p) || (a.shots || []).length);
}

function vOpen(){
  const d = D();
  const ok = ready();
  return head()
    + '<p class="dv-hint">' + esc(d.hintOpen) + "</p>"
    + '<div class="dv-stack">'
    +   (N.assets.length ? N.assets.map(cardOpen).join("")
        : '<div class="dv-empty">' + esc(d.noAssetsHint) + "</div>")
    +   '<div class="dv-addwrap">'
    +     '<button class="dv-addbig" type="button" onclick="__dv.pop()">+ ' + esc(d.addAsset) + "</button>"
    +     (popOpen ? assetPop() : "")
    +   "</div>"
    + "</div>"
    + '<div class="dv-common"><div class="dv-pt"><b>05</b>' + esc(d.p5) + "<i>" + esc(d.p5s) + "</i></div>"
    +   skipEd() + "</div>"
    + '<div class="dv-closebar">'
    +   '<div class="t">' + esc(ok ? d.closeNote : d.closeNoteOff) + "</div>"
    +   '<button class="go" onclick="__dv.close()"' + (ok ? "" : " disabled") + ">"
    +     esc(ok ? d.closeDay : d.writePlanFirst) + "</button>"
    + "</div>"
    + strip();
}

/* ---------------- вигляд: день закрито ---------------- */
function cardClosed(a, i){
  const d = D();
  const list = tradesFor(a);
  const r = sumR(list);
  const res = list.length ? '<span class="res ' + clsR(r) + '">' + fmtR(r) + "</span>" : "";
  const pt = (n, t, s, fact) => '<div class="dv-pt' + (fact ? " fact" : "") + '"><b>' + n + "</b>" + esc(t) + "<i>" + esc(s) + "</i></div>";
  return '<div class="dv-card">' + assetHead(a, i, res)
    + '<div class="dv-two">'
    +   '<div class="col left">'
    +     '<div class="dv-colhead"><b class="plan">' + esc(d.morning) + " · " + esc(d.planTag) + "</b></div>"
    +     '<div class="dv-blk">' + pt("01", d.p1, d.p1s) + shotsRow("assets." + i + ".shots", d.shotPlan, true) + "</div>"
    +     '<div class="dv-blk">' + pt("02", d.p2, d.p2s) + biasRead(a) + "</div>"
    +     '<div class="dv-blk">' + pt("03", d.p3, d.p3s) + levelsRead(a) + "</div>"
    +     '<div class="dv-blk">' + pt("04", d.p4, d.p4s) + plansRead(a) + "</div>"
    +   "</div>"
    +   '<div class="col">'
    +     '<div class="dv-colhead"><b class="fact">' + esc(d.evening) + " · " + esc(d.factTag) + "</b></div>"
    +     '<div class="dv-blk">' + pt("01", d.q1, d.q1s, true) + shotsRow("assets." + i + ".eve.shots", d.shotFact) + "</div>"
    +     '<div class="dv-blk">' + pt("02", d.q2, d.q2s, true) + ed("assets." + i + ".eve.text", d.phFact, true) + "</div>"
    +     '<div class="dv-blk">' + pt("03", d.q3, d.q3s, true) + levelsDone(i) + "</div>"
    +     '<div class="dv-blk">' + pt("04", d.q4, d.q4s.replace("%s", a.nm || "—"), true)
    +        tradesHtml(list, d.tradesAuto) + "</div>"
    +     '<div class="dv-blk">' + pt("05", d.q5, d.q5s, true) + marksEd(i) + "</div>"
    +   "</div>"
    + "</div></div>";
}

function summary(){
  const d = D();
  const all = dayTrades();
  const tot = sumR(all);
  const mk = v => v ? '<span class="m"><i class="' + (v === d.yes ? "y" : v === d.no ? "n" : "p") + '"></i>' + esc(v) + "</span>"
                    : '<span class="m none">—</span>';
  const rows = (N.assets || []).map(a => {
    const list = tradesFor(a), r = sumR(list);
    const cls = a.side === d.short ? "short" : a.side === d.long ? "long" : "";
    const said = ((a.eve && a.eve.text) || "").split(/[.!?]\s/)[0];
    return '<div class="srow"><span class="nm">' + esc(a.nm || d.phAsset) + "</span>"
      + (a.side ? '<span class="tag ' + cls + '">' + esc(a.side) + "</span>" : "<span></span>")
      + '<span class="said">' + (said ? esc(said) : "—") + "</span>"
      + mk((a.marks || {}).match) + mk((a.marks || {}).hold)
      + '<span class="r ' + (list.length ? clsR(r) : "") + '">' + (list.length ? fmtR(r) : "—") + "</span></div>";
  }).join("");
  return '<div class="dv-sum">'
    + '<div class="h"><b>' + esc(d.sumTitle) + "</b><span>" + N.assets.length + " " + esc(d.sumAssets)
    +   " · " + all.length + " " + esc(d.sumTrades) + "</span>"
    +   (all.length ? '<span class="tot ' + clsR(tot) + '">' + fmtR(tot) + "</span>" : "") + "</div>"
    + '<div class="srow hd"><span>' + esc(d.colAsset) + "</span><span>" + esc(d.colPlan) + "</span><span>"
    +   esc(d.colFact) + "</span><span>" + esc(d.colMatch) + "</span><span>" + esc(d.colHold)
    +   '</span><span style="text-align:right">' + esc(d.colRes) + "</span></div>"
    + rows
    + '<div class="lesson"><div class="k">' + esc(d.lessonTitle) + "</div>"
    +   ed("fact.lesson", d.phLesson, true) + "</div>"
    + "</div>";
}

function vClosed(){
  const d = D();
  const orphan = tradesOrphan();
  return head()
    + '<p class="dv-hint">' + esc(d.hintClosed) + "</p>"
    + '<div class="dv-stack">' + N.assets.map(cardClosed).join("")
    + (orphan.length
        ? '<div class="dv-card"><div class="dv-ah"><span class="nm">' + esc(d.otherTrades) + "</span>"
          + '<span class="sp"></span></div><div class="dv-cb"><div class="dv-blk">'
          + tradesHtml(orphan, d.otherTradesNote) + "</div></div></div>"
        : "")
    + "</div>"
    + '<div style="height:14px"></div>' + summary()
    + '<div class="dv-common" style="margin-top:14px"><div class="dv-pt"><b>05</b>' + esc(d.p5) + "<i>" + esc(d.p5s) + "</i></div>"
    +   ed("skip", d.phSkip, true) + "</div>"
    + '<p class="dv-hint" style="margin-top:14px">'
    +   '<button class="dv-add" onclick="__dv.reopen()">' + esc(d.reopen) + "</button></p>"
    + strip();
}

function vDay(){
  if (!DATE) DATE = iso(new Date());
  if (N === undefined){
    load();
    return '<div class="empty">' + esc(D().loading) + "</div>";
  }
  if (N === null) N = blank();
  return N.closed ? vClosed() : vOpen();
}
VIEWS.day = vDay;

/* ---------------- правка на місці ---------------- */
document.addEventListener("click", e => {
  if (S.view !== "day" || !N) return;

  /* відкриті спливні: клік повз них — закриває */
  if (calOpen && !e.target.closest(".dv-calwrap")){ calOpen = false; render(); return; }
  if (popOpen && !e.target.closest(".dv-addwrap")){ popOpen = false; render(); return; }
  if (tfEdit && !e.target.closest(".dv-tfpick")){ tfEdit = null; render(); return; }

  const sl = e.target.closest && e.target.closest(".dv-shot[data-shot]");
  if (sl){
    if (sl.classList.contains("ro")) return;
    if (e.target.closest(".rm")){
      e.stopPropagation();
      removeShot(sl.dataset.shot);
      save(); render();
      return;
    }
    filePick._to = sl;
    filePick.click();
    return;
  }

  const el = e.target.closest && e.target.closest(".dv-f[data-p]");
  if (!el || el.querySelector("input,textarea")) return;
  const path = el.dataset.p;
  const multi = el.dataset.multi === "1";
  const f = document.createElement(multi ? "textarea" : "input");
  f.className = "dv-in";
  const cur = get(path);
  f.value = cur == null ? "" : cur;
  el.textContent = "";
  el.appendChild(f);
  f.focus();
  if (f.setSelectionRange) f.setSelectionRange(f.value.length, f.value.length);
  let done = false;
  const commit = ok => {
    if (done) return;
    done = true;
    if (ok){ set(path, f.value.trim()); save(); }
    render();
  };
  f.addEventListener("blur", () => commit(true));
  f.addEventListener("keydown", ev => {
    if (ev.key === "Escape"){ ev.stopPropagation(); commit(false); }
    if (ev.key === "Enter" && (!multi || ev.ctrlKey || ev.metaKey)){ ev.preventDefault(); commit(true); }
  });
});

/* подвійний клік по слоту — вибір файлу з комп'ютера */
document.addEventListener("dblclick", e => {
  if (S.view !== "day" || !N) return;
  const sl = e.target.closest && e.target.closest(".dv-shot[data-shot]:not(.ro)");
  if (!sl) return;
  e.preventDefault();
  armed = null;
  filePick._to = sl;
  filePick.click();
});

document.addEventListener("mouseover", e => {
  const sl = e.target.closest && e.target.closest(".dv-shot[data-shot]:not(.ro)");
  if (sl) hotShot = sl;
});
document.addEventListener("paste", e => {
  if (S.view !== "day" || !N) return;
  if (e.target.closest && e.target.closest("input,textarea")) return;
  const files = (e.clipboardData && e.clipboardData.files) || [];
  if (!files.length) return;
  /* спершу той слот, який людина обрала кліком, потім той, над яким
     стоїть миша, і лише тоді перший порожній */
  const el = (armed && document.querySelector('.dv-shot[data-shot="' + armed + '"]'))
    || (hotShot && document.body.contains(hotShot) ? hotShot : null)
    || document.querySelector(".dv-shot[data-shot]:not(.has):not(.ro)");
  if (!el) return;
  e.preventDefault();
  takeFile(files[0], el);
});
document.addEventListener("dragover", e => {
  if (e.target.closest && e.target.closest(".dv-shot[data-shot]:not(.ro)")) e.preventDefault();
});
document.addEventListener("drop", e => {
  const el = e.target.closest && e.target.closest(".dv-shot[data-shot]:not(.ro)");
  if (!el) return;
  e.preventDefault();
  takeFile(e.dataTransfer.files[0], el);
});
document.addEventListener("keydown", e => {
  if (S.view !== "day") return;
  if (e.key === "Enter" && e.target && e.target.id === "dvOwn"){ e.preventDefault(); window.__dv.addOwn(); }
  if (e.key === "Enter" && e.target && e.target.id === "dvTf" && tfEdit){
    e.preventDefault(); window.__dv.tf(tfEdit.replace(/\.tf$/, ".tf"), null);
  }
  if (e.key === "Escape" && armed){ armed = null; render(); }
});

/* ---------------- назовні ---------------- */
window.__dv = {
  go: shift,
  goto: goto,
  today(){ goto(iso(new Date())); },
  cal(){ calOpen = !calOpen; popOpen = false; if (calOpen) calMonth = DATE.slice(0, 7); render(); },
  calMove(dir){
    const [y, m] = (calMonth || DATE.slice(0, 7)).split("-").map(Number);
    const t = new Date(y, m - 1 + dir, 1);
    calMonth = t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0");
    render();
  },
  pop(){
    if (window.Guest && Guest.block(T.gsGateTitle)) return;
    popOpen = !popOpen; calOpen = false; render();
  },
  addAsset(nm, fromTs){
    N.assets.push(blankAsset(nm, fromTs === 1 || fromTs === "1" || fromTs === true));
    popOpen = false; save(); render();
  },
  addOwn(){
    const inp = document.getElementById("dvOwn");
    const v = ((inp && inp.value) || "").trim().toUpperCase();
    if (!v){ if (inp) inp.focus(); return; }
    window.__dv.addAsset(v, 0);
  },
  dropAsset(i){ N.assets.splice(i, 1); save(); render(); },
  tfEdit(path){ tfEdit = (tfEdit === path ? null : path); render(); },
  tf(path, val){
    /* val === null — закрили хрестиком: беремо те, що встигли вписати */
    if (val === null){
      const inp = document.getElementById("dvTf");
      const own = ((inp && inp.value) || "").trim();
      if (own) set(path, own.slice(0, 8));
    } else {
      set(path, val);
    }
    tfEdit = null; save(); render();
  },
  side(i, v){
    const a = N.assets[i];
    a.side = (a.side === v ? "" : v);
    save(); render();
  },
  mark(i, k, v){
    const a = N.assets[i];
    if (!a.marks) a.marks = {};
    a.marks[k] = (a.marks[k] === v ? "" : v);
    save(); render();
  },
  hit(i, j){
    const cycle = {"": "ok", ok: "mid", mid: "no", no: ""};
    const l = N.assets[i].levels[j];
    l.dcls = cycle[l.dcls || ""];
    save(); render();
  },
  /* Запис дня назовні — з нього sharelink.js збирає знімок розбору.
     Віддаємо лише той день, який зараз відкритий: інші не завантажені. */
  note(date){ return (!date || date === DATE) ? N : null; },
  shareDay(){
    if (window.Guest && Guest.block(T.gsGateTitle)) return;
    if (window.Share) Share.open("review", DATE);
  },
  /* Зведення по одній угоді: та сама картинка, що й у журналі —
     з деталями входу й скрінами. День цілком тут не потрібен. */
  share(id){
    if (window.Share) Share.open("trade", id);
    else if (window.__tradeImg) __tradeImg.open("trade", id);
  },
  flag(id){
    if (!N.trades) N.trades = {};
    const cycle = {"": "plan", plan: "off", off: ""};
    N.trades[id] = cycle[N.trades[id] || ""];
    save(); render();
  },
  addLevel(i){ (N.assets[i].levels = N.assets[i].levels || []).push({}); save(); render(); },
  delLevel(i, j){ N.assets[i].levels.splice(j, 1); save(); render(); },
  close(){ if (N.closed || !ready()) return; N.closed = true; save(); render(); },
  reopen(){ if (!N.closed) return; N.closed = false; save(); render(); },
};

/* ---------------- підпис у бічній панелі ---------------- */
function paintNav(){
  const a = document.querySelector('.nav a[data-v="day"]');
  if (!a) return;
  const sp = a.querySelector("span");
  if (sp) sp.textContent = D().title;
  a.setAttribute("data-tip", D().navTip);
}
const realApply = window.applyLang;
if (typeof realApply === "function"){
  window.applyLang = function(){
    const r = realApply.apply(this, arguments);
    paintNav();
    return r;
  };
}

/* ============================================================
   Словник розділу. Поки лежить тут, а не в i18n.js: розділ ще
   ворушиться, і так його правки не чіпають спільний файл.
   ============================================================ */
const DICT = {
uk: {
  title: "Аналіз дня", navTip: "Що планував зранку — і як воно відпрацювало",
  loading: "Хвилинку…", today: "сьогодні", prevDay: "Попередній день", nextDay: "Наступний день",
  long: "Long", short: "Short", flat: "Нейтрально",
  yes: "так", partly: "частково", no: "ні",
  weekdays: ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
  lgOk: "за планом", lgPart: "частково", lgNo: "не за планом", lgOpen: "без вечора",

  hintOpen: "Кожен актив — своя картка: скріни по таймфреймах, напрям, рівні, сценарії. "
          + "Активи підказує ваша ТС. Увечері натиснете «Записати підсумок дня» — і поруч із планом зʼявиться факт.",
  hintClosed: "Ліворуч — план, як його записали зранку, праворуч — що вийшло. Угоди з журналу самі лягли до свого активу. "
            + "Оцінки «за планом» і «тримався» — по кожному активу окремо, з них збирається статистика.",
  morning: "Ранок", evening: "Вечір", planTag: "план", factTag: "факт",

  addAsset: "додати актив", dropAsset: "Прибрати актив", phAsset: "актив",
  fromTs: "з вашої ТС", fromTsTag: "з вашої ТС", fromJournal: "вже були в журналі",
  ownAsset: "свій", phOwnAsset: "напр. USDJPY", add: "Додати",
  noTsAssets: "у ТС інструменти ще не записані", noJournalAssets: "у журналі ще нічого",
  noAssetsHint: "Додайте актив, який розбираєте зранку — можна кілька.",
  tfPick: "таймфрейм", addTf: "таймфрейм", noShots: "скрінів не було",
  otherTrades: "Інші угоди дня", otherTradesNote: "Угоди по інструментах, яких зранку не розбирали",

  p1: "Графіки зранку", p1s: "по таймфреймах",
  p2: "Куди дивишся", p2s: "лонг чи шорт і чому",
  p3: "Рівні, які відмітив", p3s: "ціна і що це",
  p4: "Що плануєш робити", p4s: "сценарії на день",
  p5: "Чого не робити", p5s: "правила на день, спільні для всіх активів",

  q1: "Той самий графік увечері", q1s: "як усе закінчилось",
  q2: "Куди ринок пішов", q2s: "своїми словами",
  q3: "Що з ними сталось", q3s: "по кожному рівню",
  q4: "Що зробив насправді", q4s: "угоди з журналу по %s",
  q5: "Чи втримався", q5s: "по цьому активу",

  phWhy: "Чому саме так — одним-двома реченнями",
  phPrice: "ціна", phWhat: "що це", phWhy2: "навіщо він мені",
  phPlanA: "Якщо ринок зробить … — я зроблю …",
  phPlanB: "А якщо піде інакше — тоді …",
  phSkip: "Кожне правило з нового рядка. Наприклад: до 11:00 входу немає — виходжу з-за графіка",
  phFact: "Що ринок зробив насправді",
  phDid: "що з ним сталось",
  phLesson: "Один рядок собі на завтра",
  addLevel: "ще рівень", hitTip: "дійшло / наполовину / ні",
  shotPlan: "вставити скрін розмітки", shotFact: "вставити скрін кінця дня",
  shotHint: "клік → далі Ctrl+V · подвійний клік → файл",
  shotArmed: "тепер Ctrl+V", tfOwn: "свій",

  autoTag: "саме", newsAuto: "Новини на сьогодні беруться з розділу «Новини»",
  tradesAuto: "Угоди підтягуються з журналу за назвою інструмента — тут їх не набирають",
  noTrades: "За цей день угод по цьому активу немає",
  byPlan: "за планом", offPlan: "поза планом", markIt: "позначити",
  shareTip: "Поділитись зведенням саме по цій угоді",
  shareDay: "Поділитись", shareTip2: "Поділитись розбором дня за посиланням",
  markMatch: "Ринок пішов за планом", markHold: "Тримався плану",

  sumTitle: "підсумок дня", sumAssets: "активи", sumTrades: "угоди",
  colAsset: "актив", colPlan: "план", colFact: "що вийшло", colMatch: "за планом",
  colHold: "тримався", colRes: "результат", lessonTitle: "що з цього винести",

  closeDay: "Записати підсумок дня", writePlanFirst: "Спершу запиши план",
  closeNote: "Коли день скінчився — натисніть: ліворуч лишиться план, праворуч зʼявиться місце під факт по кожному активу.",
  closeNoteOff: "Кнопка ввімкнеться, коли в якомусь активі зʼявиться план: напрям, рівень чи скрін.",
  reopen: "← повернутись до плану",

  stPlayed: "Сценарій зіграв", stPlayedNote: "днів за останній місяць",
  stOff: "Угод поза планом", stOffNote: "взяв те, чого зранку не планував",
  stCost: "Скільки вони коштували", stCostNote: "разом по цих угодах",
},

ru: {
  title: "Анализ дня", navTip: "Что планировал утром — и как оно отработало",
  loading: "Минутку…", today: "сегодня", prevDay: "Предыдущий день", nextDay: "Следующий день",
  long: "Long", short: "Short", flat: "Нейтрально",
  yes: "да", partly: "частично", no: "нет",
  weekdays: ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
  lgOk: "по плану", lgPart: "частично", lgNo: "не по плану", lgOpen: "без вечера",

  hintOpen: "Каждый актив — своя карточка: скрины по таймфреймам, направление, уровни, сценарии. "
          + "Активы подсказывает ваша ТС. Вечером нажмёте «Записать итог дня» — и рядом с планом появится факт.",
  hintClosed: "Слева — план, как его записали утром, справа — что вышло. Сделки из журнала сами легли к своему активу. "
            + "Оценки «по плану» и «держался» — по каждому активу отдельно, из них собирается статистика.",
  morning: "Утро", evening: "Вечер", planTag: "план", factTag: "факт",

  addAsset: "добавить актив", dropAsset: "Убрать актив", phAsset: "актив",
  fromTs: "из вашей ТС", fromTsTag: "из вашей ТС", fromJournal: "уже были в журнале",
  ownAsset: "свой", phOwnAsset: "напр. USDJPY", add: "Добавить",
  noTsAssets: "в ТС инструменты ещё не записаны", noJournalAssets: "в журнале ещё ничего",
  noAssetsHint: "Добавьте актив, который разбираете утром — можно несколько.",
  tfPick: "таймфрейм", addTf: "таймфрейм", noShots: "скринов не было",
  otherTrades: "Другие сделки дня", otherTradesNote: "Сделки по инструментам, которые утром не разбирали",

  p1: "Графики утром", p1s: "по таймфреймам",
  p2: "Куда смотришь", p2s: "лонг или шорт и почему",
  p3: "Уровни, которые отметил", p3s: "цена и что это",
  p4: "Что планируешь делать", p4s: "сценарии на день",
  p5: "Чего не делать", p5s: "правила на день, общие для всех активов",

  q1: "Тот же график вечером", q1s: "как всё закончилось",
  q2: "Куда рынок пошёл", q2s: "своими словами",
  q3: "Что с ними стало", q3s: "по каждому уровню",
  q4: "Что сделал на самом деле", q4s: "сделки из журнала по %s",
  q5: "Удержался ли", q5s: "по этому активу",

  phWhy: "Почему именно так — одним-двумя предложениями",
  phPrice: "цена", phWhat: "что это", phWhy2: "зачем он мне",
  phPlanA: "Если рынок сделает … — я сделаю …",
  phPlanB: "А если пойдёт иначе — тогда …",
  phSkip: "Каждое правило с новой строки. Например: до 11:00 входа нет — выхожу из-за графика",
  phFact: "Что рынок сделал на самом деле",
  phDid: "что с ним стало",
  phLesson: "Одна строка себе на завтра",
  addLevel: "ещё уровень", hitTip: "дошло / наполовину / нет",
  shotPlan: "вставить скрин разметки", shotFact: "вставить скрин конца дня",
  shotHint: "клик → дальше Ctrl+V · двойной клик → файл",
  shotArmed: "теперь Ctrl+V", tfOwn: "свой",

  autoTag: "само", newsAuto: "Новости на сегодня берутся из раздела «Новини»",
  tradesAuto: "Сделки подтягиваются из журнала по названию инструмента — тут их не набирают",
  noTrades: "За этот день сделок по этому активу нет",
  byPlan: "по плану", offPlan: "вне плана", markIt: "отметить",
  shareTip: "Поделиться сводкой именно по этой сделке",
  shareDay: "Поделиться", shareTip2: "Поделиться разбором дня по ссылке",
  markMatch: "Рынок пошёл по плану", markHold: "Держался плана",

  sumTitle: "итог дня", sumAssets: "актива", sumTrades: "сделки",
  colAsset: "актив", colPlan: "план", colFact: "что вышло", colMatch: "по плану",
  colHold: "держался", colRes: "результат", lessonTitle: "что из этого вынести",

  closeDay: "Записать итог дня", writePlanFirst: "Сначала запиши план",
  closeNote: "Когда день закончился — нажмите: слева останется план, справа появится место под факт по каждому активу.",
  closeNoteOff: "Кнопка включится, когда в каком-то активе появится план: направление, уровень или скрин.",
  reopen: "← вернуться к плану",

  stPlayed: "Сценарий сыграл", stPlayedNote: "дней за последний месяц",
  stOff: "Сделок вне плана", stOffNote: "взял то, чего утром не планировал",
  stCost: "Сколько они стоили", stCostNote: "вместе по этим сделкам",
},

en: {
  title: "Day review", navTip: "What you planned in the morning — and how it played out",
  loading: "One moment…", today: "today", prevDay: "Previous day", nextDay: "Next day",
  long: "Long", short: "Short", flat: "Neutral",
  yes: "yes", partly: "partly", no: "no",
  weekdays: ["mo", "tu", "we", "th", "fr", "sa", "su"],
  lgOk: "as planned", lgPart: "partly", lgNo: "off plan", lgOpen: "no evening yet",

  hintOpen: "Each instrument gets its own card: screenshots by timeframe, direction, levels, scenarios. "
          + "Instruments are suggested from your system. In the evening press “Write the day up” and the facts appear next to the plan.",
  hintClosed: "Left is the plan as written in the morning, right is what came of it. Trades from the journal landed under their instrument on their own. "
            + "“As planned” and “held to it” are marked per instrument — the stats are built from them.",
  morning: "Morning", evening: "Evening", planTag: "plan", factTag: "fact",

  addAsset: "add instrument", dropAsset: "Remove instrument", phAsset: "instrument",
  fromTs: "from your system", fromTsTag: "from your system", fromJournal: "seen in the journal",
  ownAsset: "custom", phOwnAsset: "e.g. USDJPY", add: "Add",
  noTsAssets: "no instruments in your system yet", noJournalAssets: "nothing in the journal yet",
  noAssetsHint: "Add the instrument you are reviewing this morning — several are fine.",
  tfPick: "timeframe", addTf: "timeframe", noShots: "no screenshots",
  otherTrades: "Other trades of the day", otherTradesNote: "Trades on instruments you did not review in the morning",

  p1: "Charts in the morning", p1s: "by timeframe",
  p2: "Which way you look", p2s: "long or short and why",
  p3: "Levels you marked", p3s: "price and what it is",
  p4: "What you plan to do", p4s: "scenarios for the day",
  p5: "What not to do", p5s: "rules for the day, shared by all instruments",

  q1: "The same chart in the evening", q1s: "how it ended",
  q2: "Where the market went", q2s: "in your own words",
  q3: "What happened to them", q3s: "level by level",
  q4: "What you actually did", q4s: "journal trades on %s",
  q5: "Did you hold to it", q5s: "for this instrument",

  phWhy: "Why exactly — one or two sentences",
  phPrice: "price", phWhat: "what it is", phWhy2: "why it matters",
  phPlanA: "If the market does … — I do …",
  phPlanB: "And if it goes the other way — then …",
  phSkip: "One rule per line. For example: no entry by 11:00 — I leave the screen",
  phFact: "What the market actually did",
  phDid: "what happened to it",
  phLesson: "One line for tomorrow",
  addLevel: "one more level", hitTip: "reached / halfway / no",
  shotPlan: "add the markup screenshot", shotFact: "add the end-of-day screenshot",
  shotHint: "click → then Ctrl+V · double click → file",
  shotArmed: "now press Ctrl+V", tfOwn: "custom",

  autoTag: "auto", newsAuto: "Today's news comes from the News section",
  tradesAuto: "Trades come from the journal, matched by instrument — no typing here",
  noTrades: "No trades on this instrument for this day",
  byPlan: "by plan", offPlan: "off plan", markIt: "mark",
  shareTip: "Share a summary of this trade alone",
  shareDay: "Share", shareTip2: "Share the day review by link",
  markMatch: "Market went as planned", markHold: "Held to the plan",

  sumTitle: "day summary", sumAssets: "instruments", sumTrades: "trades",
  colAsset: "instrument", colPlan: "plan", colFact: "what happened", colMatch: "as planned",
  colHold: "held to it", colRes: "result", lessonTitle: "what to take from it",

  closeDay: "Write the day up", writePlanFirst: "Write the plan first",
  closeNote: "When the day is over, press it: the plan stays on the left and room for the facts opens on the right, per instrument.",
  closeNoteOff: "The button turns on once any instrument has a plan: a direction, a level or a screenshot.",
  reopen: "← back to the plan",

  stPlayed: "Scenario played out", stPlayedNote: "days in the last month",
  stOff: "Trades off plan", stOffNote: "things you didn't plan in the morning",
  stCost: "What they cost", stCostNote: "total across those trades",
},
};

paintNav();

})();
