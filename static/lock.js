/* ============================================================
   Замок на акаунт.

   Ставить його власник руками з /admin і знімає так само руками.
   Сама людина зробити з ним не може нічого: кнопки «закрити» тут
   немає навмисно, Escape не слухаємо, а шар повертається на місце,
   якщо його прибрати з консолі браузера.

   Тримає замок однак не цей файл, а сервер: під замком кожен запит
   до /api/ вертається з 403 code=locked (app.py: _locked_out). Шар —
   це те, що людина бачить, а не те, що її зупиняє. Тому прибрати
   його вручну нічого не дає: журнал під ним однаково мертвий.

   Текст приходить із сервера (users.lock_note): слова до кожного
   замка свої, і зашивати їх тут не можна. Контакт, навпаки, зашитий —
   він у нас один і той самий, що й у support.js.
   ============================================================ */
(function(){

const TG = "danylo_mf";

let back = null, note = "", timer = 0;

function build(){
  const el = document.createElement("div");
  el.className = "lk-back";
  el.innerHTML =
    '<div class="lk-w" role="dialog" aria-modal="true">'
    + '<p class="lk-note"></p>'
    + '<div class="lk-c">'
    +   '<span class="lk-k">Telegram-контакт</span>'
    +   '<a class="lk-a" href="https://t.me/' + TG + '"'
    +      ' target="_blank" rel="noopener">@' + TG + '</a>'
    + '</div></div>';
  /* textContent, а не в розмітку рядком: текст приходить із бази, і
     складати з нього html означало б пустити туди будь-які теги. */
  el.querySelector(".lk-note").textContent = note;
  return el;
}

/* Шар на місці? Ні — ставимо назад. Прибрати його з консолі можна,
   але не надовго. */
function keep(){
  if (back && document.body.contains(back)) return;
  back = build();
  document.body.appendChild(back);
}

function show(text){
  if (text) note = text;
  if (!note) return;                 /* без слів замок не показуємо */
  keep();
  document.documentElement.classList.add("locked");
  if (window.ScrollLock) ScrollLock.on();
  if (!timer) timer = setInterval(keep, 1000);
}

window.Lock = {show: show, get on(){ return !!back; }};

})();
