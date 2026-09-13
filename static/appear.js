/* ============================================================
   Поява розділів: варіант «Б» з пробника design/anim.

   Коли відкривається розділ, вікно чи панель, його блоки не з'являються
   разом, а по черзі: спливають на 18px з легким масштабом. Усередині
   блоків рядки й клітинки ідуть своєю чергою, плашки результату в
   календарі вискакують після своєї клітинки, лінія еквіті малюється
   зліва направо. Числа й далі рахує Ticker (ui.js).

   Нічого в розмітці не міняємо: модуль знаходить блоки за класами, які
   вже є, і вішає анімацію з затримкою. Після кінця анімації клас і
   затримку знімаємо — інакше hover-ефекти (translate у картках) билися б
   із transform анімації.

   Коли грає: зміна розділу (не перемальовування після правки угоди —
   інакше сторінка моргала б на кожен клік), відкриття вікна (#modalBox)
   і будь-якої панелі (Sheet/Drawer). Не грає при prefers-reduced-motion.
   ============================================================ */
(function(){

const STEP  = 85;    /* між сусідніми блоками */
const ISTEP = 60;    /* між рядками/клітинками всередині блоку */
const CAP   = 14;    /* далі цієї черги не чекаємо: довгий список їде разом */
const ICAP  = 24;

/* Блоки — те, що спливає цілком. Порядок черги — порядок у документі. */
const BLOCKS = [
  ".vhead", ".filters", ".dimsel",
  ".ovw .shell", ".ovw .rail", ".card", ".dv-card", ".dv-head",
  ".nw-warn", ".nw-days", ".nw-filters", ".nw-search", ".nw-list",
  ".st-sec", ".fcard", ".hb", ".th-grp > .nt-sub", ".th-grid", ".th-collab", ".th-custom",
  ".acc-card", ".acc-head", ".ts-sec", ".ts-card", ".sh-body > *", ".m-head", ".m-foot",
  ".as-msg", ".as-empty",
].join(",");

/* Елементи всередині блоку, що йдуть своєю чергою після нього */
const ITEMS = [
  ".stats .st", ".week .day", ".cal .day", ".dtrade", ".tlist tr", "table tbody tr",
  ".nw-ev", ".th-card", ".kpi", ".bw .cell", ".hb-opt", ".chip", ".dv-lv .r", ".dv-sc .s",
  ".arow", ".dims .pill", ".lk-col", ".lk-row",
].join(",");

/* Смужки (win rate в аналітиці, розрізи в обзорі) виростають від нуля
   після свого рядка */
const BARS = ".arow .wrbar .track i, .ovw .rail .bar .ln i";

/* Плашки результату в клітинках календаря — після своєї клітинки */
const MARKS = ".cal .day .mk, .week .day .mk";

const still = () => window.matchMedia
  && matchMedia("(prefers-reduced-motion: reduce)").matches;

function set(el, cls, delay){
  if (!el || el.classList.contains("ap") || el.classList.contains("ap-pop")
      || el.classList.contains("ap-draw") || el.classList.contains("ap-fade")) return;
  el.style.animationDelay = Math.round(delay) + "ms";
  el.classList.add(cls);
  el.addEventListener("animationend", function done(){
    el.classList.remove(cls);
    el.style.animationDelay = "";
    el.removeEventListener("animationend", done);
  });
}

function run(root){
  if (!root || still() || document.hidden) return;

  const blocks = [...root.querySelectorAll(BLOCKS)]
    /* вкладені блоки (картка в картці) не рахуємо двічі */
    .filter(b => !b.parentElement.closest(BLOCKS) || !root.contains(b.parentElement.closest(BLOCKS)));
  const delayOf = new Map();
  blocks.forEach((b, i) => {
    const d = Math.min(i, CAP) * STEP;
    delayOf.set(b, d);
    set(b, "ap", d);
  });

  /* рядки й клітинки: черга всередині свого блоку */
  const perBlock = new Map();
  root.querySelectorAll(ITEMS).forEach(el => {
    const b = el.closest(BLOCKS);
    const base = (b && delayOf.has(b)) ? delayOf.get(b) + 90 : 0;
    const key = b || root;
    const k = perBlock.get(key) || 0;
    perBlock.set(key, k + 1);
    /* Довгий список (журнал на сотню рядків) не анімуємо цілком: за
       межею черги рядки просто з'являються разом зі своїм блоком. Інакше
       сотня одночасних анімацій — і швидке перемикання розділів лагає. */
    if (k >= ICAP) return;
    const d = base + k * ISTEP;
    el.__apDelay = d;
    set(el, "ap", d);
  });

  /* плашки в клітинках — після клітинки, одна за одною */
  const perCell = new Map();
  root.querySelectorAll(MARKS).forEach(mk => {
    const cell = mk.closest(".day");
    const k = perCell.get(cell) || 0;
    perCell.set(cell, k + 1);
    if (!cell || cell.__apDelay == null) return;      /* клітинка поза чергою — плашки теж */
    set(mk, "ap-pop", cell.__apDelay + 120 + k * 70);
  });

  /* смужки виростають після свого рядка */
  root.querySelectorAll(BARS).forEach(bar => {
    const row = bar.closest(ITEMS) || bar.closest(BLOCKS);
    const base = row ? (row.__apDelay != null ? row.__apDelay : delayOf.get(row)) : null;
    if (base == null) return;                          /* рядок поза чергою — смужка теж */
    set(bar, "ap-bar", base + 220);
  });

  /* лінія еквіті малюється, заливка під нею проявляється слідом */
  root.querySelectorAll(".eqline, .plline path[stroke]").forEach(p => {
    const b = p.closest(BLOCKS);
    const base = (b && delayOf.has(b)) ? delayOf.get(b) + 150 : 150;
    p.setAttribute("pathLength", "1");
    set(p, "ap-draw", base);
  });
  root.querySelectorAll(".eqarea, .plline path[fill^='url'], .eqwrap .dot, .eqwrap .eqval").forEach(p => {
    const b = p.closest(BLOCKS);
    const base = (b && delayOf.has(b)) ? delayOf.get(b) + 150 : 150;
    set(p, "ap-fade", base + 700);
  });

  /* Страховка: у прихованого елемента (смужка, згорнута на телефоні)
     анімація не грає й animationend не приходить — клас лишався б
     назавжди, а з ним і opacity:0. Після найдовшої можливої черги
     знімаємо все, що не зняли самі. */
  setTimeout(() => {
    root.querySelectorAll(".ap, .ap-pop, .ap-draw, .ap-fade, .ap-bar").forEach(el => {
      el.classList.remove("ap", "ap-pop", "ap-draw", "ap-fade", "ap-bar");
      el.style.animationDelay = "";
    });
  }, CAP * STEP + ICAP * ISTEP + 2600);
}

/* ---- розділи: граємо лише при зміні розділу і на першому показі ---- */
let lastView = null;
const renderOrig = window.render;
if (typeof renderOrig === "function"){
  window.render = function(){
    const r = renderOrig.apply(this, arguments);
    const v = document.documentElement.getAttribute("data-page");
    if (v !== lastView){
      lastView = v;
      run(document.getElementById("main"));
    }
    return r;
  };
}

/* ---- вікна: після того, як motion.js показав саме вікно ---- */
const openOrig = window.openModal;
if (typeof openOrig === "function"){
  window.openModal = function(html){
    const r = openOrig.apply(this, arguments);
    if (r !== false) run(document.getElementById("modalBox"));
    return r;
  };
}

/* ---- панелі (Sheet/Drawer): їх будує ui.js, зовні не підмінити — тому
   дивимось, що додалось у body. Вміст помічника перемальовується при
   кожній репліці, але ми бачимо лише появу самої панелі, тож старі
   репліки не стрибають щоразу. ---- */
new MutationObserver(muts => {
  muts.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType !== 1 || !n.classList.contains("pnl-wrap")) return;
    const box = n.querySelector(".pnl");
    /* даємо панелі дописати свій вміст (insertAdjacentHTML іде після build).
       setTimeout, не rAF: у прихованій вкладці rAF не приходить узагалі */
    setTimeout(() => run(box), 0);
  }));
}).observe(document.body, {childList: true});

window.Appear = {run};

})();
