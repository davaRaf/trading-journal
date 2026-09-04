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

let closing = false, closeTimer = 0;   /* стан анімації закриття */

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
  return '<div class="m-body st">' + h + "</div>";
}

function draw(){
  /* Якщо вікно відкрили просто під час анімації закриття — скасовуємо її,
     інакше воно з'явилось би вже невидимим. */
  if (closeTimer){ clearTimeout(closeTimer); closeTimer = 0; closing = false; }
  const modal = document.getElementById("modal");
  if (modal) modal.classList.remove("st-out");
  openModal(
    '<div class="m-head"><h2>' + esc(T.stTitle) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(T.mrClose) + '">×</button></div>'
    + body()
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(T.mrClose) + "</button></div>");
  if (!inPub() && window.__profile && __profile.section()) __profile.wire();
}

async function open(){
  if (!inPub() && window.__profile) await __profile.load();
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

/* Закриття з анімацією. Вікно закривають з чотирьох місць — хрестик,
   кнопка внизу, Esc і клік по підкладці, — і всі вони кличуть той самий
   closeModal(). Тому підміняємо його, а не вішаємо обробники: чужі вікна
   проходять далі без змін, наше спершу згортається.
   Так само, як notion.js свого часу підмінив openImport. */
const origClose = window.closeModal;

window.closeModal = function(){
  const modal = document.getElementById("modal");
  const box = document.getElementById("modalBox");
  const mine = !!(box && box.querySelector(".m-body.st"));
  const still = window.matchMedia
    && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!mine || !modal || modal.hidden || still || closing) return origClose();
  closing = true;
  modal.classList.add("st-out");
  closeTimer = setTimeout(() => {
    modal.classList.remove("st-out");
    closing = false;
    closeTimer = 0;
    origClose();
  }, 150);
};

window.__settings = {open: open, lang: lang, redraw: draw};

})();
