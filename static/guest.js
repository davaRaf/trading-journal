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

/* Значки сервісів — ті самі, що на сторінці входу: людина має побачити
   знайоме вікно, а не щось нове. */
const ICONS = {
  google: '<svg viewBox="0 0 18 18" aria-hidden="true"><path fill="#4285F4" d="M17.6 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.33-1.58-5.04-3.71H.94v2.33A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.96 10.71a5.4 5.4 0 0 1 0-3.42V4.96H.94a9 9 0 0 0 0 8.08l3.02-2.33z"/><path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .94 4.96l3.02 2.33C4.67 5.16 6.66 3.58 9 3.58z"/></svg>',
  discord: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#5865F2" d="M20.317 4.369a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.32.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.009c.12.099.246.198.373.292a.077.077 0 0 1-.006.127c-.598.35-1.22.645-1.873.891a.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.331c-1.183 0-2.157-1.086-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.211 0 2.176 1.096 2.157 2.42 0 1.332-.955 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.086-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.211 0 2.176 1.096 2.157 2.42 0 1.332-.946 2.418-2.157 2.418z"/></svg>',
};

/* Вікно «увійдіть». reason — що саме людина намагалась зробити: так
   зрозуміліше, чому її спинили. Виглядає як карта зі сторінки входу:
   той самий знак, ті самі кнопки сервісів, той самий роздільник. */
function gate(reason){
  if (typeof openModal !== "function") { location.href = "/login"; return; }
  const socs = (window.__gsProviders || []).map(p =>
    '<a class="gsoc" href="/auth/' + p.k + '">' + (ICONS[p.k] || "")
    + '<span>' + esc(T.gsWith.replace("%s", p.name)) + '</span></a>').join("");
  openModal(
    '<div class="gate-w">'
    + '<div class="gate-brand">'
    +   '<svg class="logo" aria-hidden="true"><use href="#logomark"/></svg>'
    +   '<span class="nm">Stats<i>AI</i></span>'
    +   '<span class="sub">' + esc(T.gsLabel) + '</span>'
    + '</div>'
    + '<h3>' + esc(reason || T.gsGateTitle) + '</h3>'
    + '<p>' + esc(T.gsGateText) + '</p>'
    + (socs ? '<div class="gate-socs">' + socs + '</div><div class="gate-or"><span>'
        + esc(T.gsOr) + '</span></div>' : '')
    + '<a class="gate-go" href="/login#signup">' + esc(T.gsSignupMail) + '</a>'
    + '<div class="gate-alt">' + esc(T.gsHaveAcc) + ' '
    +   '<a href="/login">' + esc(T.gsLogin) + '</a></div>'
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
