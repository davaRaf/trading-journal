/* ============================================================
   Поява й зникання вікон — один раз на весь сайт.

   openModal() і closeModal() з app.js просто знімають і ставлять hidden.
   Раніше плавність собі дописувало кожне вікно окремо (так робив
   settings.js), і виходило, що налаштування згортаються м'яко, а картка
   новини чи форма угоди — миттєво. Тепер підміняємо обидві функції один
   раз, і будь-яке вікно, зокрема чуже й майбутнє, отримує рух даром.

   Класи вішаємо на .modal, а не на картку: під час зникання елемент має
   ще бути видимим, тому hidden ставимо після кінця анімації.
   ============================================================ */
(function(){

const OUT = 120;                     /* має збігатися з --m-out у motion.css */
let closing = 0;                     /* таймер згортання, 0 — не згортаємось */

const still = () => window.matchMedia
  && matchMedia("(prefers-reduced-motion: reduce)").matches;

function play(el, cls){
  if (!el) return;
  el.classList.remove("m-in", "m-out");
  if (still()) return;
  /* перезапускаємо анімацію: без цього другий показ поспіль її не грає */
  void el.offsetWidth;
  el.classList.add(cls);
}

/* ---- вікна ---- */

const openOrig = window.openModal;
const closeOrig = window.closeModal;

if (typeof openOrig === "function"){
  window.openModal = function(html){
    const modal = document.getElementById("modal");
    /* Вікно вже відкрите — значить, усередині просто перемальовують вміст
       (наприклад, налаштування після зміни мови). Тоді нічого не граємо:
       картка не повинна смикатись від кожної правки. */
    const fresh = !modal || modal.hidden;
    if (closing){ clearTimeout(closing); closing = 0; }
    if (modal) modal.classList.remove("m-out");
    const out = openOrig.apply(this, arguments);
    if (fresh) play(modal, "m-in");
    return out;
  };
}

if (typeof closeOrig === "function"){
  window.closeModal = function(){
    /* Замкнене вікно (опитування після входу) не закривається взагалі —
       перевіряємо до анімації, інакше воно зникне з очей, лишившись відкритим. */
    if (typeof modalLocked !== "undefined" && modalLocked) return;
    const modal = document.getElementById("modal");
    if (!modal || modal.hidden || still() || closing) return closeOrig.apply(this, arguments);
    const args = arguments, self = this;
    play(modal, "m-out");
    closing = setTimeout(() => {
      closing = 0;
      modal.classList.remove("m-out");
      closeOrig.apply(self, args);
    }, OUT);
  };
}

/* ---- перегляд картинки ---- */

const lightOpen = window.openLightbox;
const lightClose = window.closeLightbox;
let lightTimer = 0;

if (typeof lightOpen === "function"){
  window.openLightbox = function(src){
    const box = document.getElementById("lightbox");
    if (lightTimer){ clearTimeout(lightTimer); lightTimer = 0; }
    if (box) box.classList.remove("m-out");
    const out = lightOpen.apply(this, arguments);
    play(box, "m-in");
    return out;
  };
}

if (typeof lightClose === "function"){
  window.closeLightbox = function(){
    const box = document.getElementById("lightbox");
    if (!box || box.hidden || still() || lightTimer) return lightClose.apply(this, arguments);
    const args = arguments, self = this;
    play(box, "m-out");
    lightTimer = setTimeout(() => {
      lightTimer = 0;
      box.classList.remove("m-out");
      lightClose.apply(self, args);
    }, OUT);
  };
}

})();
