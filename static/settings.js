/* ============================================================
   Вікно «Налаштування»: мова інтерфейсу й відкритий журнал.

   Раніше це були два різні місця в бічній панелі — три кнопки мови
   внизу й окрема кнопка відкритого журналу. Розділ «Підключення»
   лишився в панелі, де й був: за ним ходять частіше, ніж за
   настройками, і ховати його за зайвим кліком нема сенсу.

   Свого стану вікно не тримає:
   — мову перемикає той самий applyLang(), після чого вікно
     перемальовується новою мовою, не закриваючись;
   — розділ відкритого журналу цілком з static/profile.js.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* У чужому журналі (/u/<нік>) особисті розділи ховаємо: там людина
   дивиться не своє, і будь-який запис однаково заблокований. Лишається
   мова — нею читають сторінку. */
const inPub = () => !!(window.Pub && window.Pub.on);

function langs(){
  const names = {uk: "Українська", ru: "Русский", en: "English"};
  return '<div class="st-langs" role="group" aria-label="' + esc(T.stLang) + '">'
    + ["uk", "ru", "en"].map(c =>
        '<button type="button" class="' + (c === LANG ? "on" : "") + '"'
        + ' aria-pressed="' + (c === LANG) + '"'
        + ' onclick="__settings.lang(&quot;' + c + '&quot;)">' + names[c] + "</button>").join("")
    + "</div>";
}

function sec(title, guts, cls){
  return '<section class="st-sec' + (cls ? " " + cls : "") + '">'
    + '<h3 class="st-h">' + esc(title) + "</h3>" + guts + "</section>";
}

function body(){
  let h = sec(T.stLang, langs());
  const pp = (!inPub() && window.__profile) ? __profile.section() : "";
  if (pp) h += sec(T.ppTitle, pp, "pp");
  const pw = (!inPub() && window.__pwd) ? __pwd.section() : "";
  if (pw) h += sec(T.pwTitle, pw, "pw");
  const bk = (!inPub() && window.__backup) ? __backup.section() : "";
  if (bk) h += sec(T.bkTitle, bk, "bk");
  /* службова статистика — розділ є лише в тих, кому сервер її віддав */
  const sr = (!inPub() && window.__sources) ? __sources.section() : "";
  if (sr) h += sec(T.srTitle, sr, "sr");
  return '<div class="m-body st">' + h + "</div>";
}

function draw(){
  openModal(
    '<div class="m-head"><h2>' + esc(T.stTitle) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(T.mrClose) + '">×</button></div>'
    + body()
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(T.mrClose) + "</button></div>");
  if (!inPub() && window.__profile && __profile.section()) __profile.wire();
  if (!inPub() && window.__pwd && __pwd.section()) __pwd.wire();
}

async function open(){
  /* Обидва розділи читають своє паралельно: чекати їх по черзі — це
     зайва пауза перед відкриттям вікна. */
  if (!inPub()) await Promise.all([
    window.__profile ? __profile.load() : null,
    window.__pwd ? __pwd.load() : null,
    window.__backup ? __backup.load() : null,
    window.__sources ? __sources.load() : null,
  ]);
  draw();
}

/* Мову міняє той самий applyLang, що й раніше: він перемальовує сам
   застосунок. Вікно перемальовуємо слідом, щоб і воно стало новою
   мовою — і при цьому не закрилось. */
function lang(code){
  if (code === LANG) return;
  applyLang(code);
  draw();
}

window.__settings = {open: open, lang: lang, redraw: draw};

})();
