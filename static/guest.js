/* ============================================================
   Гість — людина, яка прийшла подивитись і ще не заводила акаунт.

   Найчастіше вона приходить із чужого посилання «поділитись»: побачила
   один день і натиснула «подивитись журнал». Раніше її одразу кидало на
   сторінку входу — вона не встигала зрозуміти, що їй пропонують, і
   йшла. Тепер вона потрапляє в сам журнал на демонстраційних даних.

   Дивитись можна все: розділи, календар, аналітику, ТС. Не можна лише
   писати — щойно гість намагається щось створити чи змінити, показуємо
   вікно «увійдіть». Тобто плата береться не за перегляд, а за запис.

   Демо-дані живуть у браузері (demo.js), на сервер нічого не йде.
   ============================================================ */
(function(){

let on = false;

/* Полоса зверху: гість має розуміти, що цифри не справжні, і бачити,
   куди йти по свій журнал. */
function bar(){
  const el = document.createElement("div");
  el.className = "gbar";
  el.innerHTML = '<b>' + esc(T.gsLabel) + '</b><span>' + esc(T.gsBarText) + '</span>'
    + '<span class="sp"></span>'
    + '<a class="lnk" href="/login">' + esc(T.gsLogin) + '</a>'
    + '<a class="go" href="/login#signup">' + esc(T.gsSignup) + '</a>';
  document.body.appendChild(el);
  document.body.classList.add("has-gbar");
}

/* У бічній панелі гостю нічого виходити — натомість ставимо вхід і
   реєстрацію. Раніше цих кнопок на сайті не було взагалі. */
function sidebar(){
  const foot = document.querySelector(".side-foot");
  const out = document.getElementById("logoutBtn");
  if (out) out.remove();
  if (!foot) return;
  const box = document.createElement("div");
  box.className = "gside";
  box.innerHTML = '<a class="btn primary" href="/login#signup">' + esc(T.gsSignup) + '</a>'
    + '<a class="btn" href="/login">' + esc(T.gsLogin) + '</a>';
  foot.insertBefore(box, foot.firstChild);
}

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"]/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

/* Вікно «увійдіть». reason — що саме людина намагалась зробити:
   так зрозуміліше, чому її спинили. */
function gate(reason){
  if (typeof openModal !== "function") { location.href = "/login"; return; }
  const socs = (window.__gsProviders || []).map(p =>
    '<a class="btn" href="/auth/' + p.k + '">' + esc(T.gsWith.replace("%s", p.name)) + '</a>').join("");
  openModal(
    '<div class="gate-w">'
    + '<div class="gate-mk"><svg width="18" height="18"><use href="#logomark"/></svg></div>'
    + '<h3>' + esc(reason || T.gsGateTitle) + '</h3>'
    + '<p>' + esc(T.gsGateText) + '</p>'
    + (socs ? '<div class="gate-socs">' + socs + '</div><div class="gate-or"><span>'
        + esc(T.gsOr) + '</span></div>' : '')
    + '<a class="btn primary wide" href="/login#signup">' + esc(T.gsSignupMail) + '</a>'
    + '<button type="button" class="gate-later" onclick="closeModal()">'
    + esc(T.gsLater) + '</button></div>');
}

/* Які кнопки входу показувати — питаємо в сервера, як і сторінка входу. */
async function providers(){
  const NAMES = {google: "Google", discord: "Discord", telegram: "Telegram"};
  try{
    const r = await fetch("/api/auth/providers");
    const d = await r.json();
    window.__gsProviders = Object.keys(d.providers || {})
      .filter(k => d.providers[k] && k !== "telegram")   // Telegram потребує свого віджета
      .map(k => ({k: k, name: NAMES[k] || k}));
  }catch(e){ window.__gsProviders = []; }
}

function start(){
  if (on) return;
  on = true;
  document.documentElement.setAttribute("data-guest", "1");
  bar();
  sidebar();
  providers();
}

window.Guest = {
  start: start,
  get on(){ return on; },
  /* Повертає true, якщо дію робити не можна — місце виклику просто
     виходить. Так одна перевірка закриває і кнопки, і запити. */
  block: function(reason){
    if (!on) return false;
    gate(reason);
    return true;
  },
};

})();
