/* ============================================================
   Розділ «Аналіз дня».

   Не цифри дня, а розбір: що людина побачила на графіку зранку,
   який був план — і як ринок це відпрацював.

   Живе окремим файлом і сам додає себе у VIEWS, як «Новини» й
   «Моя ТС».

   Два вигляди одного дня:
     • день іде   — ліворуч форма плану, праворуч перелік того,
                    що з'явиться ввечері;
     • день закрито — розворот парами: 01 ліворуч завжди відповідає
                    01 праворуч.

   Усе, що набрано, лягає в базу (day_store.py), бо з цього
   рахується підсумок за місяць: чи справджувались сценарії і
   скільки коштували угоди поза планом.
   ============================================================ */
(function(){

let DATE = null;        /* який день дивимось, YYYY-MM-DD */
let N = undefined;      /* розбір дня: undefined — ще не питали, null — немає */
let STATS = null;       /* підсумок за 30 днів */
let hotShot = null;

function D(){ return DICT[window.LANG] || DICT.uk; }
function iso(d){
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
       + "-" + String(d.getDate()).padStart(2, "0");
}
function shift(days){
  const [y, m, d] = DATE.split("-").map(Number);
  const t = new Date(y, m - 1, d + days);
  DATE = iso(t);
  N = undefined;
  render();
}

/* ---------------- сервер ---------------- */
function blank(){
  return {closed: false, bias: {side: "", why: ""},
          levels: [{}, {}, {}], plans: [{}, {}], skip: "",
          shots: {}, fact: {}, marks: {}, trades: {}};
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
    N = demoAll()[want] || null;
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
    N = r.day || null;
  }catch(e){ N = null; }
  if (S.view === "day") render();
}

async function loadStats(){
  if (demo()){
    const all = demoAll();
    STATS = Object.keys(all).map(k => ({date: k, data: all[k],
      match: (all[k].marks || {}).match || "", hold: (all[k].marks || {}).hold || ""}));
    if (S.view === "day") render();
    return;
  }
  try{
    const r = await api("GET", "/api/day/stats");
    STATS = r.notes || [];
  }catch(e){ STATS = []; }
  if (S.view === "day") render();
}

let saveTimer = null;
function save(){
  /* гість може все розглядати, але не записувати: щойно він спробував
     зберегти значення — кличемо завести свій журнал */
  if (window.Guest && Guest.block(T.gsGateTitle)) return;
  STATS = null;                                /* підсумок доведеться перерахувати */
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

/* ---------------- скріни ---------------- */
function shotBox(key, cap){
  const f = (N.shots || {})[key];
  const d = D();
  return '<div class="dv-shot' + (f ? " has" : "") + '" data-shot="' + key + '">'
    + (f ? '<img alt="" src="' + esc(/^data:/.test(f) ? f : "/dnshot/" + f)
           + '"><button class="rm" type="button">×</button>'
         : '<div class="ph"><b>+</b>' + esc(cap) + "<em>" + esc(d.shotHint) + "</em></div>")
    + "</div>";
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

async function upload(el, dataUrl){
  if (demo()){
    if (!N.shots) N.shots = {};
    N.shots[el.dataset.shot] = dataUrl;
    save(); render();
    return;
  }
  el.classList.add("busy");
  try{
    const r = await api("POST", "/api/day/shot", {data: dataUrl});
    if (!N.shots) N.shots = {};
    N.shots[el.dataset.shot] = r.file;
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

/* ---------------- шматки ---------------- */
function biasEd(){
  const d = D(), cur = (N.bias || {}).side || "";
  const b = (val, cls) => '<button class="' + (cur === val ? "on " + (cls || "") : "")
    + '" onclick="__dv.side(this.dataset.v)" data-v="' + val + '">' + esc(val) + "</button>";
  return '<div class="dv-bias"><div class="dv-pick">'
    + b(d.long) + b(d.short, "down") + b(d.flat, "flat") + "</div></div>"
    + ed("bias.why", d.phWhy, true);
}

function levelsEd(){
  const d = D();
  const rows = (N.levels || []).map((l, i) =>
    '<div class="dv-lvr"><span class="p">' + ed("levels." + i + ".p", d.phPrice) + "</span>"
    + '<span class="t">' + ed("levels." + i + ".t", d.phWhat) + "</span>"
    + '<span class="n">' + ed("levels." + i + ".n", d.phWhy2) + "</span>"
    + '<button class="dv-add" style="margin:0" onclick="__dv.delLevel(' + i + ')">×</button>'
    + "</div>").join("");
  return '<div class="dv-lv">' + rows + "</div>"
    + '<button class="dv-add" onclick="__dv.addLevel()">+ ' + esc(d.addLevel) + "</button>";
}

function plansEd(){
  const d = D();
  return '<div class="dv-sc">'
    + '<div class="dv-scr main"><span class="k">A</span><span class="tx">'
    +   ed("plans.0.tx", d.phPlanA, true) + "</span></div>"
    + '<div class="dv-scr"><span class="k">Б</span><span class="tx">'
    +   ed("plans.1.tx", d.phPlanB, true) + "</span></div>"
    + "</div>";
}

function skipEd(){
  const d = D();
  return ed("skip", d.phSkip, true)
    + '<div class="dv-auto"><b>' + esc(d.autoTag) + "</b>" + esc(d.newsAuto) + "</div>";
}

function levelsDone(){
  const d = D();
  return '<div class="dv-lvd">' + (N.levels || []).map((l, i) =>
    '<div class="dv-lvr2 ' + (l.dcls || "") + '"><span class="p">' + esc(l.p || "—") + "</span>"
    + '<button class="dv-hit" type="button" title="' + esc(d.hitTip)
    + '" onclick="__dv.hit(' + i + ')"></button>'
    + '<span class="n">' + ed("levels." + i + ".did", d.phDid) + "</span></div>").join("")
    + "</div>";
}

function dayTrades(){
  return (S.trades || []).filter(t => t.date === DATE && !t.hidden);
}

function tradesHtml(){
  const d = D();
  const list = dayTrades();
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
    + '<div class="dv-auto"><b>' + esc(d.autoTag) + "</b>" + esc(d.tradesAuto) + "</div>";
}

function marksEd(){
  const d = D();
  const one = (key, label) => {
    const cur = (N.marks || {})[key] || "";
    const b = t => '<button class="' + (cur === t ? "on" : "") + '" data-k="' + key
      + '" data-v="' + t + '" onclick="__dv.mark(this.dataset.k, this.dataset.v)">' + esc(t) + "</button>";
    return "<div><div class=\"k\">" + esc(label) + '</div><div class="dv-pick">'
      + b(d.yes) + b(d.partly) + b(d.no) + "</div></div>";
  };
  return '<div class="dv-marks">' + one("match", d.markMatch) + one("hold", d.markHold) + "</div>";
}

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

/* ---------------- два вигляди ---------------- */
function head(){
  const d = D();
  const today = iso(new Date());
  const nice = human(DATE);
  return '<div class="vhead"><h1>' + esc(d.title) + "</h1>"
    + '<span class="sub">' + esc(nice) + (DATE === today ? " · " + esc(d.today) : "") + "</span>"
    + '<span class="dv-nav">'
    +   '<button onclick="__dv.go(-1)">←</button>'
    +   '<span class="day">' + esc(DATE) + "</span>"
    +   '<button onclick="__dv.go(1)">→</button>'
    +   (DATE === today ? "" : '<button onclick="__dv.today()">' + esc(d.today) + "</button>")
    + "</span></div>";
}

function human(dt){
  const [y, m, dd] = dt.split("-").map(Number);
  const date = new Date(y, m - 1, dd);
  const wd = (T.wds || [])[(date.getDay() + 6) % 7] || "";
  const mon = (T.monthsGen || T.months || [])[m - 1] || "";
  return wd + ", " + dd + " " + mon;
}

function vOpen(){
  const d = D();
  const ready = !!((N.bias || {}).side || (N.plans || [])[0] && N.plans[0].tx
                   || (N.levels || []).some(l => l.p));
  return head()
    + '<p class="dv-hint">' + esc(d.hintOpen) + "</p>"
    + '<div class="dv-sp"><div class="dv-two">'
    +   '<div class="col left">'
    +     '<div class="dv-blk"><div class="dv-pt"><b>01</b>' + esc(d.p1) + "<i>" + esc(d.p1s) + "</i></div>"
    +       shotBox("plan", d.shotPlan) + "</div>"
    +     '<div class="dv-blk"><div class="dv-pt"><b>02</b>' + esc(d.p2) + "<i>" + esc(d.p2s) + "</i></div>"
    +       biasEd() + "</div>"
    +     '<div class="dv-blk"><div class="dv-pt"><b>03</b>' + esc(d.p3) + "<i>" + esc(d.p3s) + "</i></div>"
    +       levelsEd() + "</div>"
    +     '<div class="dv-blk"><div class="dv-pt"><b>04</b>' + esc(d.p4) + "<i>" + esc(d.p4s) + "</i></div>"
    +       plansEd() + "</div>"
    +     '<div class="dv-blk"><div class="dv-pt"><b>05</b>' + esc(d.p5) + "<i>" + esc(d.p5s) + "</i></div>"
    +       skipEd() + "</div>"
    +   "</div>"
    +   '<div class="col"><div class="dv-wait">'
    +     '<div class="ttl">' + esc(d.waitTitle) + "</div>"
    +     '<p class="sub">' + esc(d.waitSub) + "</p><ul>"
    +       '<li><span>01</span><div>' + d.w1 + "</div></li>"
    +       '<li><span>02</span><div>' + d.w2 + "</div></li>"
    +       '<li><span>03</span><div>' + d.w3 + "</div></li>"
    +       '<li><span>04</span><div>' + d.w4 + "</div></li>"
    +       '<li><span>05</span><div>' + d.w5 + "</div></li>"
    +     "</ul>"
    +     '<button class="go" onclick="__dv.close()"' + (ready ? "" : " disabled") + ">"
    +       esc(ready ? d.closeDay : d.writePlanFirst) + "</button>"
    +     '<p class="note">' + esc(ready ? d.closeNote : d.closeNoteOff) + "</p>"
    +   "</div></div>"
    + "</div></div>" + strip();
}

function vClosed(){
  const d = D();
  const pair = (n, lt, ls, lb, rt, rs, rb) =>
    '<div class="dv-pair">'
    + '<div class="dv-cell"><div class="dv-pt"><b>' + n + "</b>" + esc(lt) + "<i>" + esc(ls)
    +   "</i></div>" + lb + "</div>"
    + '<div class="dv-cell"><div class="dv-pt"><b>' + n + "</b>" + esc(rt) + "<i>" + esc(rs)
    +   "</i></div>" + rb + "</div>"
    + "</div>";

  return head()
    + '<p class="dv-hint">' + esc(d.hintClosed) + "</p>"
    + '<div class="dv-sp">'
    +   '<div class="dv-head"><span>' + esc(d.morning) + ' <b class="plan">' + esc(d.planTag) + "</b></span>"
    +     "<span>" + esc(d.evening) + ' <b class="fact">' + esc(d.factTag) + "</b></span></div>"
    +   pair("01", d.p1, d.p1s, shotBox("plan", d.shotPlan),
                d.q1, d.q1s, shotBox("fact", d.shotFact))
    +   pair("02", d.p2, d.p2s, biasEd(),
                d.q2, d.q2s, ed("fact.text", d.phFact, true))
    +   pair("03", d.p3, d.p3s, levelsEd(),
                d.q3, d.q3s, levelsDone())
    +   pair("04", d.p4, d.p4s, plansEd(),
                d.q4, d.q4s, tradesHtml())
    +   pair("05", d.p5, d.p5s, skipEd(),
                d.q5, d.q5s, marksEd() + '<div class="dv-lesson" style="margin-top:16px">'
                + ed("fact.lesson", d.phLesson, true) + "</div>")
    + "</div>"
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

  const sl = e.target.closest && e.target.closest(".dv-shot[data-shot]");
  if (sl){
    if (e.target.closest(".rm")){
      e.stopPropagation();
      if (N.shots) delete N.shots[sl.dataset.shot];
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

document.addEventListener("mouseover", e => {
  const sl = e.target.closest && e.target.closest(".dv-shot[data-shot]");
  if (sl) hotShot = sl;
});
document.addEventListener("paste", e => {
  if (S.view !== "day" || !N) return;
  if (e.target.closest && e.target.closest("input,textarea")) return;
  const files = (e.clipboardData && e.clipboardData.files) || [];
  if (!files.length) return;
  const el = (hotShot && document.body.contains(hotShot))
    ? hotShot : document.querySelector(".dv-shot[data-shot]:not(.has)");
  if (!el) return;
  e.preventDefault();
  takeFile(files[0], el);
});
document.addEventListener("dragover", e => {
  if (e.target.closest && e.target.closest(".dv-shot[data-shot]")) e.preventDefault();
});
document.addEventListener("drop", e => {
  const el = e.target.closest && e.target.closest(".dv-shot[data-shot]");
  if (!el) return;
  e.preventDefault();
  takeFile(e.dataTransfer.files[0], el);
});

/* ---------------- назовні ---------------- */
window.__dv = {
  go: shift,
  today(){ DATE = iso(new Date()); N = undefined; render(); },
  side(v){
    if (!N.bias) N.bias = {};
    N.bias.side = (N.bias.side === v ? "" : v);
    save(); render();
  },
  mark(k, v){
    if (!N.marks) N.marks = {};
    N.marks[k] = (N.marks[k] === v ? "" : v);
    save(); render();
  },
  hit(i){
    const cycle = {"": "ok", ok: "mid", mid: "no", no: ""};
    N.levels[i].dcls = cycle[N.levels[i].dcls || ""];
    save(); render();
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
  addLevel(){ (N.levels = N.levels || []).push({}); save(); render(); },
  delLevel(i){ N.levels.splice(i, 1); save(); render(); },
  close(){ N.closed = true; save(); render(); },
  reopen(){ N.closed = false; save(); render(); },
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
  loading: "Хвилинку…", today: "сьогодні",
  long: "Long", short: "Short", flat: "Нейтрально",
  yes: "так", partly: "частково", no: "ні",

  hintOpen: "Ліворуч заповнюєш зранку. Права половина чекає вечора — там майже все підтягнеться саме.",
  hintClosed: "Ліворуч — те, що написав зранку, праворуч — що з цього вийшло. "
            + "Рядки стоять парами: 01 ліворуч відповідає 01 праворуч.",
  morning: "Ранок", evening: "Вечір", planTag: "план", factTag: "факт",

  p1: "Графік зранку", p1s: "скрін розмітки",
  p2: "Куди дивишся", p2s: "лонг чи шорт і чому",
  p3: "Рівні, які відмітив", p3s: "ціна і що це",
  p4: "Що плануєш робити", p4s: "сценарії на день",
  p5: "Чого не робити", p5s: "правила на день",

  q1: "Той самий графік увечері", q1s: "як усе закінчилось",
  q2: "Куди ринок пішов", q2s: "своїми словами",
  q3: "Що з ними сталось", q3s: "по кожному рівню",
  q4: "Що зробив насправді", q4s: "угоди з журналу",
  q5: "Чи втримався", q5s: "і що з цього винести",

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
  shotHint: "клік · Ctrl+V · перетягни",

  autoTag: "саме", newsAuto: "Новини на сьогодні беруться з розділу «Новини»",
  tradesAuto: "Угоди підтягуються з журналу — тут їх не набирають",
  noTrades: "За цей день угод у журналі немає",
  byPlan: "за планом", offPlan: "поза планом", markIt: "позначити",
  shareTip: "Поділитись зведенням саме по цій угоді",
  markMatch: "Ринок пішов за планом", markHold: "Тримався плану",

  waitTitle: "Вечір · ще попереду",
  waitSub: "Повернешся сюди після торгів. Набирати руками майже нічого не доведеться:",
  w1: "Графік увечері — <b>один скрін</b>, той самий інструмент",
  w2: "Куди ринок пішов — <b>одне речення</b> своїми словами",
  w3: "Що з рівнями сталось — <b>позначиш по кожному</b>",
  w4: "Угоди дня — <b>підтягнуться з журналу самі</b>",
  w5: "Чи втримався і висновок — <b>дві кнопки й рядок</b>",
  closeDay: "Записати підсумок дня", writePlanFirst: "Спершу запиши план",
  closeNote: "день закінчився — відкриється друга половина",
  closeNoteOff: "кнопка ввімкнеться, коли зʼявиться план",
  reopen: "← повернутись до плану",

  stPlayed: "Сценарій зіграв", stPlayedNote: "днів за останній місяць",
  stOff: "Угод поза планом", stOffNote: "взяв те, чого зранку не планував",
  stCost: "Скільки вони коштували", stCostNote: "разом по цих угодах",
},

ru: {
  title: "Анализ дня", navTip: "Что планировал утром — и как оно отработало",
  loading: "Минутку…", today: "сегодня",
  long: "Long", short: "Short", flat: "Нейтрально",
  yes: "да", partly: "частично", no: "нет",

  hintOpen: "Слева заполняешь утром. Правая половина ждёт вечера — там почти всё подтянется само.",
  hintClosed: "Слева — то, что написал утром, справа — что из этого вышло. "
            + "Строки стоят парами: 01 слева отвечает 01 справа.",
  morning: "Утро", evening: "Вечер", planTag: "план", factTag: "факт",

  p1: "График утром", p1s: "скрин разметки",
  p2: "Куда смотришь", p2s: "лонг или шорт и почему",
  p3: "Уровни, которые отметил", p3s: "цена и что это",
  p4: "Что планируешь делать", p4s: "сценарии на день",
  p5: "Чего не делать", p5s: "правила на день",

  q1: "Тот же график вечером", q1s: "как всё закончилось",
  q2: "Куда рынок пошёл", q2s: "своими словами",
  q3: "Что с ними стало", q3s: "по каждому уровню",
  q4: "Что сделал на самом деле", q4s: "сделки из журнала",
  q5: "Удержался ли", q5s: "и что из этого вынести",

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
  shotHint: "клик · Ctrl+V · перетащи",

  autoTag: "само", newsAuto: "Новости на сегодня берутся из раздела «Новини»",
  tradesAuto: "Сделки подтягиваются из журнала — тут их не набирают",
  noTrades: "За этот день сделок в журнале нет",
  byPlan: "по плану", offPlan: "вне плана", markIt: "отметить",
  shareTip: "Поделиться сводкой именно по этой сделке",
  markMatch: "Рынок пошёл по плану", markHold: "Держался плана",

  waitTitle: "Вечер · ещё впереди",
  waitSub: "Вернёшься сюда после торгов. Набирать руками почти ничего не придётся:",
  w1: "График вечером — <b>один скрин</b>, тот же инструмент",
  w2: "Куда рынок пошёл — <b>одно предложение</b> своими словами",
  w3: "Что с уровнями стало — <b>отметишь по каждому</b>",
  w4: "Сделки дня — <b>подтянутся из журнала сами</b>",
  w5: "Удержался и вывод — <b>две кнопки и строка</b>",
  closeDay: "Записать итог дня", writePlanFirst: "Сначала запиши план",
  closeNote: "день закончился — откроется вторая половина",
  closeNoteOff: "кнопка включится, когда появится план",
  reopen: "← вернуться к плану",

  stPlayed: "Сценарий сыграл", stPlayedNote: "дней за последний месяц",
  stOff: "Сделок вне плана", stOffNote: "взял то, чего утром не планировал",
  stCost: "Сколько они стоили", stCostNote: "вместе по этим сделкам",
},

en: {
  title: "Day review", navTip: "What you planned in the morning — and how it played out",
  loading: "One moment…", today: "today",
  long: "Long", short: "Short", flat: "Neutral",
  yes: "yes", partly: "partly", no: "no",

  hintOpen: "You fill the left side in the morning. The right half waits for the evening — most of it fills itself.",
  hintClosed: "Left is what you wrote in the morning, right is what came of it. "
            + "Rows are paired: 01 on the left answers 01 on the right.",
  morning: "Morning", evening: "Evening", planTag: "plan", factTag: "fact",

  p1: "Chart in the morning", p1s: "screenshot of your markup",
  p2: "Which way you look", p2s: "long or short and why",
  p3: "Levels you marked", p3s: "price and what it is",
  p4: "What you plan to do", p4s: "scenarios for the day",
  p5: "What not to do", p5s: "rules for the day",

  q1: "The same chart in the evening", q1s: "how it ended",
  q2: "Where the market went", q2s: "in your own words",
  q3: "What happened to them", q3s: "level by level",
  q4: "What you actually did", q4s: "trades from the journal",
  q5: "Did you hold to it", q5s: "and what to take from it",

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
  shotHint: "click · Ctrl+V · drop",

  autoTag: "auto", newsAuto: "Today's news comes from the News section",
  tradesAuto: "Trades come from the journal — no typing here",
  noTrades: "No trades in the journal for this day",
  byPlan: "by plan", offPlan: "off plan", markIt: "mark",
  shareTip: "Share a summary of this trade alone",
  markMatch: "Market went as planned", markHold: "Held to the plan",

  waitTitle: "Evening · still ahead",
  waitSub: "You'll come back after the session. Almost nothing to type:",
  w1: "Evening chart — <b>one screenshot</b>, same instrument",
  w2: "Where the market went — <b>one sentence</b> in your own words",
  w3: "What happened to the levels — <b>you mark each one</b>",
  w4: "Trades of the day — <b>pulled from the journal</b>",
  w5: "Held to it and the lesson — <b>two buttons and a line</b>",
  closeDay: "Write the day up", writePlanFirst: "Write the plan first",
  closeNote: "the day is over — the second half opens",
  closeNoteOff: "the button turns on once there is a plan",
  reopen: "← back to the plan",

  stPlayed: "Scenario played out", stPlayedNote: "days in the last month",
  stOff: "Trades off plan", stOffNote: "things you didn't plan in the morning",
  stCost: "What they cost", stCostNote: "total across those trades",
},
};

paintNav();

})();
