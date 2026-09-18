/* ============================================================
   Журнали бектесту (btj.js).

   Бектест ганяють по кілька штук: US100 за березень, золото за рік, та
   сама ТС на іншому активі. Статистика одного прогону не має змішуватись
   з іншим, тож у режимі бектесту завжди відкритий один журнал, і
   «Огляд», «Журнал» та «Аналітика» рахують тільки його угоди.

   Звʼязок з угодами — по імені: поле `bt_run` в угоді (колись «Прогін»).
   Прогони, записані до журналів, стають журналами самі при першому
   читанні. Угоди без підпису збираються в «Без журналу» — його можна
   назвати, і тоді він стане звичайним журналом.

   Оформлення розділу — те саме, що в «Рахунків» (accounts.css): картки,
   поля, сітка. Своє тут тільки в btj.css.
   ============================================================ */
(function(){

let JS;              /* журнали з сервера; undefined — ще не читали */
let cur = null;      /* ключ відкритого журналу; "" — «Без журналу» */
let blankN = 0;      /* скільки угод бектесту без підпису */
const LS = "tj_btj";

function D(){ return DICT[window.LANG] || DICT.uk; }
function norm(s){ return String(s == null ? "" : s).replace(/[\s\u00a0\u202f\u2007]+/g, " ").trim(); }
function key(s){ return norm(s).toLowerCase(); }
function all(){ return Array.isArray(S.btAll) ? S.btAll : []; }
function tradesOf(k){ return all().filter(t => key(t.bt_run) === k); }
function human(iso){
  const p = String(iso || "").split("-");
  return p.length === 3 ? p[2] + "." + p[1] + "." + p[0] : "";
}

/* Усе, що можна відкрити: журнали плюс «Без журналу», якщо такі угоди є. */
function list(){
  const out = (JS || []).map(j => Object.assign({k: key(j.name)}, j));
  if (blankN) out.push({id: 0, k: "", name: "", blank: true});
  return out;
}
function find(k){ return list().find(j => j.k === k) || null; }

/* Свіжий — той, де остання угода найпізніша: саме його людина, найпевніше,
   і ганяє зараз. Журнал без угод — за номером, новіший вище. */
function freshest(){
  const last = new Map();
  for (const t of all()){
    const k = key(t.bt_run), d = t.date || "";
    if (!last.has(k) || d > last.get(k)) last.set(k, d);
  }
  const l = list();
  l.sort((a, b) => ((last.get(b.k) || "") > (last.get(a.k) || "") ? 1 : -1) || (b.id - a.id));
  return l[0] || null;
}

async function load(){
  try{ JS = (await api("GET", "/api/bt/journals")).journals || []; }
  catch(e){ if (JS === undefined) JS = []; }
}

/* Викликається з reload() у режимі бектесту, коли угоди вже приїхали. */
async function sync(){
  await load();
  /* Прогони без картки журналу — з часів поля «Прогін» або вписані руками
     прямо у формі угоди. Заводимо їм картку самі: людина не мусить знати,
     що журнал — це окремий запис. */
  const have = new Set((JS || []).map(j => key(j.name)));
  const orphans = new Map();
  blankN = 0;
  for (const t of all()){
    const nm = norm(t.bt_run), k = nm.toLowerCase();
    if (!k){ blankN++; continue; }
    if (!have.has(k) && !orphans.has(k)) orphans.set(k, nm);
  }
  if (orphans.size){
    for (const nm of orphans.values()){
      try{ await api("POST", "/api/bt/journals", {journal: {name: nm}, adopt: nm}); }catch(e){}
    }
    await load();
  }
  let want = null;
  try{ want = localStorage.getItem(LS); }catch(e){}
  if (want !== null && find(want)) cur = want;
  else { const f = freshest(); cur = f ? f.k : null; }
  paint();
}

function select(name){
  cur = key(name);
  try{ localStorage.setItem(LS, cur); }catch(e){}
  paint();
}

/* Угоди відкритого журналу. Журналів ще немає зовсім — усе, що є (тобто
   нічого: без журналів угод бектесту не буває). */
function filter(list){
  if (cur === null) return list;
  return list.filter(t => key(t.bt_run) === cur);
}

function curJ(){ return cur === null ? null : find(cur); }
function label(j){ return j.blank ? D().blank : j.name; }

/* Назва відкритого журналу — на смужці «Режим бектесту», підпис пункту
   «Журнали» в меню — зі словника цього файлу. */
function paint(){
  const on = typeof btOn === "function" && btOn();
  const j = on ? curJ() : null;
  const flag = document.getElementById("btFlag");
  if (flag && on) flag.textContent = T.modeBtFlag + (j ? " · " + label(j) : "");
  document.querySelectorAll('a[data-v="btj"] span').forEach(s => { s.textContent = D().navTitle; });
}

/* Шапка всередині журналу: повернутись до списку, назва журналу й вкладки.

   Вкладки двох рівнів, і вони розведені навмисне. Зверху — що дивимось:
   «Журнал», «Усі угоди», «Огляд». «Календар | Список» — лише вигляд
   самого журналу, тому це окремий перемикач збоку, і видно його тільки
   на вкладці «Журнал». Вигляд памʼятаємо: повернувся з огляду — журнал
   такий самий, яким його лишив. */
/* Назва журналу в рядку «‹ місяць › Сьогодні» календаря й списку. */
function paneTitle(){
  const j = curJ();
  if (!j) return "";
  const period = j.period_from || j.period_to
    ? [human(j.period_from), human(j.period_to)].filter(Boolean).join(" – ") : "";
  const sub = [j.asset, period].filter(Boolean).join(" · ");
  return '<div class="btj-pane"><b>' + esc(label(j)) + "</b>"
    + (sub ? "<span>" + esc(sub) + "</span>" : "") + "</div>";
}
function jStyle(){
  try{ const v = localStorage.getItem("tj_jstyle"); return v === "table" ? "table" : "cal"; }
  catch(e){ return "cal"; }
}
function head(active){
  const d = D(), j = curJ();
  if (!j) return "<h1>" + esc(d.title) + "</h1>";
  const period = j.period_from || j.period_to
    ? [human(j.period_from), human(j.period_to)].filter(Boolean).join(" – ") : "";
  const sub = [j.asset, period].filter(Boolean).join(" · ");
  const inJ = active === "cal" || active === "table";
  const main = (v, on, l, tip) => '<button type="button" class="' + (on ? "on" : "") + '"'
    + (on ? ' aria-current="page"' : "") + (tip ? ' data-tip="' + esc(tip) + '"' : "")
    + ' onclick="__btj.tab(\'' + v + '\')">' + esc(l) + "</button>";
  const tab = (v, l, tip) => '<button class="' + (active === v ? "on" : "") + '"'
    + (tip ? ' data-tip="' + esc(tip) + '"' : "") + ' onclick="__btj.tab(\'' + v + '\')">' + esc(l) + "</button>";
  return '<div class="btj-head"><a class="btj-back" href="#btj">'
    + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M15 6l-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    + esc(d.navTitle) + "</a>"
    /* У календарі й списку назва стоїть у рядку перемотки місяців
       (paneTitle нижче) — там вона поруч із тим, що гортають. Великий
       заголовок лишається тільки для «Усіх угод» і «Огляду». */
    + (["cal", "table"].indexOf(active) >= 0 ? ""
        : '<div class="btj-title"><h1>' + esc(label(j)) + "</h1>"
          + (sub ? '<span class="btj-sub">' + esc(sub) + "</span>" : "") + "</div>")
    + "</div>"
    + '<div class="btj-nav"><div class="btj-main" role="tablist">'
    + main("journal", inJ, d.jTab, d.jTabTip)
    + main("list", active === "list", T.jrAllTab, T.jrAllTabTip)
    + main("ov", active === "ov", d.ovTab, d.ovTabTip) + "</div>"
    + (inJ ? '<div class="seg-tabs btj-style">'
        + tab("cal", T.jrCalTab, T.jrCalTabTip) + tab("table", T.jrTableTab, T.jrTableTabTip) + "</div>" : "")
    + "</div>";
}

/* ---------------- картка журналу ---------------- */

function stat(k){
  const ts = tradesOf(k);
  const c = calc(ts);
  /* Крива й просадка — додаванням, як на «Огляді»: там підсумок місяця
     теж сума відсотків, і дві цифри одного журналу мусять збігатись. */
  let sum = 0, peak = 0, dd = 0;
  const curve = [];
  for (const t of sortAsc(realTrades(ts))){
    sum += netR(t);
    peak = Math.max(peak, sum);
    dd = Math.min(dd, sum - peak);
    curve.push(sum);
  }
  const days = ts.map(t => (t.date || "").slice(0, 10)).filter(Boolean).sort();
  return {c: c, curve: curve, dd: dd, n: ts.length, first: days[0] || "", last: days[days.length - 1] || ""};
}

function card(j){
  const d = D(), s = stat(j.k), c = s.c;
  const period = j.period_from || j.period_to
    ? [human(j.period_from), human(j.period_to)].filter(Boolean).join(" – ")
    : "";
  const sub = [j.asset, period].filter(Boolean).join(" · ");
  const tone = c.net > 0 ? "up" : (c.net < 0 ? "down" : "");
  const cells = [
    [d.nTrades, c.n + (c.skips ? " +" + c.skips + d.skipTag : "")],
    [d.wr, c.wr == null ? "—" : Math.round(c.wr) + "%"],
    [d.avgRR, c.avgRR == null ? "—" : Math.round(c.avgRR * 100) / 100],
    [d.maxDD, c.n ? (Math.round(s.dd * 100) / 100) + "%" : "—"],
  ];
  const spark = window.__acc && __acc.spark ? __acc.spark(s.curve) : "";
  const arg = j.blank ? "null" : j.id;
  /* Уся картка — вхід у журнал: так швидше, ніж цілитись у кнопку. Кнопка
     «Відкрити» лишається — видно, що картка натискається. */
  const go = "__btj.open(" + (j.blank ? "\'\'" : arg) + ")";
  return '<div class="shell"><div class="core ac-card btj-card" onclick="' + go + '">'
    + '<div class="ac-top"><div class="ac-name"><b>' + esc(label(j)) + "</b>"
    +   (sub ? '<div class="ac-sub">' + esc(sub) + "</div>" : "") + "</div>"
    + "</div>"
    + '<div class="ac-bal"><div class="big ' + tone + '">' + esc(c.n ? fmtR(c.net) : "—") + "</div>"
    +   '<div class="ac-from">' + esc(s.n ? d.tradedAt.replace("%s", human(s.first) + (s.last !== s.first ? " – " + human(s.last) : "")) : d.noTrades)
    +   "</div></div>"
    + spark
    + '<div class="ac-cells">' + cells.map(x =>
        '<div class="ac-cell"><div class="l">' + esc(x[0]) + '</div><div class="v">'
        + esc(String(x[1])) + "</div></div>").join("") + "</div>"
    + (j.note ? '<p class="ac-note btj-note">' + esc(j.note) + "</p>" : "")
    + (j.blank ? '<p class="ac-note">' + esc(d.blankHint) + "</p>" : "")
    + '<div class="ac-foot">'
    /* Відкрити можна й відкритий журнал: з нього виходять до списку, і
       повернутись має бути так само просто, як зайти в будь-який інший. */
    +   '<button class="ac-link btj-go" onclick="event.stopPropagation();' + go + '">' + esc(d.open) + "</button>"
    +   '<span class="sp"></span>'
    +   '<button class="ac-link" onclick="event.stopPropagation();__btj.edit(' + arg + ')">' + esc(j.blank ? d.nameIt : d.edit) + "</button>"
    + "</div></div></div>";
}

function vBtj(){
  const d = D();
  if (JS === undefined){ sync().then(() => { if (S.view === "btj") render(); }); return '<div class="empty">' + esc(d.loading) + "</div>"; }
  const head = '<div class="ohead ac-head">'
    + "<h1>" + esc(d.title) + "</h1>"
    + '<button class="btn primary ac-new" onclick="__btj.add()">' + esc(d.add) + "</button></div>";
  const l = list();
  if (!l.length){
    return '<div class="acw">' + head
      + '<div class="shell"><div class="core ac-empty">'
      + "<p>" + esc(d.emptyLead) + '</p><p class="ac-hint">' + esc(d.emptyHint) + "</p>"
      + '<button class="btn primary" onclick="__btj.add()">' + esc(d.add) + "</button>"
      + "</div></div></div>";
  }
  return '<div class="acw">' + head + '<div class="ac-grid btj-grid">' + l.map(card).join("") + "</div></div>";
}

/* ---------------- форма журналу ---------------- */

function field(lab, id, val, ph, note){
  return '<label class="ac-f"><span>' + esc(lab) + (note ? "<i>" + esc(note) + "</i>" : "") + "</span>"
    + '<input class="ac-in" id="' + id + '" type="text" autocomplete="off" value="' + esc(val || "")
    + '"' + (ph ? ' placeholder="' + esc(ph) + '"' : "") + "></label>";
}
function dateField(lab, id, val){
  return '<div class="ac-f"><span>' + esc(lab) + "</span>"
    + '<button type="button" class="ac-in ac-date" id="' + id + '_btn" data-date="' + id + '"'
    + (val ? ' data-set="1"' : "") + "><span>" + esc(val ? human(val) : D().pickDate) + "</span>"
    + '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    + '<rect x="3" y="5" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/>'
    + '<path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
    + "</svg></button>"
    + '<input type="hidden" id="' + id + '" value="' + esc(val || "") + '"></div>';
}
/* Підказки під «Активом»: інструменти, які вже є в бектесті.
   Клік по них ловить спільний обробник рахунків (.ac-pick) — він просто
   підставляє значення в поле. */
function assetPicks(curV){
  const cnt = new Map();
  for (const t of all()){
    const p = norm(t.pair);
    if (p.length >= 2) cnt.set(p, (cnt.get(p) || 0) + 1);
  }
  let vals = [...cnt.entries()].sort((a, b) => b[1] - a[1]).map(x => x[0]);
  if (!vals.length && typeof PAIRS_ACTIVE !== "undefined") vals = PAIRS_ACTIVE.slice();
  vals = vals.slice(0, 6);
  if (!vals.length) return "";
  const now = key(curV);
  return '<div class="ac-picks" role="group">' + vals.map(v =>
    '<button type="button" class="ac-pick' + (key(v) === now ? " on" : "") + '" data-fill="' + esc(v)
    + '" data-target="btjAsset">' + esc(v) + "</button>").join("") + "</div>";
}

let editJ = null;
function openForm(j){
  const d = D();
  editJ = j;
  const isNew = !j.id;
  openModal('<div class="m-head"><h2>' + esc(j.blank ? d.nameTitle : (isNew ? d.newTitle : d.editTitle)) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(d.close) + '">×</button></div>'
    + '<div class="m-body ac-form btj-form">'
    + field(d.fName, "btjName", j.name, d.phName, d.nName)
    + '<div>' + field(d.fAsset, "btjAsset", j.asset, d.phAsset) + assetPicks(j.asset) + "</div>"
    + '<div class="ac-row2">' + dateField(d.fFrom, "btjFrom", j.period_from)
    +   dateField(d.fTo, "btjTo", j.period_to) + "</div>"
    + field(d.fNote, "btjNote", j.note, d.phNote)
    + '<p class="ac-err" id="btjErr" hidden></p></div>'
    + '<div class="m-foot">'
    + (j.id ? '<button class="btn danger" onclick="__btj.drop(' + j.id + ')">' + esc(d.del) + "</button>" : "")
    + '<span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(d.cancel) + "</button>"
    + '<button class="btn primary" onclick="__btj.save()">' + esc(d.save) + "</button></div>");
  const nm = document.getElementById("btjName");
  if (nm && !j.id) nm.focus();
}

function val(id){ const el = document.getElementById(id); return el ? el.value.trim() : ""; }

async function save(){
  const d = D(), j = editJ || {};
  const err = document.getElementById("btjErr");
  const body = {id: j.id || null, name: val("btjName"), asset: val("btjAsset"),
    period_from: val("btjFrom"), period_to: val("btjTo"), note: val("btjNote")};
  if (!body.name){ if (err){ err.textContent = d.errName; err.hidden = false; } return; }
  let saved;
  try{
    /* «Без журналу» стає журналом: сервер тією ж транзакцією переносить
       у нього угоди без підпису. */
    saved = (await api("POST", "/api/bt/journals",
      j.blank ? {journal: body, adopt: ""} : {journal: body})).journal;
  }catch(e){
    if (err){ err.textContent = d.errSave; err.hidden = false; }
    return;
  }
  /* Новий журнал одразу відкриваємо: людина завела його, щоб у нього писати.
     Перейменований відкритий — лишається відкритим під новим імʼям. */
  const wasOpen = j.blank ? cur === "" : (j.id && key(j.name) === cur);
  if (!j.id || wasOpen) select(saved.name);
  closeModal();
  await reloadAll();
  /* Новий журнал заводять, щоб писати в нього, — одразу всередину. */
  if (!j.id && !j.blank) location.hash = "journal";
}

async function drop(id){
  const d = D();
  const j = (JS || []).find(x => x.id === id);
  if (!j) return;
  const n = tradesOf(key(j.name)).length;
  const ask = n ? d.delAskN.replace("%n", n) : d.delAsk;
  if (!await Ask.yes(ask, {ok: d.delYes, cancel: d.cancel, danger: true})) return;
  try{ await api("POST", "/api/bt/journals/drop", {id: id}); }catch(e){ return; }
  if (key(j.name) === cur){ cur = null; try{ localStorage.removeItem(LS); }catch(e){} }
  closeModal();
  await reloadAll();
}

async function reloadAll(){
  try{ await reload(); }catch(e){}
  render();
}

window.__btj = {
  sync: sync, filter: filter, select: select, paint: paint, head: head, paneTitle: paneTitle,
  isOpen(){ return !!curJ(); },
  /* Вкладки шапки журналу: календар, список і всі угоди — режими розділу
     «Журнал», огляд — окремий розділ. */
  tab(v){
    if (v === "ov"){ location.hash = "dashboard"; return; }
    if (v === "journal") v = jStyle();
    if (v === "cal" || v === "table"){ try{ localStorage.setItem("tj_jstyle", v); }catch(e){} }
    S.jMode = v;
    /* ключ бектесту: реальний журнал свій вигляд памʼятає окремо */
    try{ localStorage.setItem("tj_jmode_bt", v); }catch(e){}
    if (location.hash === "#journal") render(); else location.hash = "journal";
  },
  navLabel(){ return D().navTitle; },
  /* Для форми угоди: назви журналів, відкритий — першим. */
  names(){
    const l = (JS || []).map(j => norm(j.name)).filter(Boolean);
    const c = curJ();
    if (c && !c.blank) l.sort((a, b) => (key(b) === cur) - (key(a) === cur));
    return l;
  },
  curName(){ const c = curJ(); return c && !c.blank ? c.name : ""; },
  asset(){ const c = curJ(); return c && c.asset ? c.asset : ""; },
  none(){ return !list().length; },
  add(){ openForm({name: "", asset: "", period_from: "", period_to: "", note: ""}); },
  edit(id){
    if (id === null){ openForm({id: 0, blank: true, name: "", asset: "", period_from: "", period_to: "", note: ""}); return; }
    const j = (JS || []).find(x => x.id === id);
    if (j) openForm(Object.assign({}, j));
  },
  /* Відкрити журнал — і одразу в нього: календар, як у звичайному журналі. */
  open(id){
    const j = id === "" ? {name: ""} : (JS || []).find(x => x.id === id);
    if (!j) return;
    select(j.name);
    S.trades = S.all = filter(all());
    /* Новий журнал відкривається вкладкою «Журнал» (календар чи список —
       як звик), а не тим, що лишилось відкритим у попередньому. */
    S.jMode = jStyle();
    try{ localStorage.setItem("tj_jmode_bt", S.jMode); }catch(e){}
    /* Календар і день — на останню угоду журналу: прогін іде по історії,
       і поточний місяць у ньому зазвичай порожній. */
    const last = sortAsc(S.all).pop();
    if (last){ S.selDay = dayKey(last); S.jMonth = monKey(last); }
    S.pages = {}; S.filters = {};
    if (location.hash === "#journal") render(); else location.hash = "journal";
  },
  save: save, drop: drop,
};

VIEWS.btj = vBtj;

/* ============================================================
   Словник розділу — тут, а не в i18n.js, як і в «Рахунків».
   ============================================================ */
const DICT = {
uk: {
  title: "Журнали бектесту", navTitle: "Журнали", loading: "Хвилинку…",
  add: "Новий журнал", close: "Закрити", cancel: "Скасувати", save: "Зберегти",
  edit: "Правити", del: "Видалити", open: "Відкрити", opened: "Відкритий",
  nameIt: "Назвати", blank: "Без журналу",
  blankHint: "Угоди, записані без журналу. Дай їм назву — і вони стануть окремим журналом.",
  ovTab: "Огляд", ovTabTip: "Підсумки тижня, місяця й року — по цьому журналу",
  jTab: "Журнал", jTabTip: "Угоди по днях — календарем або списком",
  emptyLead: "Журнал бектесту — окремий набір прогонів: свій актив, свій період, своя статистика.",
  emptyHint: "Заведи по журналу на кожен актив чи ідею — і їхні цифри не змішуватимуться.",
  nTrades: "Угод", wr: "Вінрейт", avgRR: "Середній RR", maxDD: "Просадка від піку", skipTag: " скіп",
  tradedAt: "угоди з %s", noTrades: "угод ще немає",
  newTitle: "Новий журнал бектесту", editTitle: "Журнал бектесту", nameTitle: "Назвати журнал",
  fName: "Назва", nName: "так він зватиметься у формі угоди", phName: "US100 · NY сесія",
  fAsset: "Актив", phAsset: "US100",
  fFrom: "Історія з", fTo: "по", pickDate: "обрати дату",
  fNote: "Нотатка", phNote: "що перевіряю: сетап, правила, таймфрейм",
  errName: "Дай журналу назву.", errSave: "Не вдалось зберегти. Перевір звʼязок і спробуй ще раз.",
  delAsk: "Видалити цей журнал?",
  delAskN: "Видалити журнал разом з його угодами (%n)? Повернути їх не вийде.",
  delYes: "Видалити",
},
ru: {
  title: "Журналы бэктеста", navTitle: "Журналы", loading: "Минутку…",
  add: "Новый журнал", close: "Закрыть", cancel: "Отмена", save: "Сохранить",
  edit: "Править", del: "Удалить", open: "Открыть", opened: "Открыт",
  nameIt: "Назвать", blank: "Без журнала",
  blankHint: "Сделки, записанные без журнала. Дай им название — и они станут отдельным журналом.",
  ovTab: "Обзор", ovTabTip: "Итоги недели, месяца и года — по этому журналу",
  jTab: "Журнал", jTabTip: "Сделки по дням — календарём или списком",
  emptyLead: "Журнал бэктеста — отдельный набор прогонов: свой актив, свой период, своя статистика.",
  emptyHint: "Заведи по журналу на каждый актив или идею — и их цифры не будут смешиваться.",
  nTrades: "Сделок", wr: "Винрейт", avgRR: "Средний RR", maxDD: "Просадка от пика", skipTag: " скип",
  tradedAt: "сделки с %s", noTrades: "сделок ещё нет",
  newTitle: "Новый журнал бэктеста", editTitle: "Журнал бэктеста", nameTitle: "Назвать журнал",
  fName: "Название", nName: "так он будет называться в форме сделки", phName: "US100 · NY сессия",
  fAsset: "Актив", phAsset: "US100",
  fFrom: "История с", fTo: "по", pickDate: "выбрать дату",
  fNote: "Заметка", phNote: "что проверяю: сетап, правила, таймфрейм",
  errName: "Дай журналу название.", errSave: "Не получилось сохранить. Проверь связь и попробуй ещё раз.",
  delAsk: "Удалить этот журнал?",
  delAskN: "Удалить журнал вместе с его сделками (%n)? Вернуть их не получится.",
  delYes: "Удалить",
},
en: {
  title: "Backtest journals", navTitle: "Journals", loading: "One moment…",
  add: "New journal", close: "Close", cancel: "Cancel", save: "Save",
  edit: "Edit", del: "Delete", open: "Open", opened: "Open now",
  nameIt: "Name it", blank: "No journal",
  blankHint: "Trades logged without a journal. Give them a name and they become a journal of their own.",
  ovTab: "Overview", ovTabTip: "Week, month and year results — for this journal",
  jTab: "Journal", jTabTip: "Trades by day — as a calendar or a list",
  emptyLead: "A backtest journal is a separate set of runs: its own asset, period and stats.",
  emptyHint: "Keep one journal per asset or idea so their numbers never mix.",
  nTrades: "Trades", wr: "Win rate", avgRR: "Avg RR", maxDD: "Drawdown from peak", skipTag: " skip",
  tradedAt: "trades from %s", noTrades: "no trades yet",
  newTitle: "New backtest journal", editTitle: "Backtest journal", nameTitle: "Name this journal",
  fName: "Name", nName: "shown in the trade form", phName: "US100 · NY session",
  fAsset: "Asset", phAsset: "US100",
  fFrom: "History from", fTo: "to", pickDate: "pick a date",
  fNote: "Note", phNote: "what I'm testing: setup, rules, timeframe",
  errName: "Give the journal a name.", errSave: "Couldn't save. Check your connection and try again.",
  delAsk: "Delete this journal?",
  delAskN: "Delete the journal together with its trades (%n)? This can't be undone.",
  delYes: "Delete",
},
};

})();
