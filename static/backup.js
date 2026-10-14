/* ============================================================
   Копія журналу: розділ у вікні «Налаштування».

   Дві речі в одному місці. Перша — кнопка «Завантажити журнал»:
   один файл з угодами, розборами днів і стратегією, який лягає до
   людини на диск і вже не залежить від нас. Друга — рядок про
   щоденний зліпок: він робиться сам (backup.py), і людині корисно
   бачити, що він справді робиться, а не просто обіцяний.

   Скачує звичайне посилання, а не fetch: сервер віддає файл із
   Content-Disposition, і браузер сам питає, куди його класти —
   без проміжного blob і без пам'яті під весь журнал.

   Влаштований як profile.js: load() читає стан, section() дає
   розмітку, wire() чіпляє події вже після вставки.
   ============================================================ */
(function(){

let have = null;                    /* перелік зліпків або null, якщо не читали */

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const inPub = () => !!(window.Pub && window.Pub.on);

async function load(){
  if (inPub()){ have = null; return null; }
  try{ have = (await api("GET", "/api/backups")).backups || []; }
  catch(e){ have = null; }           /* не відповіло — просто не показуємо рядок */
  return have;
}

/* «4 вер.» — коротко, бо це підпис, а не дата в документі. */
function day(iso){
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  const loc = {uk: "uk-UA", ru: "ru-RU", en: "en-US"}[LANG] || "uk-UA";
  return d.toLocaleDateString(loc, {day: "numeric", month: "short"});
}

function word(n){
  return typeof ovWord === "function" ? ovWord(n) : T.wordTradeMany;
}

function note(){
  if (!have) return "";
  if (!have.length) return '<p class="bk-note">' + esc(T.bkNone) + "</p>";
  const last = have[0];
  return '<p class="bk-note">' + esc(T.bkLast) + " <b>" + esc(day(last.date)) + "</b>"
    + " · " + last.trades + " " + esc(word(last.trades))
    + '<span class="bk-kept">' + esc(T.bkKept.replace("%d", have.length)) + "</span></p>";
}

/* Адреса вивантаження. Без параметрів — те саме, що було: весь журнал
   одним JSON. `kind` звужує до режиму, `run` — до одного прогону, і
   порожній рядок у ньому означає «Без журналу», а не «без звуження». */
function url(fmt, kind, run){
  const q = [];
  if (fmt === "csv") q.push("fmt=csv");
  if (kind) q.push("kind=" + kind);
  if (run !== null && run !== undefined) q.push("run=" + encodeURIComponent(run));
  return "/api/export" + (q.length ? "?" + q.join("&") : "");
}

function get(href, text, main){
  return '<a class="btn' + (main ? " primary" : "") + ' bk-get" href="' + href
    + '" download>' + esc(text) + "</a>";
}

/* Чи стоїть людина зараз у бектесті. Питаємо в app.js, а не вгадуємо:
   там же враховано і демо, і чужий журнал за посиланням. */
function onBt(){
  return typeof btOn === "function" && btOn();
}

/* Угоди бектесту — не той самий журнал, і забирати їх разом зі справжніми
   доводилось тільки тому, що іншого способу не було. Поки відкритий
   бектест, поруч стоїть вивантаження самого прогону. */
function btPart(){
  if (!onBt()) return "";
  const j = window.__btj && __btj.shown ? __btj.shown() : null;
  let out = '<div class="bk-bt"><h4 class="bk-sub">' + esc(T.bkBtTitle) + "</h4>"
    + '<p class="bk-note">' + esc(T.bkBtLead) + "</p>";
  if (j){
    const name = j.blank ? "" : String(j.name || "");
    out += '<p class="bk-note">' + esc(T.bkBtOpen) + " <b>"
      + esc(j.blank ? T.bkBtBlank : name) + "</b></p>"
      + '<div class="bk-row">'
      + get(url("", "bt", name), T.bkBtRun, true)
      + get(url("csv", "bt", name), T.bkBtRun + " · CSV")
      + "</div>";
  }
  out += '<div class="bk-row">'
    + get(url("", "bt"), T.bkBtAll)
    + get(url("csv", "bt"), T.bkBtAll + " · CSV")
    + "</div></div>";
  return out;
}

function inner(){
  return '<p class="pp-lead">' + esc(T.bkLead) + "</p>"
    + '<div class="bk-row">'
    + get(url(""), T.bkGet, true)
    + get(url("csv"), T.bkCsv)
    + "</div>"
    + note()
    + btPart();
}

/* Порожній рядок означає «показувати нема чого»: чужий журнал. */
function section(){
  return inPub() ? "" : inner();
}

function wire(){}                    /* посилання нічого не потребує */

window.__backup = {load: load, section: section, wire: wire};

})();
