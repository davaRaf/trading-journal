/* ============================================================
   Розділ «Моя ТС» — торгова стратегія людини.

   Живе окремим файлом і сам додає себе у VIEWS, як і «Новини»,
   щоб не заважати правкам в app.js.

   Що вміє:
     • порожній стан — два шляхи: зібрати з нуля або підтягнути з Notion
     • опитування по одному питанню на екран
     • готова ТС розділами, кожне поле правиться на місці
     • слот під скрін біля кожного правила: клік, Ctrl+V або перетягування
     • звірка написаного з тим, що насправді в журналі

   Свій словник тут же, унизу файлу: щоб не змішувати з i18n.js,
   поки розділ ще ворушиться.
   ============================================================ */
(function(){

/* ---------------- стан ---------------- */
let TS = undefined;        /* undefined — ще не питали сервер, null — немає ТС */
let busy = false;          /* тягнемо з Notion */
let pullErr = "";
let hotShot = null;        /* слот, куди піде Ctrl+V */
/* Посилання, з яких тягнемо ТС. Їх кілька, бо в Notion систему тримають
   розділами: контекст на одній сторінці, моделі входу на іншій. Порожній
   рядок унизу — місце під наступне посилання. */
let srcUrls = [""];
let armed = null;          /* слот, обраний кліком */

/* На телефоні Ctrl+V немає: тап читає буфер сам, два тапи — файли (ShotTap
   в ui.js). На комп'ютері клік лише націлює слот. */
function touchOnly(){
  return window.matchMedia && matchMedia("(hover: none)").matches;
}
function hintText(d){ return touchOnly() ? d.shotHintTouch : d.shotHint; }
/* коротке повідомлення в самому слоті — і назад до підказки */
function flashHint(sl, text){
  const em = sl.querySelector(".ph em");
  if (!em) return;
  em.textContent = text;
  setTimeout(() => { if (document.body.contains(em)) em.textContent = hintText(D()); }, 2400);
}

/* Підсвічуємо націлений слот на місці, без перемальовки розділу: інакше
   до другого кліку доживає вже інший вузол і подвійний клік не працює. */
function paintArmed(){
  const d = D();
  document.querySelectorAll(".ts-shot[data-p]").forEach(el => {
    const on = el.dataset.p === armed;
    el.classList.toggle("armed", on);
    const em = el.querySelector(".ph em");
    if (em) em.textContent = on ? d.shotArmed : hintText(d);
  });
}

function D(){ return DICT[window.LANG] || DICT.uk; }

/* ---------------- сервер ----------------
   У публічному демо сервера немає — там ТС живе в браузері, як і угоди.
   Скрін у демо лишається картинкою всередині документа: класти його
   нікуди. */
const DEMO_KEY = "statsai_ts_demo";
function demo(){ return typeof DEMO !== "undefined" && DEMO; }

async function load(){
  if (demo()){
    try{ TS = normalize(JSON.parse(localStorage.getItem(DEMO_KEY) || "null")); }catch(e){ TS = null; }
    /* Перемальовуємо не одразу: у демо дані лежать у браузері й читаються
       миттєво, тому виклик прилітає всередину того самого render(), який
       нас і покликав, — і його результат затирає наш. Через таймер розділ
       домальовується вже після нього. */
    setTimeout(() => { if (S.view === "ts") render(); }, 0);
    return;
  }
  try{
    const r = await api("GET", "/api/ts" + (btOn() ? "?kind=bt" : ""));
    TS = (r && r.ts && Object.keys(r.ts).length) ? normalize(r.ts) : null;
  }catch(e){ TS = null; }
  if (S.view === "ts") render();
}

let saveTimer = null;
function save(){
  if (window.Guest && Guest.block(T.gsGateTs)) return;
  if (demo()){
    try{ localStorage.setItem(DEMO_KEY, JSON.stringify(TS)); }catch(e){}
    return;
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api("POST", "/api/ts", {ts: TS, kind: btOn()?"bt":""}).catch(() => {});
  }, 400);
}

/* Стара ТС тримала біля моделі рівно один скрін (models[i].shot).
   Прикладів входу зазвичай більше одного, тож тепер це список shots[].
   Старі записи піднімаємо на новий вид одразу після завантаження, щоб
   решта коду знала лише про список. */
function normalize(ts){
  if (!ts) return ts;
  [].concat(ts.models || [], ts.setups || []).forEach(m => {
    if (!Array.isArray(m.shots)) m.shots = m.shot ? [m.shot] : [];
    delete m.shot;
  });
  return ts;
}

/* ---------------- шлях до поля ----------------
   Поля правляться на місці, тож кожному треба адреса: "risk.per",
   "tfs.2.what". Так один обробник обслуговує всю сторінку. */
function get(path){
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), TS);
}
function set(path, val){
  const keys = path.split(".");
  let o = TS;
  for (let i = 0; i < keys.length - 1; i++){
    if (o[keys[i]] == null) o[keys[i]] = /^\d+$/.test(keys[i+1]) ? [] : {};
    o = o[keys[i]];
  }
  o[keys[keys.length - 1]] = val;
}

/* ---------------- дрібне ---------------- */
function ed(path, cls, ph){
  const v = get(path);
  const blank = !v && v !== 0;
  return '<span class="ts-ed' + (blank ? " blank" : "") + (cls ? " " + cls : "")
    + '" data-p="' + path + '">' + esc(blank ? (ph || D().empty) : v) + "</span>";
}
function edArea(path, ph){
  const v = get(path);
  const blank = !v;
  return '<span class="ts-ed multi' + (blank ? " blank" : "") + '" data-p="' + path
    + '" data-multi="1">' + esc(blank ? (ph || D().empty) : v) + "</span>";
}
function x(path, i){
  return '<button class="ts-x" type="button" title="' + D().remove
    + '" onclick="__ts.del(\'' + path + '\',' + i + ')">×</button>';
}
function add(path, label){
  return '<button class="ts-add" type="button" onclick="__ts.add(\'' + path + '\')">+ '
    + esc(label) + "</button>";
}
/* Значок «сюди йде картинка»: раніше в слоті стояв самий «+», і слот
   читався як щось службове, а не як місце під скрін. */
const SHOT_IC = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
  + ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/>'
  + '<circle cx="8.6" cy="10" r="1.5"/>'
  + '<path d="M20.5 15.2l-4.1-3.9a1.6 1.6 0 0 0-2.2 0L5.2 19.5"/></svg>';

/* Ім'я файлу на сервері або сама картинка (демо) */
function tsShotSrc(f){ return /^data:/.test(f) ? f : "/tsshot/" + f; }

const RP_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
  + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>';

function shot(path, label, mini){
  const f = get(path);
  const inner = f
    ? '<img alt="" src="' + esc(tsShotSrc(f)) + '"><div class="over"><span>' + esc(D().shotOpen)
      + '</span></div><button class="rp" type="button" title="' + esc(D().shotReplace) + '">'
      + RP_IC + '</button><button class="rm" type="button" title="' + esc(D().remove) + '">×</button>'
    : '<div class="ph">' + SHOT_IC + esc(label || D().shotAdd)
      + "<em>" + esc(armed === path ? D().shotArmed : hintText(D())) + "</em></div>";
  return '<div class="ts-shot' + (f ? " has" : "") + (mini ? " mini" : "")
    + (armed === path ? " armed" : "") + '" data-p="' + path + '">' + inner + "</div>";
}

/* ================= порожній стан ================= */
function vNone(){
  const d = D();
  /* заголовка «Моя ТС» тут немає: порожній стан має власний — «Ще немає торгової стратегії» */
  return '<div class="ts-none">'
    +   "<h2>" + esc(d.noneTitle) + "</h2>"
    +   '<p class="lead">' + d.noneLead + "</p>"
    +   '<div class="ts-ways">'
    +     '<div class="ts-way hot"><div class="ic">+</div>'
    +       "<h3>" + esc(d.wayNewTitle) + "</h3><p>" + esc(d.wayNewText) + "</p>"
    +       '<div class="foot"><button class="ts-big" onclick="__ts.ask()">' + esc(d.wayNewBtn)
    +         '</button><span class="mins">' + esc(d.wayNewMins) + "</span></div></div>"
    +     '<div class="ts-way"><div class="ic">⧉</div>'
    +       "<h3>" + esc(d.wayNotionTitle) + "</h3><p>" + esc(d.wayNotionText) + "</p>"
    +       '<div class="foot">'
    +         (busy ? '<div class="ts-load"><i></i><span>' + esc(d.pulling) + "</span></div>" : "")
    +         (pullErr ? '<p class="ts-err">' + esc(pullErr) + "</p>" : "")
    +         urlFields()
    +         '<p class="hint">' + d.wayNotionHint + "</p></div></div>"
    +   "</div>"
    +   '<div class="ts-why"><p class="ts-sub2">' + esc(d.whyTitle) + "</p><ul>"
    +     "<li>" + d.why1 + "</li><li>" + d.why2 + "</li><li>" + d.why3 + "</li></ul>"
    +     '<p class="after">' + esc(d.whyAfter) + "</p></div>"
    + "</div>";
}

/* Поля під посилання: скільки завгодно, останнє порожнє — під наступне.
   Значення тримаємо в srcUrls, бо розділ перемальовується цілком (спінер,
   помилка), і те, що людина вже вставила, інакше зникало б. */
function urlFields(){
  const d = D();
  const dis = busy ? " disabled" : "";
  let h = "";
  srcUrls.forEach((u, i) => {
    h += '<div class="ts-paste"><input type="text" class="ts-url" data-i="' + i
      + '" value="' + esc(u) + '" placeholder="' + esc(d.wayNotionPh) + '"' + dis + ">"
      + (srcUrls.length > 1
          ? '<button class="ghost" title="' + esc(d.srcDrop) + '" onclick="__ts.srcDrop('
            + i + ')"' + dis + ">×</button>"
          : "")
      + (i === srcUrls.length - 1
          ? '<button onclick="__ts.pull()"' + dis + ">" + esc(d.wayNotionBtn) + "</button>"
          : "")
      + "</div>";
  });
  h += '<button class="ts-more" onclick="__ts.srcAdd()"' + dis + ">+ "
    + esc(d.srcAdd) + "</button>";
  return h;
}

/* ================= заповнена ТС =================
   Паспорт зверху + вкладки (варіант B, 18.09.2026). Раніше тут стояли дев'ять
   карток підряд, і найпотрібніше перед угодою — чек-лист і «коли не входжу» —
   лежало в самому низу. Тепер ключові цифри завжди на виду, а решта розкладена
   по п'яти вкладках: на екрані одна тема за раз.

   Два режими. Звичайний — для читання: без пунктирів, порожніх полів і кнопок
   «+ додати», саме вони й робили сторінку «напханою». Кнопка «Редагувати»
   вмикає правку — і все це з'являється. Дані ТС ті самі, що й були: змінилась
   лише подача, тож старі стратегії відкриваються без жодного перенесення. */
let editing = false;
let menuOpen = false;
const TAB_KEY = "tj_ts_tab";
const TABS = ["before", "entry", "risk", "real", "extra"];
let tab = (() => {
  try{ const t = localStorage.getItem(TAB_KEY); return TABS.indexOf(t) >= 0 ? t : "before"; }
  catch(e){ return "before"; }
})();

const PEN_IC = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z" '
  + 'stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
const DONE_IC = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" '
  + 'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const SHARE_IC = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 15V4M7 9l5-5 5 5M5 14v4a2 2 0 002 2h10a2 2 0 002-2v-4" '
  + 'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const DOTS_IC = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="5" cy="12" r="1.7" fill="currentColor"/>'
  + '<circle cx="12" cy="12" r="1.7" fill="currentColor"/><circle cx="19" cy="12" r="1.7" fill="currentColor"/></svg>';

function card(title, inner, cls){
  return '<div class="tsv-card' + (cls ? " " + cls : "") + '">'
    + (title ? "<h3>" + esc(title) + "</h3>" : "") + inner + "</div>";
}
function lab(t){ return '<div class="tsv-lab">' + esc(t) + "</div>"; }
function subh(t){ return '<p class="tsv-subh">' + esc(t) + "</p>"; }
function none(t){ return '<div class="empty">' + esc(t) + "</div>"; }

/* ---------- паспорт: цифри, які мають бути на виду завжди ---------- */
function passport(){
  const d = D();
  const assets = TS.assets || [];
  const wins = TS.windows || [];
  const cell = (label, inner, cls) => '<div class="tsv-pc' + (cls ? " " + cls : "") + '">' + lab(label) + inner + "</div>";
  return '<div class="tsv-pass">'
    + cell(d.lAssets, '<div class="tsv-chips">'
        + assets.map((a, i) => '<span class="tsv-chip">' + ed("assets." + i) + x("assets", i) + "</span>").join("")
        + (assets.length ? "" : '<span class="tsv-none">' + esc(d.noneYet) + "</span>")
        + add("assets", d.addAsset) + "</div>", "wide")
    + cell(d.lWindows, '<div class="tsv-wins">'
        + wins.map((w, i) => "<div><b>" + ed("windows." + i + ".name", "", d.emptyName) + "</b> "
            + ed("windows." + i + ".time", "", d.emptyTime) + "</div>").join("")
        + (wins.length ? "" : '<span class="tsv-none">' + esc(d.noneYet) + "</span>") + "</div>", "wide")
    + cell(d.pRisk, '<div class="tsv-big">' + ed("risk.per") + "</div>")
    + cell(d.pRr, '<div class="tsv-big">' + ed("risk.rr") + "</div>")
    /* тижневий ліміт є не в кожного — порожній рядок «— тиждень» тільки заважав би */
    + cell(d.lLimits, '<div class="tsv-big">' + ed("risk.day") + "<small>" + esc(d.wDay) + "</small></div>"
        + ((get("risk.week") || editing)
            ? '<div class="tsv-big s">' + ed("risk.week") + "<small>" + esc(d.wWeek) + "</small></div>" : ""))
    + cell(d.pMax, '<div class="tsv-big">' + ed("maxtrades") + "</div>")
    + "</div>";
}

/* ---------- вкладка «Перед входом» ---------- */
function secCheck(){
  const d = D();
  const list = TS.check || [];
  /* Просто перелік правил — тим самим виглядом, що й у спільному посиланні.
     Галочок і лічильника «0 / 1» тут немає: «Моя ТС» описує систему, а не
     веде окрему угоду. */
  return (list.length
      ? '<div class="ts-q">' + list.map((c, i) =>
          '<div class="ts-qi"><i>' + String(i + 1).padStart(2, "0") + "</i>"
          + '<span class="t"><div class="ts-row">' + edArea("check." + i) + x("check", i)
          + "</div></span></div>").join("") + "</div>"
      : none(d.noCheck))
    + add("check", d.addCheck);
}

function secNo(){
  const d = D();
  const col = (key, label) => {
    const items = ((TS.no && TS.no[key]) || []);
    return '<div class="tsv-nog"><div class="h">' + esc(label) + "</div>"
      + (items.length
          ? '<ul class="ts-list">' + items.map((v, i) =>
              '<li><div class="ts-row">' + edArea("no." + key + "." + i) + x("no." + key, i)
              + "</div></li>").join("") + "</ul>"
          : '<p class="tsv-none">' + esc(d.noneYet) + "</p>")
      + add("no." + key, d.addLine) + "</div>";
  };
  const mind = get("mind");
  return '<div class="tsv-nogo">' + col("market", d.lNoMarket) + col("time", d.lNoTime)
    + col("self", d.lNoSelf) + "</div>"
    + ((mind || editing)
        ? '<div class="tsv-quote">' + lab(d.lMind) + edArea("mind", d.emptyMind) + "</div>" : "");
}

/* вікна з поясненнями, дні й новини — «коли я взагалі сідаю торгувати» */
function secWhen(){
  const d = D();
  const row = (k, v) => '<div class="tsv-kv"><div class="k">' + k + '</div><div class="v">' + v + "</div></div>";
  return row(esc(d.lTradeDays), ed("days")) + row(esc(d.lRedNews), ed("news"))
    + (TS.windows || []).map((w, i) => row(ed("windows." + i + ".name", "", d.emptyName),
        '<div class="ts-row"><span><b>' + ed("windows." + i + ".time", "", d.emptyTime) + "</b> "
        + ed("windows." + i + ".note", "", d.emptyNote) + "</span>" + x("windows", i) + "</div>")).join("")
    + add("windows", d.addWindow);
}

function tabBefore(){
  const d = D();
  return '<div class="tsv-two">' + card(d.secCheck, secCheck()) + card(d.secNo, secNo()) + "</div>"
    + card(d.secWhen, secWhen(), "tsv-gap");
}

/* ---------- вкладка «Як входжу» ---------- */
function secTf(){
  const d = D();
  const list = TS.tfs || [];
  /* Підпис до списку («якщо відкриття місяця, я заходжу подивитись…») стоїть
     окремим рядком над описом: це заголовок переліку, а не бирка збоку. */
  const rows = list.map((r, i) =>
    '<div class="tsv-card tsv-tf' + ((r.shot || editing) ? " sh" : "") + '">'
    + '<div class="tsv-tfh"><span class="n">' + ed("tfs." + i + ".tf", "", d.emptyTf) + "</span>" + x("tfs", i) + "</div>"
    + '<div class="what"><div class="role">' + ed("tfs." + i + ".role", "", d.emptyRole) + "</div>"
    + edArea("tfs." + i + ".what", d.emptyWhat) + "</div>"
    + shot("tfs." + i + ".shot") + "</div>").join("");
  return (rows ? '<div class="tsv-tfs">' + rows + "</div>" : none(d.noTfs)) + add("tfs", d.addTf);
}

/* Моделі входу, сетапи, супровід і «Додатково» — однакові картки: назва,
   пояснення і скріни. Малює їх один код, тож і виправляти вигляд — в одному
   місці. kk/vk — як у цьому списку звуться поля назви й тексту. */
function tiles(path, kk, vk, o){
  const d = D();
  const list = get(path) || [];
  if (!list.length) return none(o.none) + add(path, o.add);
  return '<div class="tsv-mods">' + list.map((m, i) => {
      const p = path + "." + i;
      const shots = m.shots || [];
      return '<div class="tsv-card tsv-mod"><div class="ts-row"><b class="nm">'
        + ed(p + "." + kk, "", o.phK) + "</b>" + x(path, i) + "</div>"
        + '<div class="note">' + edArea(p + "." + vk, o.phV) + "</div>"
        + '<div class="ts-shots">'
        +   shots.map((f, j) => shot(p + ".shots." + j, o.shot, true)).join("")
        +   shot(p + ".shots." + shots.length, shots.length ? d.shotAddShort : o.shot, true)
        + "</div></div>";
    }).join("") + "</div>" + add(path, o.add);
}

function secRules(){
  const d = D();
  const one = (label, path, shotPath) => card("", lab(label) + '<div class="v">' + edArea(path) + "</div>"
    + (shotPath ? '<div class="ts-shots">' + shot(shotPath, d.shotHow, true) + "</div>" : ""));
  return '<div class="tsv-rules">' + one(d.lBias, "bias") + one(d.lStop, "stop.v", "stop.shot")
    + one(d.lTarget, "target.v", "target.shot") + "</div>";
}

function tabEntry(){
  const d = D();
  return subh(d.secTf) + secTf()
    + subh(d.lModels) + tiles("models", "name", "note",
        {none: d.noModels, add: d.addModel, phK: d.emptyName, phV: d.emptyNote, shot: d.shotExample})
    + subh(d.lSetups) + tiles("setups", "name", "note",
        {none: d.noSetups, add: d.addSetup, phK: d.emptyName, phV: d.emptyNote, shot: d.shotExample})
    + subh(d.lRules) + secRules();
}

/* ---------- вкладка «Ризик і супровід» ---------- */
function secCases(){
  const d = D();
  const list = TS.riskCases || [];
  return card("", (list.length
      ? list.map((c, i) => '<div class="tsv-kv"><div class="k">' + ed("riskCases." + i + ".k") + "</div>"
          + '<div class="v"><div class="ts-row">' + edArea("riskCases." + i + ".v")
          + x("riskCases", i) + "</div></div></div>").join("")
      : none(d.noCases))
    + add("riskCases", d.addCase));
}

function tabRisk(){
  const d = D();
  return subh(d.secManage) + tiles("manage", "k", "v",
      {none: d.noManage, add: d.addRule, phK: d.emptyRule, phV: "", shot: d.shotHow})
    + subh(d.lRiskCases) + secCases();
}

/* ---------- вкладка «Звірка з журналом» ---------- */
function dayMap(list){
  const m = new Map();
  for (const t of list){
    const k = t.date || "";
    if (!k) continue;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(t);
  }
  return m;
}

function against(){
  const d = D();
  const list = (S.trades || []).filter(t => !t.hidden);
  if (list.length < 5) return '<div class="empty">' + esc(d.realFew) + "</div>";

  const rows = [];
  let kept = 0;
  const R = (nm, note, val, em, cls) => {
    if (cls === "pos") kept++;
    rows.push(
      '<div class="r"><div class="nm">' + esc(nm) + "<i>" + esc(note) + "</i></div>"
      + '<div class="v ' + cls + '">' + esc(val) + (em ? "<em>" + esc(em) + "</em>" : "") + "</div></div>");
  };

  const minRR = parseFloat(String((TS.risk || {}).rr || "").replace(",", "."));
  if (minRR > 0){
    const bad = list.filter(t => t.rr != null && t.rr < minRR - 1e-9);
    R(d.realRR, d.realRRNote.replace("%s", minRR),
      bad.length + " " + d.wTrades,
      Math.round(bad.length / list.length * 100) + "% " + d.wOfAll,
      bad.length ? "neg" : "pos");
  }

  const days = dayMap(list);
  const dayLim = parseFloat(String((TS.risk || {}).day || "").replace(",", ".").replace("%", ""));
  if (dayLim > 0){
    let over = 0, worst = 0;
    days.forEach(arr => {
      const net = arr.reduce((s, t) => s + netR(t), 0);
      if (net < -dayLim - 1e-9){ over++; if (net < worst) worst = net; }
    });
    R(d.realDay, d.realDayNote.replace("%s", dayLim + "%"),
      over + " " + d.wDays, over ? d.realWorst + " " + fmtR(worst) : d.realHold,
      over ? "neg" : "pos");
  }

  const maxT = parseInt(String(TS.maxtrades || "").replace(/\D/g, ""), 10);
  if (maxT > 0){
    let over = 0, most = 0;
    days.forEach(arr => { if (arr.length > maxT) over++; if (arr.length > most) most = arr.length; });
    R(d.realMax, d.realMaxNote.replace("%s", maxT),
      over + " " + d.wDays, d.realMost + " " + most, over ? "mid" : "pos");
  }

  const declared = parseFloat(String((TS.risk || {}).per || "").replace(",", ".").replace("%", ""));
  const withRisk = list.filter(t => t.risk != null && !isNaN(t.risk));
  if (declared > 0 && withRisk.length){
    const avg = withRisk.reduce((s, t) => s + t.risk, 0) / withRisk.length;
    const off = Math.abs(avg - declared) > declared * 0.25;
    R(d.realRisk, d.realRiskNote.replace("%s", declared + "%"),
      r1(avg) + "%", off ? d.realOff : d.realHold, off ? "mid" : "pos");
  }

  const models = (TS.models || []).map(m => (m.name || "").toLowerCase()).filter(Boolean);
  const withModel = list.filter(t => (t.entry_model || "").trim());
  if (models.length && withModel.length){
    const mine = withModel.filter(t => models.includes(t.entry_model.trim().toLowerCase()));
    const rest = {};
    withModel.filter(t => !models.includes(t.entry_model.trim().toLowerCase()))
      .forEach(t => { const k = t.entry_model.trim(); rest[k] = (rest[k] || 0) + 1; });
    const top = Object.keys(rest).sort((a, b) => rest[b] - rest[a]).slice(0, 3)
      .map(k => k + " " + rest[k]).join(", ");
    R(d.realModel, d.realModelNote.replace("%s", models.join(", ")),
      mine.length + " / " + withModel.length,
      top ? d.realOther + " " + top : d.realHold,
      mine.length === withModel.length ? "pos" : "mid");
  }

  if (!rows.length) return '<div class="empty">' + esc(d.realNeed) + "</div>";
  /* підсумок одним числом: скільки правил тримаються без жодного порушення */
  return '<div class="tsv-score"><b>' + kept + " / " + rows.length + "</b><span>" + esc(d.realScore) + "</span></div>"
    + '<div class="ts-cmp">' + rows.join("") + "</div>";
}

function tabReal(){
  const d = D();
  /* У бектесті звірка теж має сенс — «скільки разів прогін порушив правила».
     Але з заголовка має бути видно, по чому саме рахували. */
  const bt = typeof btOn === "function" && btOn();
  return card(d.secReal + " · " + (S.trades || []).length + " " + d.wTrades
              + (bt ? " · " + T.btTsNote : ""), against());
}

/* ---------- вкладка «Додатково» ---------- */
/* Звідки підтягнуто: список сторінок, з якими працюємо далі. Сюди ж
   додають наступну — контекст на одній сторінці, моделі входу на іншій.
   Перечитуємо завжди всі разом: інакше модель бачила б систему по шматку. */
function srcList(){
  const d = D();
  const n = TS.notion || {};
  const pages = (n.pages && n.pages.length) ? n.pages
    : (n.url ? [{url: n.url, title: ""}] : []);
  let h = "";
  if (pages.length) h += '<div class="ts-srcs">';
  h += pages.map((pg, i) => '<span class="ts-src"><a href="' + esc(pg.url)
      + '" target="_blank" rel="noopener">' + esc(pg.title || pg.url) + "</a>"
      + (pages.length > 1 && !busy
          ? '<button class="rm" title="' + esc(d.srcDrop)
            + '" onclick="__ts.srcOut(' + i + ')">×</button>'
          : "") + "</span>").join("");
  if (pages.length) h += "</div>";
  else h += '<p class="tsv-none" style="margin-bottom:12px">' + esc(d.srcNone) + "</p>";
  const bad = n.failed || [];
  if (bad.length){
    h += '<p class="ts-err">' + esc(d.srcFailed) + " "
      + bad.map(f => esc(f.url)).join(", ") + "</p>";
  }
  h += (busy ? '<div class="ts-load"><i></i><span>' + esc(d.pulling) + "</span></div>" : "")
    + (pullErr ? '<p class="ts-err">' + esc(pullErr) + "</p>" : "")
    + urlFields()
    + (pages.length ? '<p class="hint">' + esc(d.srcAgainWarn) + "</p>" : "");
  return h;
}

/* Сторінка з Notion, як ми її прочитали. Тримаємо поруч, бо розбір
   ніколи не витягне все: людина звіряє й дописує руками. Скріни, які
   не лягли до таймфреймів, теж лишаються тут, а не зникають. */
/* Сторінки Notion — окремою карткою й першими у вкладці. Систему тримають
   розділами на кількох сторінках, і після першого посилання людина шукала,
   куди вставити наступне: поле ховалось під нотатками, в картці з текстом. */
function secSources(){
  return card(D().secSources, srcList(), "tsv-src");
}

function secRaw(){
  const n = TS.notion || {};
  if (!n.text && !(n.shots || []).length) return "";
  const used = (TS.tfs || []).map(t => t.shot).filter(Boolean);
  const rest = (n.shots || []).filter(s => used.indexOf(s.file) < 0);
  return card(D().secRaw,
    (n.text ? '<p class="ts-sub2">' + esc(D().rawText) + '</p><div class="ts-raw">'
        + esc(n.text) + "</div>" : "")
    + (rest.length ? '<p class="ts-sub2">' + esc(D().rawShots) + '</p><div class="ts-shots">'
        + rest.map(s => '<div class="ts-shot has mini"><img alt="" src="'
            + esc(tsShotSrc(s.file)) + '"></div>').join("") + "</div>" : ""), "tsv-gap");
}

function tabExtra(){
  const d = D();
  return secSources()
    + subh(d.secExtra) + tiles("extra", "k", "v",
      {none: d.noExtra, add: d.addExtra, phK: d.emptyExtraK, phV: d.emptyExtraV, shot: d.shotHow})
    + secRaw();
}

function vFull(){
  const d = D();
  const tabsL = [["before", d.tabBefore], ["entry", d.tabEntry], ["risk", d.tabRisk],
                 ["real", d.tabReal], ["extra", d.tabExtra]];
  /* Біля назви розділу нічого не пишемо: звідки взялась ТС і коли її чіпали
     востаннє — службова дрібниця, а не заголовок. Головна дія одна —
     «Редагувати»; опитування й видалення пішли в меню «⋯». */
  let h = '<div class="tsv' + (editing ? " editing" : "") + '">';
  h += '<div class="vhead tsv-head"><h1>' + esc(d.title) + "</h1>"
    + '<span class="right">'
    +   '<button class="tsv-btn pri" type="button" onclick="__ts.edit()">'
    +     (editing ? DONE_IC + esc(d.btnDone) : PEN_IC + esc(d.btnEdit)) + "</button>"
    +   '<button class="tsv-btn share" type="button" onclick="__ts.share()">' + SHARE_IC
    +     "<span>" + esc(d.btnShare) + "</span></button>"
    +   '<span class="tsv-more"><button class="tsv-btn ic" type="button" aria-haspopup="menu" aria-expanded="'
    +     menuOpen + '" aria-label="' + esc(d.btnMore) + '" title="' + esc(d.btnMore)
    +     '" onclick="__ts.menu()">' + DOTS_IC + "</button>"
    +     (menuOpen
          ? '<div class="tsv-menu" role="menu">'
            + '<button type="button" role="menuitem" class="m-share" onclick="__ts.share()">' + esc(d.btnShare) + "</button>"
            + '<button type="button" role="menuitem" onclick="__ts.srcOpen()">' + esc(d.btnNotion) + "</button>"
            + '<button type="button" role="menuitem" onclick="__ts.ask()">' + esc(d.btnAsk) + "</button>"
            + '<button type="button" role="menuitem" class="danger" onclick="__ts.wipe()">' + esc(d.btnDelete) + "</button>"
            + "</div>"
          : "")
    +   "</span></span></div>";
  if (editing){
    h += '<div class="tsv-editbar"><p>' + d.editTip + "</p>"
      + '<button class="tsv-btn" type="button" onclick="__ts.edit()">' + esc(d.btnDone) + "</button></div>";
  }
  h += passport();
  h += '<div class="tsv-tabs" role="tablist">' + tabsL.map(([id, l]) =>
      '<button type="button" role="tab" aria-selected="' + (id === tab) + '"' + (id === tab ? ' class="on"' : "")
      + ' onclick="__ts.tab(\'' + id + '\')">' + esc(l) + "</button>").join("") + "</div>";
  h += '<div class="tsv-panel">'
    + ({before: tabBefore, entry: tabEntry, risk: tabRisk, real: tabReal, extra: tabExtra}[tab])()
    + "</div>";
  return h + "</div>";
}

function vTS(){
  if (TS === undefined){
    load();
    return '<div class="empty">' + esc(D().loading) + "</div>";
  }
  return TS ? vFull() : vNone();
}
VIEWS.ts = vTS;

/* ================= правка на місці ================= */
function startEdit(el){
  if (el.querySelector("input,textarea")) return;
  const path = el.dataset.p;
  const multi = el.dataset.multi === "1";
  const val = get(path);
  const f = document.createElement(multi ? "textarea" : "input");
  f.className = "ts-in";
  f.value = (val == null ? "" : val);
  el.textContent = "";
  el.appendChild(f);

  /* Багаторядкове поле відкривається рівно під свій текст і росте вниз у міру
     набору. Фіксована висота на 74px була стрибком: клікнув по одному рядку —
     а тобі розсунуло півсторінки. Спершу ставимо теперішню висоту, і вже з неї
     наступним кадром їдемо до нової — інакше transition нема від чого рахувати. */
  if (multi){
    const grow = () => {
      const now = f.style.height;
      f.style.height = "auto";
      /* +2 — рамка: при border-box height її враховує, а scrollHeight ні */
      const need = (f.scrollHeight + 2) + "px";
      if (now && now !== need){
        f.style.height = now;
        requestAnimationFrame(() => { f.style.height = need; });
      } else f.style.height = need;
    };
    grow();
    f.addEventListener("input", grow);
  }

  f.focus();
  if (f.setSelectionRange) f.setSelectionRange(f.value.length, f.value.length);

  let done = false;
  const commit = ok => {
    if (done) return;
    done = true;
    if (ok){
      set(path, f.value.trim());
      TS.updated = today();
      save();
    }
    render();
  };
  f.addEventListener("blur", () => commit(true));
  f.addEventListener("keydown", e => {
    if (e.key === "Escape"){ e.stopPropagation(); commit(false); }
    if (e.key === "Enter" && (!multi || e.ctrlKey || e.metaKey)){ e.preventDefault(); commit(true); }
  });
}

/* ================= слоти під скріни ================= */
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
    set(el.dataset.p, dataUrl);
    TS.updated = today();
    save(); render();
    return;
  }
  el.classList.add("busy");
  try{
    const r = await api("POST", "/api/ts/shot", {data: dataUrl});
    set(el.dataset.p, r.file);
    TS.updated = today();
    save();
  }catch(e){}
  el.classList.remove("busy");
  render();
}

function takeFile(file, el){
  armed = null;
  if (!file || !/^image\//.test(file.type)) return;
  const fr = new FileReader();
  fr.onload = () => shrink(fr.result, u => upload(el, u));
  fr.readAsDataURL(file);
}

const filePick = document.createElement("input");
filePick.type = "file";
filePick.accept = "image/*";
filePick.style.display = "none";
document.body.appendChild(filePick);
filePick.onchange = () => {
  if (filePick._to && filePick.files[0]) takeFile(filePick.files[0], filePick._to);
  filePick.value = "";
};

/* ---------- один набір обробників на весь розділ ---------- */
document.addEventListener("click", e => {
  if (S.view !== "ts" || !TS) return;

  /* меню «⋯» закривається кліком будь-куди поза ним */
  if (menuOpen && !(e.target.closest && e.target.closest(".tsv-more"))){
    menuOpen = false;
    render();
    return;
  }

  const sl = e.target.closest && e.target.closest(".ts-shot[data-p]");
  /* поза режимом правки скрін можна лише роздивитись */
  if (sl && !editing){
    const have = get(sl.dataset.p);
    if (have && typeof openLightbox === "function") openLightbox(sl.querySelector("img") || tsShotSrc(have));
    return;
  }
  if (sl){
    if (e.target.closest(".rm")){
      e.stopPropagation();
      const p = sl.dataset.p;
      const keys = p.split(".");
      const last = keys[keys.length - 1];
      if (/^\d+$/.test(last)){          /* елемент списку — прибираємо зовсім */
        const arr = get(keys.slice(0, -1).join("."));
        if (Array.isArray(arr)) arr.splice(+last, 1);
      } else set(p, "");
      save(); render();
      return;
    }
    /* кнопка «замінити» — файли з комп'ютера, як і був подвійний клік */
    if (e.target.closest(".rp")){
      e.stopPropagation();
      armed = null;
      filePick._to = sl;
      filePick.click();
      return;
    }
    /* у заповненому слоті клік дивиться скрін: щоб роздивитись графік,
       не треба нікуди його перетягувати */
    const have = get(sl.dataset.p);
    if (have && typeof openLightbox === "function"){
      /* передаємо саму картинку: поруч у блоці лежать сусідні скріни,
         і перегляд гортається стрілками, не закриваючись */
      openLightbox(sl.querySelector("img") || tsShotSrc(have));
      return;
    }
    if (touchOnly()){
      ShotTap.tap("ts:" + sl.dataset.p, {
        paste: f => takeFile(f, sl),
        files: () => { filePick._to = sl; filePick.click(); },
        empty: () => flashHint(sl, D().shotTouchEmpty),
      });
      return;
    }
    armed = (armed === sl.dataset.p) ? null : sl.dataset.p;
    paintArmed();
    return;
  }

  const el = e.target.closest && e.target.closest(".ts-ed[data-p]");
  if (el && editing) startEdit(el);
});

/* подвійний клік — вибір файлу з комп'ютера. Заповнений слот пропускаємо:
   там перший клік уже відкрив скрін, і діалог файлів поверх нього — сюрприз */
document.addEventListener("dblclick", e => {
  if (S.view !== "ts" || !TS || !editing) return;
  if (touchOnly()) return;             /* на телефоні два тапи ловить ShotTap */
  const sl = e.target.closest && e.target.closest(".ts-shot[data-p]");
  if (!sl || get(sl.dataset.p)) return;
  e.preventDefault();
  armed = null;
  filePick._to = sl;
  filePick.click();
});

document.addEventListener("mouseover", e => {
  const sl = e.target.closest && e.target.closest(".ts-shot[data-p]");
  if (sl) hotShot = sl;
});

document.addEventListener("keydown", e => {
  /* поки висить питання «точно вийти?», Escape належить йому: цей обробник
     зареєстрований раніше й інакше відкрив би ще одне таке саме питання */
  if (window.Ask && Ask.isOpen()) return;
  if (e.key === "Escape" && askBox){ e.stopPropagation(); askClose(); return; }
  if (e.key === "Escape" && menuOpen && S.view === "ts"){ menuOpen = false; render(); }
}, true);

document.addEventListener("paste", e => {
  if (S.view !== "ts" || !TS || !editing) return;
  if (e.target.closest && e.target.closest("input,textarea")) return;
  const files = (e.clipboardData && e.clipboardData.files) || [];
  if (!files.length) return;
  /* спершу слот, обраний кліком, потім той, над яким миша, і лише тоді
     перший порожній */
  const el = (armed && document.querySelector('.ts-shot[data-p="' + armed + '"]'))
    || (hotShot && document.body.contains(hotShot) ? hotShot : null)
    || document.querySelector(".ts-shot[data-p]:not(.has)");
  if (!el) return;
  e.preventDefault();
  takeFile(files[0], el);
});

document.addEventListener("dragover", e => {
  if (!editing) return;
  const el = e.target.closest && e.target.closest(".ts-shot[data-p]");
  if (!el) return;
  e.preventDefault();
  el.classList.add("drop");
});
document.addEventListener("dragleave", e => {
  const el = e.target.closest && e.target.closest(".ts-shot[data-p]");
  if (el) el.classList.remove("drop");
});
document.addEventListener("drop", e => {
  if (!editing) return;
  const el = e.target.closest && e.target.closest(".ts-shot[data-p]");
  if (!el) return;
  e.preventDefault();
  el.classList.remove("drop");
  takeFile(e.dataTransfer.files[0], el);
});

/* ================= опитування ================= */
let step = 0, answers = {}, askBox = null;

function QS(){
  const q = D().q;
  return [
    {k:"assets", multi:true, opts:["US100","GER40","US500","US30","EURUSD","GBPUSD","XAUUSD","BTCUSD","JP225"], t:q.assets, h:q.assetsH},
    {k:"ctx",   multi:true, opts:["1W","1D","4H"], t:q.ctx, h:q.ctxH},
    {k:"conf",  multi:true, opts:["4H","1H","30M","15M","5M"], t:q.conf, h:q.confH},
    {k:"entry", multi:true, opts:["15M","5M","3M","1M"], t:q.entry, h:q.entryH},
    {k:"hours", multi:true, opts:q.hoursOpts, t:q.hours, h:q.hoursH},
    {k:"days",  multi:true, opts:q.daysOpts, t:q.days, h:q.daysH},
    {k:"model", multi:true, own:true, opts:["cisd","bos","inversion"], t:q.model, h:q.modelH},
    {k:"stop",  own:true, opts:q.stopOpts, t:q.stop, h:""},
    {k:"target",own:true, opts:q.targetOpts, t:q.target, h:""},
    {k:"risk",  multi:true, own:true, opts:["0.25%","0.5%","1%","1.5%","2%"], t:q.risk, h:q.riskH},
    {k:"rr",    own:true, opts:["1.5","2","2.5","3"], t:q.rr, h:""},
    {k:"day",   own:true, opts:["1%","2%","3%","5%",q.noLimit], t:q.day, h:q.dayH},
    {k:"maxtrades", own:true, opts:["1","2","3","5",q.noLimit], t:q.maxtrades, h:""},
    {k:"be",    multi:true, opts:q.beOpts, t:q.be, h:q.beH},
    {k:"partial", opts:q.partialOpts, t:q.partial, h:""},
    {k:"manual", multi:true, opts:q.manualOpts, t:q.manual, h:q.manualH},
    {k:"skip",  text:true, t:q.skip, h:q.skipH, ph:q.skipPh},
    {k:"mind",  text:true, t:q.mind, h:q.mindH, ph:q.mindPh},
  ].map(q => (q.opts && window.Prefs) ? Object.assign(q, {opts: Prefs.vals("ts:" + q.k, q.opts)}) : q);
}

function askOpen(){
  step = 0;
  answers = {};
  const list = QS();
  list.forEach(q => answers[q.k] = q.multi ? [] : "");
  /* якщо ТС уже є — підставляємо те, що знаємо, щоб не набирати наново */
  if (TS){
    answers.assets = (TS.assets || []).slice();
    answers.model = (TS.models || []).map(m => m.name).filter(Boolean);
    /* ризик тепер із кількох варіантів — розбираємо збережений рядок назад */
    answers.risk = ((TS.risk || {}).per || "").split(",").map(s => s.trim()).filter(Boolean);
    answers.rr = (TS.risk || {}).rr || "";
    answers.day = (TS.risk || {}).day || "";
    answers.maxtrades = TS.maxtrades || "";
  }
  askBox = document.createElement("div");
  askBox.className = "ts-ask";
  document.body.appendChild(askBox);
  ScrollLock.on();
  drawAsk();
}
/* Чи є що втрачати: опитування нічого не зберігає до самого кінця, тож
   вийти посеред нього — це стерти всі відповіді. Але коли ще нічого не
   відповіли, перепитувати нема про що. */
function askDirty(){
  return Object.keys(answers || {}).some(k => {
    const v = answers[k];
    return Array.isArray(v) ? v.length > 0 : String(v || "").trim() !== "";
  });
}

async function askClose(force){
  if (!force && askDirty() && !await Ask.yes(D().confirmQuitAsk, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
  const wasOpen = !!askBox;
  if (askBox && askBox.parentNode) askBox.parentNode.removeChild(askBox);
  askBox = null;
  if (wasOpen) ScrollLock.off();
}
function askPrev(){ if (step > 0){ step--; drawAsk(); } else askClose(); }
function askNext(){ step++; drawAsk(); }

function pick(k, v, el){
  const q = QS().find(x => x.k === k);
  if (q.multi){
    const a = answers[k] || (answers[k] = []);
    const i = a.indexOf(v);
    if (i >= 0) a.splice(i, 1); else a.push(v);
    /* Перемикаємо саму кнопку, а не малюємо панель наново: повний
       перемальовок скидав прокрутку і смикав екран на кожному кліку.
       Крім класу «on» у питанні з кількома відповідями нічого не змінюється. */
    if (el) el.classList.toggle("on", i < 0);
    else drawAsk();
  } else {
    answers[k] = v;
    if (el){
      el.closest(".ts-opts").querySelectorAll(".ts-opt.on").forEach(b => b.classList.remove("on"));
      el.classList.add("on");
    } else drawAsk();
  }
}

/* Свій варіант відповіді. Кнопку збираємо через DOM, а не рядком розмітки:
   у назві може бути будь-що, включно з лапками, і склеювання зламало б onclick. */
function own(k, inp){
  const v = (inp.value || "").trim();
  if (!v) return;
  const q = QS().find(x => x.k === k);
  /* одна відповідь: свій варіант обирається одразу і веде далі, як кнопка */
  if (q && !q.multi){ pick(k, v); return; }
  const a = answers[k] || (answers[k] = []);
  if (!a.includes(v)){
    a.push(v);
    const box = inp.closest(".ts-ask-in").querySelector(".ts-opts");
    if (box){
      const b = document.createElement("button");
      b.className = "ts-opt on";
      b.textContent = v;
      b.onclick = () => pick(k, v, b);
      box.appendChild(b);
    }
  }
  inp.value = "";
  inp.focus();
}

function drawAsk(){
  if (!askBox) return;
  const d = D(), list = QS();
  const dots = list.map((q, i) =>
    '<i class="' + (i === step ? "on" : i < step ? "done" : "") + '"></i>').join("");
  const top = '<div class="ts-ask-top"><button onclick="__ts.prev()">← ' + esc(d.back) + "</button>"
    + '<div class="ts-dots">' + dots + "</div>"
    + '<button class="x" onclick="__ts.close()">×</button></div>';

  if (step >= list.length){
    const j = k => { const v = answers[k]; return Array.isArray(v) ? (v.join(" · ") || "—") : (v || "—"); };
    const l = (k, v) => "<div><span class=\"k\">" + esc(k) + "</span><span class=\"v\"><b>"
      + esc(v) + "</b></span></div>";
    askBox.innerHTML = top + '<div class="ts-ask-body"><div class="ts-ask-in">'
      + '<div class="ts-ask-n">' + esc(d.ready) + "</div>"
      + '<h2 class="ts-ask-q">' + esc(d.readyTitle) + "</h2>"
      + '<p class="ts-ask-h">' + esc(d.readyText) + "</p>"
      + '<div class="ts-done-l">'
      +   l(d.lAssets, j("assets")) + l(d.qCtx, j("ctx")) + l(d.qConf, j("conf")) + l(d.qEntry, j("entry"))
      +   l(d.lWindows, j("hours")) + l(d.lModels, j("model")) + l(d.lStop, j("stop"))
      +   l(d.lTarget, j("target")) + l(d.lRiskPer, j("risk")) + l(d.lRrMin, j("rr"))
      +   l(d.lDayLimit, j("day")) + l(d.lMaxTrades, j("maxtrades"))
      +   l(d.lBe, j("be")) + l(d.lPartial, j("partial"))
      + "</div>"
      + '<div class="ts-ask-foot"><button class="ts-next" onclick="__ts.finish()">' + esc(d.saveIt)
      +   '</button><button class="ts-skip" onclick="__ts.again()">' + esc(d.again) + "</button>"
      + "</div></div></div>";
    return;
  }

  const q = list[step];
  let body = "";
  if (q.multi) body += '<div class="ts-multi">' + esc(d.canPickMany) + "</div>";
  if (q.text){
    body += '<textarea class="ts-ask-inp" placeholder="' + esc(q.ph || "")
         + '" oninput="__ts.text(\'' + q.k + "',this.value)\">" + esc(answers[q.k] || "") + "</textarea>";
  } else {
    const sel = v => q.multi ? (answers[q.k] || []).includes(v) : answers[q.k] === v;
    /* дописані самим користувачем варіанти теж показуємо кнопками — інакше
       при поверненні до питання свій варіант зник би з очей */
    const opts = q.multi
      ? q.opts.concat((answers[q.k] || []).filter(v => !q.opts.includes(v)))
      : q.opts.concat(answers[q.k] && !q.opts.includes(answers[q.k]) ? [answers[q.k]] : []);
    /* у кожної кнопки хрестик: прибрати з підказок те, чим не користуєшся */
    const jsv = v => String(v).replace(/'/g, "\\'");
    body += '<div class="ts-opts">' + opts.map(v =>
      '<span class="ts-optw"><button class="ts-opt' + (sel(v) ? " on" : "") + '" onclick="__ts.pick(\'' + q.k + "','"
      + jsv(v) + "',this)\">" + esc(v) + "</button>"
      + '<i class="ts-optx" title="' + esc(d.q.optHide) + '" onclick="__ts.hideOpt(\'' + q.k + "','" + jsv(v) + "')\">"
      + (window.TRASH_ICON || "×") + "</i></span>").join("")
      + (window.Prefs && Prefs.hidden("ts:" + q.k).length
          ? '<button class="ts-optundo" onclick="__ts.restoreOpts(\'' + q.k + '\')">' + esc(d.q.optRestore) + "</button>" : "")
      + "</div>";
    /* Свій варіант є в кожному питанні з кнопками: готові підказки — це
       найчастіше, а не все. Вимкнути можна own:false, якби знадобилось. */
    if (q.own !== false){
      body += '<div class="ts-own"><input class="ts-own-inp" placeholder="' + esc(d.ownPh)
           + '" onkeydown="if(event.key===\'Enter\'){event.preventDefault();__ts.own(\''
           + q.k + '\',this)}">'
           + '<button class="ts-own-add" onclick="__ts.own(\'' + q.k
           + '\',this.previousElementSibling)">+</button></div>';
    }
  }

  askBox.innerHTML = top + '<div class="ts-ask-body"><div class="ts-ask-in">'
    + '<div class="ts-ask-n">' + esc(d.question) + " " + (step + 1) + " " + esc(d.of) + " " + list.length + "</div>"
    + '<h2 class="ts-ask-q">' + esc(q.t) + "</h2>"
    + (q.h ? '<p class="ts-ask-h">' + esc(q.h) + "</p>" : "")
    + body
    + '<div class="ts-ask-foot">'
    +   '<button class="ts-next" onclick="__ts.next()">' + esc(d.next) + "</button>"
    +   '<button class="ts-skip" onclick="__ts.next()">' + esc(d.skipQ) + "</button>"
    + "</div></div></div>";
}

function today(){
  const n = new Date();
  return n.getFullYear() + "-" + String(n.getMonth() + 1).padStart(2, "0")
       + "-" + String(n.getDate()).padStart(2, "0");
}

/* Відповіді -> стратегія. Те, що людина пропустила, лишається порожнім:
   краще видима дірка, ніж вигадане за неї значення. */
function finish(){
  const d = D(), a = answers;
  const keep = TS || {};
  const tfs = [];
  const push = (list, role) => (list || []).forEach(tf => {
    const was = (keep.tfs || []).find(x => x.tf === tf);
    tfs.push({tf: tf, role: role, what: was ? was.what : "", shot: was ? was.shot : ""});
  });
  push(a.ctx, d.roleCtx);
  push(a.conf, d.roleConf);
  push(a.entry, d.roleEntry);

  const manage = [];
  if ((a.be || []).length) manage.push({k: d.lBe, v: a.be.join(", "), shots: []});
  if (a.partial) manage.push({k: d.lPartial, v: a.partial, shots: []});
  if ((a.manual || []).length) manage.push({k: d.lManual, v: a.manual.join(", "), shots: []});

  const check = [];
  if ((a.ctx || []).length) check.push(d.ckCtx.replace("%s", a.ctx.join(", ")));
  if ((a.conf || []).length) check.push(d.ckConf.replace("%s", a.conf.join(", ")));
  if (a.rr) check.push(d.ckRR.replace("%s", a.rr));
  if ((a.hours || []).length) check.push(d.ckWindow);
  if (a.day) check.push(d.ckDay);
  if (a.stop) check.push(d.ckStop.replace("%s", a.stop));
  check.push(d.ckHead);

  TS = {
    source: "hand",
    updated: today(),
    assets: (a.assets || []).slice(),
    tfs: tfs,
    windows: (a.hours || []).map(n => {
      const was = (keep.windows || []).find(w => w.name === n);
      return {name: n, time: was ? was.time : "", note: was ? was.note : ""};
    }),
    days: (a.days || []).length ? d.daysSkip + " " + a.days.join(", ") : "",
    news: "",
    models: (a.model || []).map(n => {
      const was = (keep.models || []).find(m => m.name === n);
      return {name: n, note: was ? was.note : "", shots: (was && was.shots) || []};
    }),
    bias: keep.bias || "",
    stop: {v: a.stop || "", shot: (keep.stop || {}).shot || ""},
    target: {v: a.target || "", shot: (keep.target || {}).shot || ""},
    maxtrades: a.maxtrades || "",
    risk: {per: (a.risk || []).join(", "), rr: a.rr || "", day: a.day || "",
           week: (keep.risk || {}).week || ""},
    riskCases: keep.riskCases || [],
    manage: manage,
    no: {market: (a.skip || "").split("\n").map(s => s.trim()).filter(Boolean),
         time: [], self: []},
    mind: a.mind || "",
    check: check,
    notion: keep.notion || null,
  };
  save();
  askClose(true);          // збережено — питати «точно вийти?» тут нема сенсу
  render();
}

/* ================= підтягнути з Notion ================= */
const SRC_MAX = 8;             /* стільки сторінок читає сервер за раз */

/* Що зараз у полях. Забираємо з самої сторінки, а не з пам'яті: людина
   могла щойно вставити посилання, а перемальовки ще не було. */
function readFields(){
  const els = document.querySelectorAll("input.ts-url");
  // полів на сторінці немає (розділ ще не намальований) — те, що вже
  // набрано, лишаємо як є, інакше воно зникло б на рівному місці
  const list = els.length ? [] : srcUrls.slice();
  els.forEach(el => list.push(el.value));
  srcUrls = list.length ? list : [""];
  const typed = [];
  srcUrls.forEach(v => {
    v = (v || "").trim();
    if (v && typed.indexOf(v) < 0) typed.push(v);
  });
  return typed;
}

/* Сторінки, з яких ТС зібрана зараз. Старі записи знають лише одне
   посилання — тоді беремо його. */
function srcHave(){
  const n = (TS && TS.notion) || {};
  if (n.urls && n.urls.length) return n.urls.slice();
  return n.url ? [n.url] : [];
}

/* Читаємо завжди весь набір сторінок разом: система розкидана по них, і
   зібрати її з половини не вийде. Тому додавання сторінки — це перечитування
   всіх, і правки в полях замінюються прочитаним. */
async function pullWith(urls){
  const list = urls.filter(Boolean).slice(0, SRC_MAX);
  if (!list.length){
    const f = document.querySelector("input.ts-url");
    if (f) f.focus();
    return;
  }
  busy = true; pullErr = ""; render();
  try{
    const r = await api("POST", "/api/ts/notion", {urls: list});
    TS = normalize(r.ts);
    TS.updated = today();
    srcUrls = [""];
    save();
  }catch(e){
    pullErr = D().pullErr;
  }
  busy = false;
  render();
}

async function pull(){
  const typed = readFields();
  const have = srcHave();
  await pullWith(have.concat(typed.filter(u => have.indexOf(u) < 0)));
}

/* ================= назовні ================= */
/* Створення ТС і перенесення з Notion — це запис. Гостю показуємо
   вікно входу одразу, а не після заповненого опитувальника. */
function guestStop(){ return !!(window.Guest && Guest.block(T.gsGateTs)); }

window.__ts = {
  /* інструменти з ТС — їх підказує «Аналіз дня», коли додаєш актив */
  assets(){ return (TS && Array.isArray(TS.assets)) ? TS.assets.filter(Boolean).slice() : []; },
  /* сама стратегія назовні — з неї sharelink.js збирає знімок */
  data(){ return TS || null; },
  /* довантажити ТС, якщо ще не читали — форма угоди бере з неї підказки */
  ensure(){ if (TS === undefined) load(); },
  /* перечитати з сервера: помічник міг щось дописати на прохання трейдера,
     і розділ під вікном має показати це без F5 */
  reload(){ return load(); },
  /* що з ТС іде в підказки форми: інструменти й моделі входу. Таймфрейми
     ні — у ТС їх пишуть як завгодно («1M», «D»), і слоти під скріни двоїлись. */
  hints(){
    const t = TS || {};
    const clean = a => (Array.isArray(a) ? a : []).map(v => String(v || "").trim()).filter(Boolean);
    return {
      assets: clean(t.assets),
      models: clean((t.models || []).map(m => m && m.name)),
    };
  },
  share(){
    if (menuOpen){ menuOpen = false; render(); }
    if (window.Guest && Guest.block(T.gsGateTs)) return;
    if (window.Share) Share.open("ts");
  },
  /* «Редагувати» / «Готово»: перемикає звичайний вигляд і режим правки */
  edit(){
    if (!editing && guestStop()) return;
    editing = !editing;
    menuOpen = false;
    armed = null;
    render();
  },
  tab(id){
    if (TABS.indexOf(id) < 0) return;
    tab = id;
    try{ localStorage.setItem(TAB_KEY, id); }catch(e){}
    render();
  },
  menu(){ menuOpen = !menuOpen; render(); },
  /* «Додати сторінку з Notion»: відкриваємо вкладку з джерелами й ставимо
     курсор у порожнє поле під посилання */
  srcOpen(){
    menuOpen = false;
    tab = "extra";
    try{ localStorage.setItem(TAB_KEY, tab); }catch(e){}
    render();
    const f = [...document.querySelectorAll("input.ts-url")].pop();
    if (f){ f.scrollIntoView({block: "center", behavior: "smooth"}); f.focus({preventScroll: true}); }
  },
  ask(){ menuOpen = false; if(guestStop()){ render(); return; } askOpen(); }, close: askClose, prev: askPrev, next: askNext, pick: pick, own: own, finish: finish,
  again(){ step = 0; drawAsk(); },
  text(k, v){ answers[k] = v; },
  /* прибрати варіант з підказок: і з екрана, і з відповіді, якщо був обраний */
  hideOpt(k, v){
    if (window.Prefs) Prefs.hide("ts:" + k, v);
    const a = answers[k];
    if (Array.isArray(a)){ const i = a.indexOf(v); if (i >= 0) a.splice(i, 1); }
    else if (a === v) answers[k] = "";
    drawAsk();
  },
  restoreOpts(k){ if (window.Prefs) Prefs.restore("ts:" + k); drawAsk(); },
  pull(){ if(guestStop()) return; pull(); },
  /* ще одне поле під посилання */
  srcAdd(){
    readFields();
    if (srcUrls.length + srcHave().length >= SRC_MAX) return;
    srcUrls.push("");
    render();
  },
  /* прибрати поле, яке ще не читали */
  srcDrop(i){
    readFields();
    srcUrls.splice(i, 1);
    if (!srcUrls.length) srcUrls = [""];
    render();
  },
  /* прибрати сторінку, яку вже підтягнули: перечитуємо ТС без неї */
  srcOut(i){
    if (guestStop()) return;
    const left = srcHave().filter((u, k) => k !== i);
    if (!left.length){ pullErr = D().srcLast; render(); return; }
    pullWith(left);
  },
  add(path){
    const arr = get(path);
    if (!Array.isArray(arr)) set(path, []);
    const list = get(path);
    const proto = {
      assets: "", check: "", "no.market": "", "no.time": "", "no.self": "",
      windows: {name: "", time: "", note: ""},
      tfs: {tf: "", role: "", what: "", shot: ""},
      models: {name: "", note: "", shots: []},
      setups: {name: "", note: "", shots: []},
      riskCases: {k: "", v: ""},
      manage: {k: "", v: "", shots: []},
      extra: {k: "", v: "", shots: []},
    }[path];
    list.push(typeof proto === "object" && proto !== null ? Object.assign({}, proto) : "");
    save(); render();
  },
  del(path, i){
    const arr = get(path);
    if (Array.isArray(arr)) arr.splice(i, 1);
    save(); render();
  },
  async wipe(){
    menuOpen = false;
    render();
    if (!await Ask.yes(D().confirmDelete, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
    if (demo()){ try{ localStorage.removeItem(DEMO_KEY); }catch(e){} }
    else { try{ await api("POST", "/api/ts/clear", {kind: btOn()?"bt":""}); }catch(e){} }
    TS = null;
    editing = false;
    render();
  },
};

/* ---------- підпис у бічній панелі ---------- */
function paintNav(){
  const a = document.querySelector('.nav a[data-v="ts"]');
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
   Словник розділу. Лежить тут, а не в i18n.js: розділ ще
   ворушиться, і так його правки не чіпають спільний файл.
   ============================================================ */
const DICT = {
uk: {
  title: "Моя ТС", navTip: "Твої правила входу — і звірка з тим, що в журналі",
  editTip: "<b>Режим правки.</b> Клікни будь-яке підкреслене поле, щоб змінити його. Скрін — клік по слоту й Ctrl+V "
         + "або перетягни картинку. Порожні поля й кнопки «+ додати» видно тільки зараз.",
  loading: "Хвилинку…", empty: "заповнити", emptyNote: "додати пояснення",
  emptyRole: "підпис до списку", emptyWhat: "що дивлюсь на цьому таймфреймі", emptyRule: "правило",
  emptyTime: "час", emptyTf: "таймфрейм", emptyName: "назва",
  emptyMind: "що нагадати собі перед торгівлею",
  remove: "прибрати", back: "назад",

  noneTitle: "Ще немає торгової стратегії",
  noneLead: "Журнал уміє звіряти кожну угоду з твоїми ж правилами — але спершу має їх знати. "
          + "<b>Двома способами:</b> зібрати тут, відповідаючи на питання, або підтягнути готову з Notion.",
  wayNewTitle: "Створити торгову стратегію з нуля",
  wayNewText: "18 окремих питань, швидка відповідь: якими парами торгуєш, у які вікна, де входиш, скільки ризикуєш, "
            + "коли переводиш у беззбиток. Відповідаєш кнопками, писати майже нічого не треба.",
  wayNewBtn: "Створити торгову стратегію з нуля", wayNewMins: "≈ 5 хвилин · можна кинути посередині",
  wayNotionTitle: "Підтягнути з Notion",
  wayNotionText: "Якщо торгова стратегія уже описана в Notion — просто дай посилання. Розділів кілька "
               + "(контекст окремо, входи окремо) — додай стільки посилань, скільки треба.",
  wayNotionBtn: "Підтягнути", wayNotionPh: "notion.so/Moya-TS-1a2b3c…",
  wayNotionHint: "Сторінка має бути відкрита за посиланням: в Notion <b>Share → Publish</b>. Ми тільки читаємо.",
  srcAdd: "ще сторінка", srcDrop: "прибрати",
  srcHave: "Сторінки, з яких зібрана торгова стратегія",
  srcFailed: "Не прочиталась сторінка:",
  srcLast: "Це остання сторінка — прибрати її не вийде.",
  srcAgainWarn: "Додаси сторінку — перечитаємо всі разом, і те, що ти правив руками, заміниться прочитаним.",
  pulling: "читаю сторінку…", pullErr: "Не вдалось прочитати сторінку. Перевір, що вона опублікована за посиланням.",
  whyTitle: "Що зміниться, коли буде торгова стратегія",
  why1: "<b>Чек-лист перед входом</b> — поки твої умови не виконані, вхід рахується поспішним.",
  why2: "<b>Звірка по журналу</b> — скільки разів RR був нижчий за твій мінімум, де перевищений денний ліміт, чи дотримуєшся встановленого ризику.",
  why3: "<b>Правила поруч</b> — усі правила в одному місці, а не в думках.",
  whyAfter: "Можна почати з нуля, а потім підтягнути з Notion — друге допише те, чого не вистачає.",

  secMarket: "Ринок і час", secTf: "Таймфрейми", secEntry: "Вхід", secRisk: "Ризик",
  secManage: "Супровід угоди", secExtra: "Додатково",
  addExtra: "ще блок", noExtra: "Тут можна дописати те, що не влізло в поля вище",
  emptyExtraK: "про що це", emptyExtraV: "своє правило або нотатка", secNo: "Коли не входжу", secCheck: "Чек-лист перед входом",
  secReal: "Що виходить насправді", secRaw: "Сторінки з Notion, як ми їх прочитали",
  rawText: "Текст сторінок", rawShots: "Скріни зі сторінок",

  lAssets: "Чим торгую", lWindows: "Вікна", lDaysNews: "Дні та новини",
  lTradeDays: "Торгові дні", lRedNews: "Червоні новини",
  lModels: "Моделі входу", lSetups: "Сетапи", lRules: "Правила входу", lBias: "Біас визначаю",
  lStop: "Де стоп", lTarget: "Де ціль", lMaxTrades: "Угод за день",
  lRrMin: "Мінімальний RR", lRiskPer: "Ризик на угоду", lDayLimit: "Ліміт за день",
  lWeekLimit: "Ліміт за тиждень", lRiskCases: "Окремі випадки",
  lBe: "Беззбиток", lPartial: "Часткова фіксація", lManual: "Закриваю руками",
  lNoMarket: "За ринком", lNoTime: "За часом", lNoSelf: "За собою", lMind: "Нагадування",

  addAsset: "інструмент", addWindow: "вікно", addTf: "таймфрейм", addModel: "модель",
  addSetup: "сетап",
  addCase: "випадок", addRule: "правило", addLine: "рядок", addCheck: "пункт",
  noTfs: "Таймфреймів ще немає", noCheck: "Чек-листа ще немає",
  noModels: "Моделей входу ще немає", noSetups: "Сетапів ще немає", noneYet: "поки порожньо",
  shotAdd: "вставити скрін", shotAddShort: "ще скрін",
  shotHint: "клік → Ctrl+V · подвійний → файл", shotArmed: "тепер Ctrl+V",
  shotHintTouch: "тап → вставити з буфера · два тапи → файл",
  shotTouchEmpty: "У буфері нема картинки. Два тапи — обрати файл.",
  shotReplace: "замінити скрін", shotOpen: "відкрити", shotExample: "приклад", shotHow: "як це виглядає",

  btnEdit: "Редагувати", btnDone: "Готово", btnMore: "Ще дії",
  tabBefore: "Перед входом", tabEntry: "Як входжу", tabRisk: "Ризик і супровід",
  tabReal: "Звірка з журналом", tabExtra: "Notion і нотатки",
  secSources: "Сторінки з Notion", btnNotion: "Додати сторінку з Notion",
  srcNone: "Систему розбито на кілька сторінок? Вставляй посилання по одному — «+ ще сторінка» додає поле під наступне.",
  pRisk: "Ризик", pRr: "Мін. RR", pMax: "Угод / день",
  lLimits: "Ліміт збитку", wDay: "день", wWeek: "тиждень", secWhen: "Коли торгую",
  noManage: "Правил супроводу ще немає", noCases: "Окремих випадків ще немає",
  realScore: "правил без порушень",
  btnAsk: "Пройти опитування", btnShare: "Поділитись", btnDelete: "Видалити ТС",
  confirmDelete: "Видалити стратегію? Скріни до неї теж зникнуть.",
  confirmQuitAsk: "Вийти з опитування? Відповіді не збережуться.",

  realFew: "Замало угод для звірки — потрібно хоча б п'ять",
  realNeed: "Щоб звіряти, заповни хоча б мінімальний RR, ризик або ліміт за день",
  realRR: "RR нижче мінімального", realRRNote: "у ТС — не менше %s",
  realDay: "Денний ліміт перевищено", realDayNote: "у ТС — не більше %s",
  realMax: "Більше угод за день, ніж у ТС", realMaxNote: "у ТС — не більше %s",
  realRisk: "Ризик на угоду", realRiskNote: "у ТС — %s",
  realModel: "Входи за своїми моделями", realModelNote: "у ТС — %s",
  realWorst: "найгірший", realMost: "найбільше", realHold: "тримаєш",
  realOff: "розходиться з ТС", realOther: "решта:",
  wTrades: "угод", wDays: "днів", wOfAll: "усіх",

  question: "питання", of: "з", next: "Далі", skipQ: "пропустити",
  canPickMany: "можна кілька", ready: "готово", readyTitle: "Це твоя ТС",
  readyText: "Тепер журнал звірятиме з нею кожну угоду.", saveIt: "Зберегти", again: "Пройти ще раз",
  roleCtx: "Контекст", roleConf: "Підтвердження", roleEntry: "Вхід",
  daysSkip: "пропускаю:",
  ckCtx: "Контекст %s за мене", ckConf: "Є підтвердження на %s", ckRR: "RR до цілі не менше %s",
  ckWindow: "Ми у своєму вікні", ckDay: "Денний ліміт не вибраний",
  ckStop: "Стоп стоїть %s", ckHead: "Голова холодна",
  qCtx: "Контекст", qConf: "Підтвердження", qEntry: "Вхід",
  q: {
    assets: "Якими парами торгуєш?", assetsH: "",
    ctx: "На чому дивишся контекст?", ctxH: "Старші таймфрейми: куди ринок іде взагалі.",
    conf: "Де шукаєш підтвердження?", confH: "Той таймфрейм, на якому вирішуєш, що рух почався.",
    entry: "Де входиш?", entryH: "Таймфрейм самої точки входу.",
    hours: "У які вікна торгуєш?", hoursH: "",
    hoursOpts: ["Frankfurt","London open","NYSE open","New York","Power Hour","Азія","Весь день"],
    days: "Які дні пропускаєш?", daysH: "Якщо торгуєш усі — просто далі.",
    daysOpts: ["Понеділок","П'ятниця","Дні з червоними новинами","Останній день місяця"],
    model: "Твої моделі входу", modelH: "",
    stop: "Де ставиш стоп?", stopOpts: ["за структуру","за тінь свічки","за межу зони","фіксований у пунктах"],
    ownPh: "свій варіант", optHide: "прибрати з підказок", optRestore: "повернути приховані",
    target: "Де ціль?", targetOpts: ["найближчий імбаланс","PDH / PDL","PWH / PWL","денний фрактал","фіксований RR","попередній екстремум"],
    risk: "Скільки ризикуєш в одній угоді?", riskH: "Від депозиту. З цієї цифри рахується все інше.",
    rr: "Нижче якого RR не входиш?",
    day: "Після якої втрати зупиняєшся на день?", dayH: "Журнал попередить, коли ліміт майже вибрано.",
    maxtrades: "Скільки угод за день максимум?",
    be: "Коли переводиш у беззбиток?", beH: "Можна кілька — у різних ситуаціях по-різному.",
    beOpts: ["на першій 15m FTA","після 1h фракталу","на межі сесії","на половині шляху до цілі",
             "після зняття ліквідності","перед червоними новинами","коли RR дійшов до 1","не переводжу"],
    partial: "Фіксуєш частинами?",
    partialOpts: ["ні, закриваю все одразу","половину на RR 1","третину на кожній цілі","за ситуацією"],
    manual: "Коли закриваєш руками?", manualH: "",
    manualOpts: ["структура зламалась проти","червона новина","кінець сесії","не йде за планом","не закриваю руками"],
    skip: "Коли пропускаєш вхід?", skipH: "Своїми словами, з нового рядка кожне правило.",
    skipPh: "Наприклад: якщо до 21:30 входу немає — скіп",
    mind: "Що нагадати собі перед торгівлею?", mindH: "Побачиш це щоразу, коли відкриєш ТС.",
    mindPh: "Наприклад: головне — зберегти капітал, а не взяти багато угод",
    noLimit: "без ліміту",
  },
},

ru: {
  title: "Моя ТС", navTip: "Твои правила входа — и сверка с тем, что в журнале",
  editTip: "<b>Режим правки.</b> Кликни любое подчёркнутое поле, чтобы изменить его. Скрин — клик по слоту и Ctrl+V "
         + "или перетащи картинку. Пустые поля и кнопки «+ добавить» видны только сейчас.",
  loading: "Минутку…", empty: "заполнить", emptyNote: "добавить пояснение",
  emptyRole: "подпись к списку", emptyWhat: "что смотрю на этом таймфрейме", emptyRule: "правило",
  emptyTime: "время", emptyTf: "таймфрейм", emptyName: "название",
  emptyMind: "что напомнить себе перед торговлей",
  remove: "убрать", back: "назад",

  noneTitle: "Ещё нет торговой стратегии",
  noneLead: "Журнал умеет сверять каждую сделку с твоими же правилами — но сначала должен их знать. "
          + "<b>Двумя способами:</b> собрать здесь, отвечая на вопросы, или подтянуть готовую из Notion.",
  wayNewTitle: "Создать торговую стратегию с нуля",
  wayNewText: "18 отдельных вопросов, быстрый ответ: какие пары торгуешь, в какие окна, где входишь, сколько рискуешь, "
            + "когда переводишь в безубыток. Отвечаешь кнопками, писать почти ничего не нужно.",
  wayNewBtn: "Создать торговую стратегию с нуля", wayNewMins: "≈ 5 минут · можно бросить посередине",
  wayNotionTitle: "Подтянуть из Notion",
  wayNotionText: "Если торговая стратегия уже описана в Notion — просто дай ссылку. Разделов несколько "
               + "(контекст отдельно, входы отдельно) — добавь столько ссылок, сколько нужно.",
  wayNotionBtn: "Подтянуть", wayNotionPh: "notion.so/Moya-TS-1a2b3c…",
  wayNotionHint: "Страница должна быть открыта по ссылке: в Notion <b>Share → Publish</b>. Мы только читаем.",
  srcAdd: "ещё страница", srcDrop: "убрать",
  srcHave: "Страницы, из которых собрана торговая стратегия",
  srcFailed: "Не прочиталась страница:",
  srcLast: "Это последняя страница — убрать её не выйдет.",
  srcAgainWarn: "Добавишь страницу — перечитаем все вместе, и то, что правил руками, заменится прочитанным.",
  pulling: "читаю страницу…", pullErr: "Не удалось прочитать страницу. Проверь, что она опубликована по ссылке.",
  whyTitle: "Что изменится, когда будет торговая стратегия",
  why1: "<b>Чек-лист перед входом</b> — пока твои условия не выполнены, вход считается поспешным.",
  why2: "<b>Сверка по журналу</b> — сколько раз RR был ниже твоего минимума, где превышен дневной лимит, придерживаешься ли установленного риска.",
  why3: "<b>Правила рядом</b> — все правила в одном месте, а не в мыслях.",
  whyAfter: "Можно начать с нуля, а потом подтянуть из Notion — второе допишет то, чего не хватает.",

  secMarket: "Рынок и время", secTf: "Таймфреймы", secEntry: "Вход", secRisk: "Риск",
  secManage: "Сопровождение сделки", secExtra: "Дополнительно",
  addExtra: "ещё блок", noExtra: "Тут можно дописать то, что не влезло в поля выше",
  emptyExtraK: "о чём это", emptyExtraV: "своё правило или заметка", secNo: "Когда не вхожу", secCheck: "Чек-лист перед входом",
  secReal: "Что выходит на самом деле", secRaw: "Страницы из Notion, как мы их прочитали",
  rawText: "Текст страниц", rawShots: "Скрины со страниц",

  lAssets: "Чем торгую", lWindows: "Окна", lDaysNews: "Дни и новости",
  lTradeDays: "Торговые дни", lRedNews: "Красные новости",
  lModels: "Модели входа", lSetups: "Сетапы", lRules: "Правила входа", lBias: "Биас определяю",
  lStop: "Где стоп", lTarget: "Где цель", lMaxTrades: "Сделок за день",
  lRrMin: "Минимальный RR", lRiskPer: "Риск на сделку", lDayLimit: "Лимит за день",
  lWeekLimit: "Лимит за неделю", lRiskCases: "Отдельные случаи",
  lBe: "Безубыток", lPartial: "Частичная фиксация", lManual: "Закрываю руками",
  lNoMarket: "По рынку", lNoTime: "По времени", lNoSelf: "По себе", lMind: "Напоминание",

  addAsset: "инструмент", addWindow: "окно", addTf: "таймфрейм", addModel: "модель",
  addSetup: "сетап",
  addCase: "случай", addRule: "правило", addLine: "строку", addCheck: "пункт",
  noTfs: "Таймфреймов ещё нет", noCheck: "Чек-листа ещё нет",
  noModels: "Моделей входа ещё нет", noSetups: "Сетапов ещё нет", noneYet: "пока пусто",
  shotAdd: "вставить скрин", shotAddShort: "ещё скрин",
  shotHint: "клик → Ctrl+V · двойной → файл", shotArmed: "теперь Ctrl+V",
  shotHintTouch: "тап → вставить из буфера · два тапа → файл",
  shotTouchEmpty: "В буфере нет картинки. Два тапа — выбрать файл.",
  shotReplace: "заменить скрин", shotOpen: "открыть", shotExample: "пример", shotHow: "как это выглядит",

  btnEdit: "Редактировать", btnDone: "Готово", btnMore: "Ещё",
  tabBefore: "Перед входом", tabEntry: "Как вхожу", tabRisk: "Риск и сопровождение",
  tabReal: "Сверка с журналом", tabExtra: "Notion и заметки",
  secSources: "Страницы из Notion", btnNotion: "Добавить страницу из Notion",
  srcNone: "Система разбита на несколько страниц? Вставляй ссылки по одной — «+ ещё страница» добавляет поле под следующую.",
  pRisk: "Риск", pRr: "Мин. RR", pMax: "Сделок / день",
  lLimits: "Лимит убытка", wDay: "день", wWeek: "неделя", secWhen: "Когда торгую",
  noManage: "Правил сопровождения пока нет", noCases: "Отдельных случаев пока нет",
  realScore: "правил без нарушений",
  btnAsk: "Пройти опрос", btnShare: "Поделиться", btnDelete: "Удалить ТС",
  confirmDelete: "Удалить стратегию? Скрины к ней тоже пропадут.",
  confirmQuitAsk: "Выйти из опроса? Ответы не сохранятся.",

  realFew: "Мало сделок для сверки — нужно хотя бы пять",
  realNeed: "Чтобы сверять, заполни хотя бы минимальный RR, риск или лимит за день",
  realRR: "RR ниже минимального", realRRNote: "в ТС — не меньше %s",
  realDay: "Дневной лимит превышен", realDayNote: "в ТС — не больше %s",
  realMax: "Больше сделок за день, чем в ТС", realMaxNote: "в ТС — не больше %s",
  realRisk: "Риск на сделку", realRiskNote: "в ТС — %s",
  realModel: "Входы по своим моделям", realModelNote: "в ТС — %s",
  realWorst: "худший", realMost: "больше всего", realHold: "держишь",
  realOff: "расходится с ТС", realOther: "остальное:",
  wTrades: "сделок", wDays: "дней", wOfAll: "всех",

  question: "вопрос", of: "из", next: "Дальше", skipQ: "пропустить",
  canPickMany: "можно несколько", ready: "готово", readyTitle: "Это твоя ТС",
  readyText: "Теперь журнал будет сверять с ней каждую сделку.", saveIt: "Сохранить", again: "Пройти ещё раз",
  roleCtx: "Контекст", roleConf: "Подтверждение", roleEntry: "Вход",
  daysSkip: "пропускаю:",
  ckCtx: "Контекст %s за меня", ckConf: "Есть подтверждение на %s", ckRR: "RR до цели не меньше %s",
  ckWindow: "Мы в своём окне", ckDay: "Дневной лимит не выбран",
  ckStop: "Стоп стоит %s", ckHead: "Голова холодная",
  qCtx: "Контекст", qConf: "Подтверждение", qEntry: "Вход",
  q: {
    assets: "Какие пары торгуешь?", assetsH: "",
    ctx: "На чём смотришь контекст?", ctxH: "Старшие таймфреймы: куда рынок идёт вообще.",
    conf: "Где ищешь подтверждение?", confH: "Тот таймфрейм, на котором решаешь, что движение началось.",
    entry: "Где входишь?", entryH: "Таймфрейм самой точки входа.",
    hours: "В какие окна торгуешь?", hoursH: "",
    hoursOpts: ["Frankfurt","London open","NYSE open","New York","Power Hour","Азия","Весь день"],
    days: "Какие дни пропускаешь?", daysH: "Если торгуешь все — просто дальше.",
    daysOpts: ["Понедельник","Пятница","Дни с красными новостями","Последний день месяца"],
    model: "Твои модели входа", modelH: "",
    stop: "Где ставишь стоп?", stopOpts: ["за структуру","за тень свечи","за границу зоны","фиксированный в пунктах"],
    ownPh: "свой вариант", optHide: "убрать из подсказок", optRestore: "вернуть скрытые",
    target: "Где цель?", targetOpts: ["ближайший имбаланс","PDH / PDL","PWH / PWL","дневной фрактал","фиксированный RR","предыдущий экстремум"],
    risk: "Сколько рискуешь в одной сделке?", riskH: "От депозита. С этой цифры считается всё остальное.",
    rr: "Ниже какого RR не входишь?",
    day: "После какой потери останавливаешься на день?", dayH: "Журнал предупредит, когда лимит почти выбран.",
    maxtrades: "Сколько сделок за день максимум?",
    be: "Когда переводишь в безубыток?", beH: "Можно несколько — в разных ситуациях по-разному.",
    beOpts: ["на первой 15m FTA","после 1h фрактала","на границе сессии","на половине пути к цели",
             "после снятия ликвидности","перед красными новостями","когда RR дошёл до 1","не перевожу"],
    partial: "Фиксируешь частями?",
    partialOpts: ["нет, закрываю всё сразу","половину на RR 1","треть на каждой цели","по ситуации"],
    manual: "Когда закрываешь руками?", manualH: "",
    manualOpts: ["структура сломалась против","красная новость","конец сессии","идёт не по плану","не закрываю руками"],
    skip: "Когда пропускаешь вход?", skipH: "Своими словами, с новой строки каждое правило.",
    skipPh: "Например: если до 21:30 входа нет — скип",
    mind: "Что напомнить себе перед торговлей?", mindH: "Увидишь это каждый раз, когда откроешь ТС.",
    mindPh: "Например: главное — сохранить капитал, а не взять много сделок",
    noLimit: "без лимита",
  },
},

en: {
  title: "My system", navTip: "Your entry rules — checked against the journal",
  editTip: "<b>Edit mode.</b> Click any underlined field to change it. Screenshot — click the slot and press Ctrl+V "
         + "or drop an image on it. Empty fields and «+ add» buttons only show up now.",
  loading: "One moment…", empty: "fill in", emptyNote: "add a note",
  emptyTime: "time", emptyTf: "timeframe", emptyName: "name",
  emptyRole: "list caption", emptyWhat: "what I look at on this timeframe", emptyRule: "rule",
  emptyMind: "what to remind yourself before trading",
  remove: "remove", back: "back",

  noneTitle: "No trading system yet",
  noneLead: "The journal can check every trade against your own rules — but it has to know them first. "
          + "<b>Two ways:</b> build it here by answering questions, or pull a ready one from Notion.",
  wayNewTitle: "Build it from scratch",
  wayNewText: "18 separate questions, quick answers: which pairs you trade, in which windows, where you enter, how much you risk, "
            + "when you move to break-even. Mostly buttons, almost no typing.",
  wayNewBtn: "Build it from scratch", wayNewMins: "≈ 5 minutes · you can stop halfway",
  wayNotionTitle: "Pull from Notion",
  wayNotionText: "If your system already lives in Notion — just give the link. Keep it in "
               + "several pages (context, entries)? Add as many links as you need.",
  wayNotionBtn: "Pull", wayNotionPh: "notion.so/My-System-1a2b3c…",
  wayNotionHint: "The page has to be open by link: in Notion <b>Share → Publish</b>. We only read it.",
  srcAdd: "one more page", srcDrop: "remove",
  srcHave: "Pages your system is built from",
  srcFailed: "Couldn't read the page:",
  srcLast: "That's the last page — it can't be removed.",
  srcAgainWarn: "Add a page and we re-read them all together, so your manual edits get replaced.",
  pulling: "reading the page…", pullErr: "Couldn't read the page. Check that it is published to web.",
  whyTitle: "What changes once it's there",
  why1: "<b>Pre-entry checklist</b> — your own conditions; until they're ticked, the entry counts as rushed.",
  why2: "<b>Checked against the journal</b> — how often RR was below your minimum, where the daily limit broke, whether you hold your risk.",
  why3: "<b>Rules at hand</b> — in one place instead of three files and your head.",
  whyAfter: "You can start from scratch and pull from Notion later — the second fills in what's missing.",

  secMarket: "Market and time", secTf: "Timeframes", secEntry: "Entry", secRisk: "Risk",
  secManage: "Managing the trade", secExtra: "Anything else",
  addExtra: "one more block", noExtra: "Room for whatever did not fit the fields above",
  emptyExtraK: "what it is about", emptyExtraV: "your own rule or a note", secNo: "When I stay out", secCheck: "Checklist before entry",
  secReal: "What actually happens", secRaw: "The Notion pages as we read them",
  rawText: "Text of the pages", rawShots: "Screenshots from the pages",

  lAssets: "What I trade", lWindows: "Windows", lDaysNews: "Days and news",
  lTradeDays: "Trading days", lRedNews: "Red news",
  lModels: "Entry models", lSetups: "Setups", lRules: "Entry rules", lBias: "Bias from",
  lStop: "Stop goes", lTarget: "Target", lMaxTrades: "Trades per day",
  lRrMin: "Minimum RR", lRiskPer: "Risk per trade", lDayLimit: "Daily limit",
  lWeekLimit: "Weekly limit", lRiskCases: "Special cases",
  lBe: "Break-even", lPartial: "Partial close", lManual: "Closing by hand",
  lNoMarket: "Market", lNoTime: "Time", lNoSelf: "Myself", lMind: "Reminder",

  addAsset: "instrument", addWindow: "window", addTf: "timeframe", addModel: "model",
  addSetup: "setup",
  addCase: "case", addRule: "rule", addLine: "line", addCheck: "item",
  noTfs: "No timeframes yet", noCheck: "No checklist yet",
  noModels: "No entry models yet", noSetups: "No setups yet", noneYet: "empty so far",
  shotAdd: "add a screenshot", shotAddShort: "one more",
  shotHint: "click → Ctrl+V · double → file", shotArmed: "now press Ctrl+V",
  shotHintTouch: "tap → paste from clipboard · double tap → file",
  shotTouchEmpty: "No image in the clipboard. Double tap to pick a file.",
  shotReplace: "replace screenshot", shotOpen: "open", shotExample: "example", shotHow: "what it looks like",

  btnEdit: "Edit", btnDone: "Done", btnMore: "More",
  tabBefore: "Before entry", tabEntry: "How I enter", tabRisk: "Risk & management",
  tabReal: "Journal check", tabExtra: "Notion & notes",
  secSources: "Notion pages", btnNotion: "Add a Notion page",
  srcNone: "System split across several pages? Paste the links one by one — «+ one more page» adds a field for the next one.",
  pRisk: "Risk", pRr: "Min RR", pMax: "Trades / day",
  lLimits: "Loss limit", wDay: "day", wWeek: "week", secWhen: "When I trade",
  noManage: "No management rules yet", noCases: "No special cases yet",
  realScore: "rules kept",
  btnAsk: "Run the questions", btnShare: "Share", btnDelete: "Delete system",
  confirmDelete: "Delete the system? Its screenshots go too.",
  confirmQuitAsk: "Leave the questionnaire? Your answers will be lost.",

  realFew: "Too few trades to compare — five at least",
  realNeed: "To compare, fill in at least the minimum RR, the risk or the daily limit",
  realRR: "RR below the minimum", realRRNote: "your rule — at least %s",
  realDay: "Daily limit broken", realDayNote: "your rule — no more than %s",
  realMax: "More trades a day than your rule", realMaxNote: "your rule — no more than %s",
  realRisk: "Risk per trade", realRiskNote: "your rule — %s",
  realModel: "Entries by your own models", realModelNote: "your rule — %s",
  realWorst: "worst", realMost: "most", realHold: "holding",
  realOff: "drifts from the rule", realOther: "the rest:",
  wTrades: "trades", wDays: "days", wOfAll: "of all",

  question: "question", of: "of", next: "Next", skipQ: "skip",
  canPickMany: "pick as many as you like", ready: "done", readyTitle: "This is your system",
  readyText: "The journal will now check every trade against it.", saveIt: "Save", again: "Run it again",
  roleCtx: "Context", roleConf: "Confirmation", roleEntry: "Entry",
  daysSkip: "skipping:",
  ckCtx: "Context %s is with me", ckConf: "Confirmation on %s", ckRR: "RR to target at least %s",
  ckWindow: "We are inside my window", ckDay: "Daily limit not used up",
  ckStop: "Stop is %s", ckHead: "Head is cool",
  qCtx: "Context", qConf: "Confirmation", qEntry: "Entry",
  q: {
    assets: "Which pairs do you trade?", assetsH: "",
    ctx: "Where do you read context?", ctxH: "Higher timeframes: where the market is going overall.",
    conf: "Where do you look for confirmation?", confH: "The timeframe where you decide the move has started.",
    entry: "Where do you enter?", entryH: "The timeframe of the entry itself.",
    hours: "Which windows do you trade?", hoursH: "",
    hoursOpts: ["Frankfurt","London open","NYSE open","New York","Power Hour","Asia","All day"],
    days: "Which days do you skip?", daysH: "If you trade them all — just move on.",
    daysOpts: ["Monday","Friday","Days with red news","Last day of the month"],
    model: "Your entry models", modelH: "",
    stop: "Where do you put the stop?", stopOpts: ["behind structure","behind the wick","behind the zone edge","fixed in points"],
    ownPh: "your own option", optHide: "remove from suggestions", optRestore: "restore hidden",
    target: "Where is the target?", targetOpts: ["nearest imbalance","PDH / PDL","PWH / PWL","daily fractal","fixed RR","previous extreme"],
    risk: "How much do you risk per trade?", riskH: "Of the account. Everything else is counted from this.",
    rr: "Below which RR do you stay out?",
    day: "After what loss do you stop for the day?", dayH: "The journal warns you when the limit is nearly used up.",
    maxtrades: "How many trades a day at most?",
    be: "When do you move to break-even?", beH: "Pick as many as you like — it differs by situation.",
    beOpts: ["at the first 15m FTA","after the 1h fractal","at the session edge","halfway to target",
             "after liquidity is taken","before red news","when RR reaches 1","I don't move it"],
    partial: "Do you close in parts?",
    partialOpts: ["no, all at once","half at RR 1","a third at each target","depends"],
    manual: "When do you close by hand?", manualH: "",
    manualOpts: ["structure broke against me","red news","end of session","not going to plan","I don't close by hand"],
    skip: "When do you skip an entry?", skipH: "In your own words, one rule per line.",
    skipPh: "For example: no entry by 21:30 — skip",
    mind: "What should we remind you before trading?", mindH: "You'll see it every time you open the system.",
    mindPh: "For example: the point is to keep the capital, not to take many trades",
    noLimit: "no limit",
  },
},
};

paintNav();

})();
