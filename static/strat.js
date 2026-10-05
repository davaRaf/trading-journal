/* ============================================================
   Кілька торгових стратегій (strat.js).

   У людини може бути не одна ТС: скальп на US100 і свінг на золоті —
   різні правила і різна статистика. Кожна стратегія — свій журнал:
   перемикач праворуч від заголовка «Огляду», «Журналу», «Аналітики» й
   «Моєї ТС» показує угоди й правила обраної (у журналі — ще й «усі»).
   У кожної стратегії свій колір-крапка. Угода пам'ятає свою стратегію
   полем ts ("" — перша, інакше номер із сервера).

   Поки стратегія одна, перемикача ніде немає — лише тиха кнопка
   «+ Стратегія» біля «Моєї ТС», щоб було звідки почати.
   У бектесті стратегій немає: там свої журнали (btj.js).
   ============================================================ */
(function(){

let L;               /* [{id, name, has}] з /api/ts/list; undefined — ще не читали */
let cur = "0";       /* обрана: "0", номер або "all" */
const LS = "tj_strat";
try{ cur = localStorage.getItem(LS) || "0"; }catch(e){}

function D(){ return DICT[window.LANG] || DICT.ru; }
function off(){
  return (typeof btOn === "function" && btOn()) || (typeof DEMO !== "undefined" && DEMO) || (window.Pub && Pub.on);
}
function list(){ return L || [{id: 0, name: "", has: false}]; }
function nm(s, i){ return (s.name || "").trim() || D().ts + " " + (i + 1); }
function label(id){
  const l = list(), i = l.findIndex(s => String(s.id) === String(id || 0));
  return i < 0 ? nm(l[0], 0) : nm(l[i], i);
}
function multi(){ return !off() && list().length > 1; }
/* яку ТС показувати й куди писати угоду: при «всіх» — першу */
function sid(){ return off() || cur === "all" ? "0" : cur; }

async function load(){
  /* DEMO тут ще не відомий: reload() з'ясовує його після угод, а нас кличе
     раніше. Тож питаємо лише бектест і чужий журнал; у демо запит просто
     не вдасться, і лишиться одна стратегія. */
  if ((typeof btOn === "function" && btOn()) || (window.Pub && Pub.on)) return;
  try{ L = (await api("GET", "/api/ts/list")).list || []; }
  catch(e){ L = L || [{id: 0, name: "", has: false}]; }
  if (cur !== "all" && !list().some(s => String(s.id) === cur)) cur = "0";
  if (cur === "all" && !multi()) cur = "0";
}

function filter(trades){
  if (!multi() || cur === "all") return trades;
  return trades.filter(t => String(t.ts || "0") === cur);
}

function select(v){
  cur = String(v);
  try{ localStorage.setItem(LS, cur); }catch(e){}
}

/* після зміни стратегії: журнал — її угоди, «Моя ТС» — її правила */
function apply(){
  if (Array.isArray(S.liveAll)) S.trades = S.all = filter(S.liveAll);
  S.pages = {}; S.filters = {};
  if (window.__ts && __ts.reload) __ts.reload();
  render();
}

/* ---------------- перемикач ---------------- */
/* у кожної стратегії свій колір — щоб розрізняти з першого погляду */
const COLORS = ["var(--accent)", "#a58bff", "#e0b341", "#2fc6b3", "#ff6fa8", "#5aa2ff", "#ff8a4c", "#9bd35a", "#c48bff", "#7aa0b8"];
function color(id){
  const i = list().findIndex(s => String(s.id) === String(id || 0));
  return COLORS[(i < 0 ? 0 : i) % COLORS.length];
}
function count(id){
  const all = Array.isArray(S.liveAll) ? S.liveAll : [];
  return id === "all" ? all.length : all.filter(t => String(t.ts || "0") === String(id)).length;
}
const CHEV = '<svg class="sw-chev" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const TICK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function dots(){ return '<span class="sw-dots">' + list().slice(0, 3).map(s => '<i style="--c:' + color(s.id) + '"></i>').join("") + "</span>"; }

/* where: "j" — журнал/огляд/аналітика (є «усі»), "ts" — «Моя ТС» */
function btn(where){
  if (off()) return "";
  const plus = where === "ts" && L !== undefined
    ? '<button type="button" class="sw-add" onclick="__strat.quick()" data-tip="' + esc(D().addTip) + '">+ ' + esc(D().newOne) + "</button>"
    : "";
  if (!multi()) return plus;
  const v = where === "ts" ? sid() : cur;
  const all = v === "all";
  return '<button type="button" class="sw-pill" aria-haspopup="menu" onclick="__strat.menu(this,\'' + (where || "j") + '\')">'
    + (all ? dots() : '<i class="sw-dot" style="--c:' + color(v) + '"></i>')
    + '<span class="sw-name">' + esc(all ? D().all : label(v)) + "</span>"
    + (where === "ts" ? "" : '<span class="sw-n">' + count(v) + "</span>") + CHEV + "</button>" + plus;
}

/* «+ Нова стратегія»: одразу заводимо порожню й відкриваємо її — там
   людину чекає звичний вибір: опитування з нуля або підтягнути з Notion.
   Назва — «ТС N», перейменувати можна в меню «⋯». */
async function quick(){
  let r;
  try{ r = await api("POST", "/api/ts/new", {name: ""}); }catch(e){ return; }
  L = r.list || L;
  go(String(r.id));
}

let pop = null;
function closeMenu(){
  if (!pop) return;
  pop.remove(); pop = null;
  document.removeEventListener("mousedown", outside, true);
  document.removeEventListener("keydown", onKey, true);
  window.removeEventListener("scroll", closeMenu, true);
}
function outside(e){ if (pop && !pop.contains(e.target) && !e.target.closest(".sw-pill")) closeMenu(); }
function onKey(e){ if (e.key === "Escape"){ e.stopPropagation(); closeMenu(); } }

function menu(b, where){
  if (pop){ const was = pop.dataset.for === where; closeMenu(); if (was) return; }
  const d = D(), v = where === "ts" ? sid() : cur;
  const row = (id, name, c, n) =>
    '<button type="button" role="menuitemradio" class="sw-row' + (String(id) === String(v) ? " on" : "") + '" data-v="' + id + '">'
    + c + '<span class="sw-rn">' + esc(name) + "</span>"
    + (n == null ? "" : '<span class="sw-rc">' + n + "</span>") + '<span class="sw-ok">' + TICK + "</span></button>";
  let h = '<div class="sw-head">' + esc(where === "ts" ? d.labTs : d.lab) + "</div>";
  h += list().map((s, i) => row(s.id, nm(s, i), '<i class="sw-dot" style="--c:' + color(s.id) + '"></i>',
                                where === "ts" ? null : count(s.id))).join("");
  if (where !== "ts") h += '<div class="sw-sep"></div>' + row("all", d.all, dots(), count("all"));
  pop = document.createElement("div");
  pop.className = "sw-pop"; pop.setAttribute("role", "menu"); pop.dataset.for = where;
  pop.innerHTML = h;
  pop.style.zIndex = window.nextTop ? nextTop() : 9000;
  document.body.appendChild(pop);
  const r = b.getBoundingClientRect();
  const w = pop.offsetWidth, hgt = pop.offsetHeight;
  pop.style.left = Math.min(Math.max(8, r.left), innerWidth - w - 8) + "px";
  pop.style.top = (r.bottom + 6 + hgt > innerHeight - 8 && r.top > hgt + 14 ? r.top - hgt - 6 : r.bottom + 6) + "px";
  pop.addEventListener("click", e => {
    const it = e.target.closest("[data-v]");
    if (!it) return;
    closeMenu();
    select(it.dataset.v); apply();
  });
  setTimeout(() => {
    document.addEventListener("mousedown", outside, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", closeMenu, true);
  }, 0);
}
function go(v){ select(v); apply(); }

/* ---------------- нова / перейменувати / прибрати ---------------- */
function sheet(title, body, foot){
  Sheet.open('<div class="m-head"><h2>' + esc(title) + '</h2><button class="x" aria-label="'
    + esc(D().close) + '" onclick="Sheet.close()">×</button></div>'
    + '<div class="m-body strat-form">' + body + "</div>"
    + '<div class="m-foot">' + foot + "</div>", {cls: "strat-pnl"});
  const f = document.getElementById("stName"); if (f){ f.focus(); f.select(); }
}

function add(){
  const d = D(), from = label(sid());
  sheet(d.newTitle,
    '<label class="st-lab">' + esc(d.name) + '</label><input id="stName" maxlength="60" placeholder="'
    + esc(d.namePh) + '" value="' + esc(d.ts + " " + (list().length + 1)) + '">'
    + '<label class="st-lab">' + esc(d.start) + "</label>"
    + '<div class="st-opts">'
    + '<label class="st-opt"><input type="radio" name="stFrom" value="empty" checked><span><b>' + esc(d.empty)
    + "</b><i>" + esc(d.emptyX) + "</i></span></label>"
    + '<label class="st-opt"><input type="radio" name="stFrom" value="copy"><span><b>' + esc(d.copy) + " «" + esc(from)
    + "»</b><i>" + esc(d.copyX) + "</i></span></label></div>"
    + '<p class="st-note">' + esc(d.newNote) + "</p>",
    '<button class="btn" onclick="Sheet.close()">' + esc(d.cancel) + '</button><span class="sp"></span>'
    + '<button class="btn primary" onclick="__strat.create()">' + esc(d.create) + "</button>");
}

async function create(){
  const name = (document.getElementById("stName") || {}).value || "";
  const copy = (document.querySelector('input[name="stFrom"]:checked') || {}).value === "copy";
  let r;
  try{ r = await api("POST", "/api/ts/new", Object.assign({name: name.trim()}, copy ? {copy: +sid()} : {})); }
  catch(e){ return; }
  L = r.list || L;
  Sheet.close();
  go(String(r.id));
}

function edit(id){
  const d = D(), l = list(), i = l.findIndex(s => s.id === id);
  if (i < 0) return;
  const s = l[i];
  sheet(d.editTitle,
    '<label class="st-lab">' + esc(d.name) + '</label><input id="stName" maxlength="60" placeholder="'
    + esc(nm(s, i)) + '" value="' + esc(s.name || "") + '">'
    + (id ? '<p class="st-note">' + esc(d.dropNote.replace("%s", label(0))) + "</p>" : ""),
    (id ? '<button class="btn danger" onclick="__strat.drop(' + id + ')">' + esc(d.del) + "</button>" : "")
    + '<span class="sp"></span><button class="btn" onclick="Sheet.close()">' + esc(d.cancel) + "</button>"
    + '<button class="btn primary" onclick="__strat.rename(' + id + ')">' + esc(d.save) + "</button>");
}

async function rename(id){
  const name = ((document.getElementById("stName") || {}).value || "").trim();
  try{ L = (await api("POST", "/api/ts/rename", {sid: id, name: name})).list || L; }catch(e){ return; }
  Sheet.close();
  render();
}

async function drop(id){
  const d = D();
  if (!(await Ask.yes(d.dropAsk.replace("%s", label(id)).replace("%t", label(0)),
                      {ok: d.del, cancel: d.cancel, danger: true}))) return;
  try{ L = (await api("POST", "/api/ts/drop", {sid: id})).list || L; }catch(e){ return; }
  Sheet.close();
  /* угоди стратегії тепер у першій — перечитуємо журнал */
  select("0");
  try{ await reload(); }catch(e){}
  apply();
}

/* ---------------- форма угоди і картка ---------------- */
function formField(t){
  const v = t ? String(t.ts || "") : (sid() === "0" ? "" : sid());
  const hidden = '<input type="hidden" id="fld_ts" value="' + esc(v) + '">';
  if (!multi()) return hidden;
  return '<div class="f strat-f"><label>' + esc(D().lab) + "</label>"
    + '<div class="strat-chips">' + list().map((s, i) => {
        const k = s.id ? String(s.id) : "";
        return '<button type="button" class="' + (k === v ? "on" : "") + '" data-v="' + k
          + '" onclick="__strat.pickForm(this)"><i class="sw-dot" style="--c:' + color(s.id) + '"></i>' + esc(nm(s, i)) + "</button>";
      }).join("") + "</div>" + hidden + "</div>";
}
function pickForm(b){
  b.parentElement.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  document.getElementById("fld_ts").value = b.dataset.v;
}
/* рядок «Стратегія — ТС 2» у картці угоди; поки стратегія одна — нічого */
function fact(t){ return multi() ? [D().lab, label(t.ts)] : null; }

/* у меню «⋯»: першу стратегію можна лише перейменувати */
function editWord(){ return sid() === "0" ? D().renameOnly : D().editTip; }

window.__strat = {load, editWord, filter, multi, sid, label, color, btn, menu, go, add, quick, create, edit, rename, drop,
                  formField, pickForm, fact};

/* Журнал міг прочитати угоди ще до того, як підвантажився цей файл (на
   локальному сервері відповідь приходить миттєво) — тоді reload() нас не
   покликав. Добираємо стратегії самі й перемальовуємо. */
setTimeout(async () => {
  if (L !== undefined || !Array.isArray(S.liveAll) || off()) return;
  await load();
  if (multi()){ S.trades = S.all = filter(S.liveAll); render(); }
}, 0);

const DICT = {
uk: {
  ts: "ТС", lab: "Стратегія", labTs: "Торгові стратегії", newOne: "Нова стратегія", all: "Усі стратегії", add: "Стратегія", addTip: "Додати ще одну торгову стратегію",
  editTip: "Перейменувати або прибрати стратегію", renameOnly: "Перейменувати стратегію", close: "Закрити", cancel: "Скасувати", save: "Зберегти", del: "Прибрати",
  newTitle: "Нова стратегія", editTitle: "Стратегія", name: "Назва", namePh: "Скальп US100",
  start: "З чого почати", empty: "З нуля", emptyX: "Порожня ТС — заповниш опитуванням, з Notion або руками",
  copy: "Копія", copyX: "Ті самі правила — далі правиш під нову ідею", create: "Створити",
  newNote: "У кожної стратегії свій журнал: угоди записуються під обрану, а статистика рахується окремо.",
  dropNote: "Якщо прибрати стратегію, її угоди не зникнуть — вони перейдуть у «%s».",
  dropAsk: "Прибрати «%s»? Правила стратегії видаляться, а її угоди перейдуть у «%t».",
},
ru: {
  ts: "ТС", lab: "Стратегия", labTs: "Торговые стратегии", newOne: "Новая стратегия", all: "Все стратегии", add: "Стратегия", addTip: "Добавить ещё одну торговую стратегию",
  editTip: "Переименовать или удалить стратегию", renameOnly: "Переименовать стратегию", close: "Закрыть", cancel: "Отмена", save: "Сохранить", del: "Удалить",
  newTitle: "Новая стратегия", editTitle: "Стратегия", name: "Название", namePh: "Скальп US100",
  start: "С чего начать", empty: "С нуля", emptyX: "Пустая ТС — заполнишь опросом, из Notion или вручную",
  copy: "Копия", copyX: "Те же правила — дальше правишь под новую идею", create: "Создать",
  newNote: "У каждой стратегии свой журнал: сделки записываются под выбранную, а статистика считается отдельно.",
  dropNote: "Если удалить стратегию, её сделки не пропадут — они перейдут в «%s».",
  dropAsk: "Удалить «%s»? Правила стратегии удалятся, а её сделки перейдут в «%t».",
},
en: {
  ts: "System", lab: "Strategy", labTs: "Trading systems", newOne: "New strategy", all: "All strategies", add: "Strategy", addTip: "Add another trading strategy",
  editTip: "Rename or remove strategy", renameOnly: "Rename strategy", close: "Close", cancel: "Cancel", save: "Save", del: "Remove",
  newTitle: "New strategy", editTitle: "Strategy", name: "Name", namePh: "US100 scalp",
  start: "Start from", empty: "Scratch", emptyX: "An empty system — fill it via the survey, Notion or by hand",
  copy: "Copy of", copyX: "Same rules — then adjust them for the new idea", create: "Create",
  newNote: "Each strategy has its own journal: trades are logged under the chosen one and stats are counted separately.",
  dropNote: "Removing a strategy keeps its trades — they move to “%s”.",
  dropAsk: "Remove “%s”? Its rules are deleted and its trades move to “%t”.",
},
};

})();
