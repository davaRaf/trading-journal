/* ============================================================
   Заметки (notes.js).

   Свободные записи с названием — правило, вывод недели, идея. Не про
   одну сделку, поэтому живут не в форме угоди, а в «Обзоре»: маленькая
   карточка под календарём года показывает последние названия, сама
   запись пишется в боковой панели. Сохраняется сама, без кнопки, —
   через полсекунды после последней буквы.

   Сервер: /api/notes (notes_store.py). Словарь — здесь, как в btj.js.
   ============================================================ */
(function(){

let L;               /* заметки с сервера; undefined — ещё не читали */
let cur = null;      /* открытая в редакторе: {id?, title, body, pinned} */
let timer = 0, saving = null, q = "";
const SHOW = 4;      /* сколько названий видно в карточке */

function D(){ return DICT[window.LANG] || DICT.ru; }
function off(){ return (typeof DEMO !== "undefined" && DEMO) || (window.Pub && Pub.on); }
function day(iso){
  const d = new Date(iso); if (isNaN(d)) return "";
  const p = n => String(n).padStart(2, "0");
  return p(d.getDate()) + "." + p(d.getMonth() + 1) + (d.getFullYear() !== new Date().getFullYear() ? "." + d.getFullYear() : "");
}
function name(n){
  const t = (n.title || "").trim();
  if (t) return t;
  const first = (n.body || "").trim().split("\n")[0];
  return first ? first.slice(0, 60) : D().untitled;
}
function snip(n){
  const b = (n.body || "").trim();
  const rest = (n.title || "").trim() ? b : b.split("\n").slice(1).join(" ");
  return rest.replace(/\s+/g, " ").slice(0, 90);
}
function sorted(){
  return (L || []).slice().sort((a, b) => (b.pinned - a.pinned) || (a.updated < b.updated ? 1 : -1));
}
function repaint(){
  if (typeof S !== "undefined" && S.view === "dashboard" && typeof render === "function") render();
}

async function load(){
  try{ L = (await api("GET", "/api/notes")).notes || []; }
  catch(e){ L = L || []; }
  repaint();
}

/* ---------------- карточка в «Обзоре» ---------------- */
function railHtml(){
  if (off()) return "";
  const d = D();
  if (L === undefined){ load(); }
  const list = sorted();
  const rows = list.slice(0, SHOW).map(n =>
    '<button class="nrow" onclick="__notes.open(' + n.id + ')">'
    + (n.pinned ? '<i class="npin" aria-hidden="true">•</i>' : "")
    + "<b>" + esc(name(n)) + "</b><em>" + esc(day(n.updated)) + "</em></button>").join("");
  const body = L === undefined ? ""
    : list.length ? '<div class="nlist">' + rows + "</div>"
      + (list.length > SHOW ? '<button class="nall" onclick="__notes.all()">' + esc(d.all) + " · " + list.length + "</button>" : "")
    : '<p class="nempty">' + esc(d.empty) + "</p>";
  return '<div class="inner ovn"><div class="cut">'
    + "<h3>" + esc(d.title)
    + '<button class="nadd" onclick="__notes.add()" data-tip="' + esc(d.newTip) + '" aria-label="' + esc(d.newTip) + '">+</button></h3>'
    + body + "</div></div>";
}

/* ---------------- панель ---------------- */
function head(back){
  const d = D();
  return '<div class="m-head nhead">'
    + (back ? '<button class="nback" onclick="__notes.all()">← ' + esc(d.all) + "</button>" : "<h2>" + esc(d.title) + "</h2>")
    + '<button class="x" aria-label="' + esc(d.close) + '" onclick="Sheet.close()">×</button></div>';
}

function listHtml(){
  const d = D(), k = q.trim().toLowerCase();
  const list = sorted().filter(n => !k || (n.title + " " + n.body).toLowerCase().includes(k));
  const rows = list.map(n =>
    '<button class="nitem" onclick="__notes.open(' + n.id + ')">'
    + '<span class="nt">' + (n.pinned ? '<i class="npin">•</i>' : "") + esc(name(n)) + "</span>"
    + (snip(n) ? '<span class="ns">' + esc(snip(n)) + "</span>" : "")
    + '<span class="nd">' + esc(day(n.updated)) + "</span></button>").join("");
  return rows || '<p class="nempty">' + esc(k ? d.nothing : d.empty) + "</p>";
}

function all(){
  const wait = flush();
  cur = null;
  const d = D();
  const h = head(false)
    + '<div class="m-body nbody">'
    + '<div class="ntools"><input id="nq" type="search" placeholder="' + esc(d.search) + '" value="' + esc(q) + '" oninput="__notes.find(this.value)">'
    + '<button class="btn primary" onclick="__notes.add()">' + esc(d.add) + "</button></div>"
    + '<div class="nitems" id="nitems">' + listHtml() + "</div></div>";
  if (Panel.isOpen()) Panel.box().innerHTML = h; else Sheet.open(h, {cls: "notes-pnl", onClose: closed});
  /* недописанная только что ушла на сервер — дорисуем, когда вернётся */
  wait.then(() => { const el = document.getElementById("nitems"); if (el) el.innerHTML = listHtml(); });
}

function find(v){ q = v; const el = document.getElementById("nitems"); if (el) el.innerHTML = listHtml(); }

function editor(n){
  cur = {id: n.id || 0, title: n.title || "", body: n.body || "", pinned: !!n.pinned};
  const d = D();
  const h = head(true)
    + '<div class="m-body nbody ned">'
    + '<input id="ntitle" class="ntitle" maxlength="120" placeholder="' + esc(d.titlePh) + '" value="' + esc(cur.title) + '" oninput="__notes.edit()">'
    + '<textarea id="ntext" class="ntext" placeholder="' + esc(d.bodyPh) + '" oninput="__notes.edit()">' + esc(cur.body) + "</textarea></div>"
    + '<div class="m-foot">'
    + '<button class="btn npinb' + (cur.pinned ? " on" : "") + '" onclick="__notes.pin(this)">' + esc(cur.pinned ? d.unpin : d.pin) + "</button>"
    + '<span class="sp"></span><span class="nstate" id="nstate"></span>'
    + (cur.id ? '<button class="btn danger" onclick="__notes.drop()">' + esc(d.del) + "</button>" : "")
    + "</div>";
  if (Panel.isOpen()) Panel.box().innerHTML = h; else Sheet.open(h, {cls: "notes-pnl", onClose: closed});
  const f = document.getElementById(cur.id ? "ntext" : "ntitle");
  if (f) f.focus();
}

function add(){ flush(); editor({}); }
function open(id){ flush(); const n = (L || []).find(x => x.id === id); if (n) editor(n); }

function state(t){ const el = document.getElementById("nstate"); if (el) el.textContent = t; }

function edit(){
  if (!cur) return;
  cur.title = (document.getElementById("ntitle") || {}).value || "";
  cur.body = (document.getElementById("ntext") || {}).value || "";
  state(D().saving);
  clearTimeout(timer);
  timer = setTimeout(save, 600);
}

function pin(btn){
  if (!cur) return;
  cur.pinned = !cur.pinned;
  btn.classList.toggle("on", cur.pinned);
  btn.textContent = cur.pinned ? D().unpin : D().pin;
  clearTimeout(timer); save();
}

async function save(){
  timer = 0;
  if (!cur) return;
  /* пустую новую не заводим: открыл и передумал — ничего не осталось */
  if (!cur.id && !cur.title.trim() && !cur.body.trim()){ state(""); return; }
  const mine = cur;
  const body = {note: {id: mine.id || undefined, title: mine.title, body: mine.body, pinned: mine.pinned}};
  saving = api("POST", "/api/notes", body).then(r => {
    const n = r.note; if (!n) return;
    if (!mine.id){
      mine.id = n.id;
      /* у новой после первого сохранения появляется «Удалить» */
      const foot = Panel.isOpen() && Panel.box().querySelector(".m-foot");
      if (foot && cur === mine && !foot.querySelector(".danger"))
        foot.insertAdjacentHTML("beforeend", '<button class="btn danger" onclick="__notes.drop()">' + esc(D().del) + "</button>");
    }
    L = (L || []).filter(x => x.id !== n.id).concat([n]);
    if (cur === mine) state(D().saved);
  }).catch(() => { if (cur === mine) state(D().failed); });
  await saving; saving = null;
}

/* недописанное сохраняем сразу — при переходе к списку и закрытии */
function flush(){
  if (timer){ clearTimeout(timer); return save(); }
  return saving || Promise.resolve();
}

async function drop(){
  if (!cur || !cur.id) return;
  const d = D();
  if (window.Ask ? !(await Ask.yes(d.delAsk, {ok: d.del, cancel: d.cancel, danger: true})) : !confirm(d.delAsk)) return;
  clearTimeout(timer); timer = 0;
  const id = cur.id;
  try{ await api("POST", "/api/notes/drop", {id: id}); }catch(e){ return; }
  L = (L || []).filter(x => x.id !== id);
  cur = null;
  all();
}

function closed(){ const wait = flush(); cur = null; wait.then(() => setTimeout(repaint, 280)); }

window.__notes = {railHtml, add, open, all, find, edit, pin, drop};

const DICT = {
uk: {
  title: "Нотатки", all: "Усі нотатки", add: "Нова нотатка", newTip: "Нова нотатка", close: "Закрити",
  empty: "Правила, висновки тижня, ідеї — усе, що не про одну угоду.",
  nothing: "Нічого не знайшлось.", search: "Пошук у нотатках", untitled: "Без назви",
  titlePh: "Назва", bodyPh: "Пиши тут — зберігається саме",
  saving: "Зберігаю…", saved: "Збережено", failed: "Не збереглось — перевір звʼязок",
  pin: "Закріпити", unpin: "Відкріпити", del: "Видалити", cancel: "Скасувати",
  delAsk: "Видалити цю нотатку? Повернути її не вийде.",
},
ru: {
  title: "Заметки", all: "Все заметки", add: "Новая заметка", newTip: "Новая заметка", close: "Закрыть",
  empty: "Правила, выводы недели, идеи — всё, что не про одну сделку.",
  nothing: "Ничего не нашлось.", search: "Поиск по заметкам", untitled: "Без названия",
  titlePh: "Название", bodyPh: "Пиши здесь — сохраняется само",
  saving: "Сохраняю…", saved: "Сохранено", failed: "Не сохранилось — проверь связь",
  pin: "Закрепить", unpin: "Открепить", del: "Удалить", cancel: "Отмена",
  delAsk: "Удалить эту заметку? Вернуть её не получится.",
},
en: {
  title: "Notes", all: "All notes", add: "New note", newTip: "New note", close: "Close",
  empty: "Rules, weekly takeaways, ideas — anything that isn't about a single trade.",
  nothing: "Nothing found.", search: "Search notes", untitled: "Untitled",
  titlePh: "Title", bodyPh: "Write here — it saves on its own",
  saving: "Saving…", saved: "Saved", failed: "Not saved — check your connection",
  pin: "Pin", unpin: "Unpin", del: "Delete", cancel: "Cancel",
  delAsk: "Delete this note? It can't be restored.",
},
};

})();
