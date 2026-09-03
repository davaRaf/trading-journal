/* ============================================================
   Однакове під різними іменами.

   Журнал буває зібраний з кількох джерел: два журнали Notion за
   різні місяці, файл з таблиці, угоди руками. У кожному свої
   звички — десь «US100», десь «NAS 100». Для статистики це різні
   інструменти: винрейт і профіт-фактор діляться навпіл, а в списку
   просто два рядки замість одного.

   Тут ми показуємо знайдені пари й даємо звести їх в одне. Самі
   нічого не міняємо: що з чим одне — вирішує людина.
   ============================================================ */
(function(){

let groups = [];
let note = "";        // що зробили останнім — рядком над списком

/* Скільки угод: «2 угоди», а не «2 угод». Рахунок слів у app.js. */
function word(n){
  return typeof ovWord === "function" ? ovWord(n) : T.wordTradeMany;
}

function fieldName(f){
  return {pair: T.fPair, session: T.fSession,
          entry_model: T.fEntryModel, setup: T.fSetup}[f] || f;
}

/* Питаємо сервер. Мовчазно: якщо не вийшло — просто нічого не пропонуємо. */
async function look(){
  try{
    const r = await api("GET", "/api/tidy");
    groups = r.groups || [];
  }catch(e){ groups = []; }
  return groups;
}

/* Блок-запрошення для чужих вікон (перенесення з Notion). Порожній рядок,
   поки зводити нічого — тоді про це й не згадуємо. */
function hint(){
  if (!groups.length) return "";
  return '<div class="nt-safe"><p>' + T.tdFound + " <b>" + groups.length + "</b></p>"
    + '<button class="btn" onclick="Tidy.open()">' + T.tdOpenBtn + "</button></div>";
}

function body(){
  if (!groups.length){
    return '<div class="nt-empty">' + T.tdNothing + "</div>";
  }
  return groups.map((g, i) =>
    '<div class="td-g">'
    + '<div class="nt-sub">' + esc(fieldName(g.field)) + "</div>"
    + '<div class="td-vars">'
    + g.variants.map(v =>
        '<label class="td-v' + (v.value === g.best ? " on" : "") + '">'
        + '<input type="radio" name="td' + i + '" value="' + esc(v.value) + '"'
        + (v.value === g.best ? " checked" : "")
        + ' onchange="Tidy.pick(this)">'
        + "<b>" + esc(v.value) + "</b>"
        + "<span>" + v.count + " " + word(v.count) + "</span></label>").join("")
    + "</div>"
    + '<button class="btn primary td-go" onclick="Tidy.merge(' + i + ')">'
    + T.tdMergeBtn + "</button></div>").join("");
}

function paint(){
  const box = document.getElementById("modalBox");
  if (!box) return;
  const b = box.querySelector(".m-body");
  if (b) b.innerHTML = '<div class="nt">'
    + (note ? '<div class="nt-ok">' + esc(note) + "</div>" : "")
    + '<p class="nt-lead">' + T.tdLead + "</p>"
    + body()
    + (groups.length && typeof exportData === "function"
        ? '<div class="nt-safe"><p>' + T.tdBackupHint + "</p>"
          + '<button class="btn" onclick="exportData()">' + T.ntSaveBackup + "</button></div>"
        : "")
    + "</div>";
}

function open(){
  if (window.Guest && Guest.block(T.gsGateConnect)) return;
  note = "";
  openModal(
    '<div class="m-head"><h2>' + T.tdTitle + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + T.mrClose + '">×</button></div>'
    + '<div class="m-body"></div>'
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn primary" onclick="closeModal()">' + T.mrClose + "</button></div>");
  paint();
  look().then(paint);      // список міг застаріти, поки вікно було закрите
}

/* Зводимо групу в одне написання. Дія гуртова й без відкату, тому питаємо
   прямо: що, на що і в скількох угодах. */
async function merge(i){
  const g = groups[i];
  if (!g) return;
  const box = document.getElementById("modalBox");
  const sel = box && box.querySelector('input[name="td' + i + '"]:checked');
  const to = sel ? sel.value : g.best;
  const from = g.variants.filter(v => v.value !== to);
  if (!from.length) return;
  const n = from.reduce((s, v) => s + v.count, 0);

  const ask = T.tdConfirm
    .replace("{from}", from.map(v => "«" + v.value + "»").join(", "))
    .replace("{to}", "«" + to + "»")
    .replace("{n}", n + " " + word(n));
  if (!await Ask.yes(ask, {ok: T.askYes, cancel: T.askNo})) return;

  let r;
  try{
    r = await api("POST", "/api/tidy/apply",
      {field: g.field, from: from.map(v => v.value), to});
  }catch(e){
    note = T.tdFailed + " " + e.message;
    return paint();
  }
  note = T.tdDone + " " + (r.changed || 0) + ".";
  try{ await reload(); render(); }catch(e){}
  await look();
  paint();
}

window.Tidy = {
  open, merge, look, hint,
  found: () => groups.length,
  /* підсвічуємо обране написання: радіокнопка сама по собі помітна погано */
  pick(input){
    const wrap = input.closest(".td-vars");
    if (!wrap) return;
    wrap.querySelectorAll(".td-v").forEach(l => l.classList.remove("on"));
    input.closest(".td-v").classList.add("on");
  },
};

})();
