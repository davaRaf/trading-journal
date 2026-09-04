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

function inner(){
  return '<p class="pp-lead">' + esc(T.bkLead) + "</p>"
    + '<a class="btn bk-get" href="/api/export" download>' + esc(T.bkGet) + "</a>"
    + note();
}

/* Порожній рядок означає «показувати нема чого»: чужий журнал. */
function section(){
  return inPub() ? "" : inner();
}

function wire(){}                    /* посилання нічого не потребує */

window.__backup = {load: load, section: section, wire: wire};

})();
