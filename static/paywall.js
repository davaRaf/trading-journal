/* ============================================================
   Плашка відмови: безкоштовне скінчилось.

   Одна на всі місця — угода, перенесення, помічник. Сервер каже
   тільки привід (402 і reason), слова до нього лежать тут: інакше
   кожна точка складала б свій текст і вони розійшлися б.

   Лічильника «лишилось N із 20» тут немає й бути не може (рішення
   власника 22.09.2026). Людина дізнається про межу, коли в неї
   впреться, — і одразу бачить, що робити далі.

   Окремий шар, а не звичайне вікно: відмова приходить поверх уже
   відкритої форми угоди, і підмінити її вміст означало б стерти
   те, що людина щойно набрала.
   ============================================================ */
(function(){

/* Привід → заголовок і пояснення. Ключі ті самі, що в billing.py. */
const WHY = {
  trades_limit:  ["pwTradeT", "pwTradeX"],
  bt_limit:      ["pwBtT",    "pwBtX"],
  imports_limit: ["pwImpT",   "pwImpX"],
  import_window: ["pwImpT",   "pwWinX"],
  bt_notion_limit: ["pwBtLimT", "pwBtLimX"],
  ai_limit:      ["pwAiT",    "pwAiX"],
  ai_cap:        ["pwCapT",   "pwCapX"],
};

let back = null;

function close(){
  if (!back) return;
  back.remove();
  back = null;
  if (window.ScrollLock) ScrollLock.off();
  document.removeEventListener("keydown", onKey);
}

function onKey(e){
  if (e.key === "Escape"){ e.stopPropagation(); close(); }
}

function show(reason){
  const keys = WHY[reason] || WHY.trades_limit;
  /* ai_cap — не про гроші: у стелю впирається той, хто вже платить,
     і кликати його в тарифи безглуздо. */
  const sell = reason !== "ai_cap" && reason !== "bt_notion_limit";
  close();
  back = document.createElement("div");
  back.className = "pw-back";
  back.style.zIndex = window.nextTop ? nextTop() : 9000;
  back.innerHTML =
    '<div class="pw-w" role="dialog" aria-modal="true">'
    /* Логотипа й напису StatsAI тут немає (рішення власника 27.09.2026):
       людина вже в журналі, називати себе ще раз ні до чого — вікно має
       бути чисте, з одним заголовком і однією дією. */
    + '<h3>' + esc(T[keys[0]] || "") + '</h3>'
    + '<p>' + esc(T[keys[1]] || "") + '</p>'
    + (sell ? '<button type="button" class="pw-go">' + esc(T.pwPlans) + '</button>' : '')
    + '<button type="button" class="pw-later">' + esc(T.pwLater) + '</button>'
    + '</div>';
  back.addEventListener("click", e => { if (e.target === back) close(); });
  const go = back.querySelector(".pw-go");
  if (go) go.addEventListener("click", () => {
    close();
    if (window.__settings) __settings.open("subscription");
  });
  back.querySelector(".pw-later").addEventListener("click", close);
  document.body.appendChild(back);
  if (window.ScrollLock) ScrollLock.on();
  document.addEventListener("keydown", onKey);
  if (go) go.focus();
}

window.Paywall = {
  show: show,
  close: close,
  /* Місце виклику ловить помилку й мовчить: плашку вже показано.
     Позначка soft саме про це — «людині вже сказали». */
  soft: function(reason){
    show(reason);
    const e = new Error("need_sub");
    e.soft = true;
    return e;
  },
};

})();
