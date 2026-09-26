/* ============================================================
   Шторка вибору замість системного <select>.

   Системний список у вікні перенесення з Notion виглядав чужим: сіра
   рамка Windows, сірий фон, тип колонки одним шматком з її назвою.
   Тут той самий вибір, але в оформленні журналу: назва зліва, тип
   колонки монопростором справа, обране — зеленою галкою.

   Сам <select> лишається в розмітці й далі тримає значення: шторка
   тільки міняє йому selectedIndex і шле «change», тож увесь код навколо
   (notion.js) працює так, ніби нічого не сталося. Якщо цей файл не
   доїхав — сторінка лишається робочою зі звичайним списком.

   Список малюємо в <body>, а не поруч із кнопкою: вікно перенесення
   прокручується, і вкладений список обрізало б краєм. Через це його
   доводиться самому ставити на місце (place) і рухати за прокруткою.
   ============================================================ */
window.SelMenu = (function(){

const GAP = 6;        /* відстань від кнопки до шторки */
const EDGE = 12;      /* скільки лишаємо до краю екрана */
const MAXH = 300;     /* вище шторка не росте — далі прокрутка */

let cur = null;       /* відкрита шторка: {sel, box, btn, pop, i} */
let uid = 0;
let tick = 0;
let typed = "", typedAt = 0;

const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const CHEV = '<svg class="nsel-c" viewBox="0 0 24 24" aria-hidden="true">'
  + '<path d="M6 9.5l6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.7"'
  + ' stroke-linecap="round" stroke-linejoin="round"/></svg>';
const TICK = '<svg class="nsel-ok" viewBox="0 0 24 24" aria-hidden="true">'
  + '<path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.1"'
  + ' stroke-linecap="round" stroke-linejoin="round"/></svg>';

/* ---------- кнопка ---------- */

function drawBtn(st){
  const o = st.sel.options[st.sel.selectedIndex];
  st.btn.innerHTML = '<span class="nsel-v">' + esc(o ? o.textContent : "") + "</span>"
    + (o && o.dataset.type ? '<em class="nsel-t">' + esc(o.dataset.type) + "</em>" : "")
    + CHEV;
  /* «не переносити» — це порожнє значення: приглушуємо, щоб рядки,
     де щось обрано, читались першими */
  st.box.classList.toggle("empty", !st.sel.value);
}

function upgrade(root){
  const scope = root || document;
  scope.querySelectorAll("select.js-sel:not([data-nsel])").forEach(sel => {
    sel.setAttribute("data-nsel", "1");
    const box = document.createElement("div");
    box.className = "nsel";
    sel.parentNode.insertBefore(box, sel);
    box.appendChild(sel);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nsel-btn";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    box.appendChild(btn);

    /* системний список лишається як сховище значення, але з дороги:
       по Tab до нього не потрапиш, зчитувач екрана читає кнопку */
    sel.tabIndex = -1;
    sel.setAttribute("aria-hidden", "true");

    const st = {sel, box, btn, pop: null, i: -1};
    btn.__nsel = st;
    drawBtn(st);
    btn.addEventListener("click", () => (cur === st ? close() : open(st)));
    btn.addEventListener("keydown", e => onKey(e, st));
  });
}

/* ---------- шторка ---------- */

function open(st, from){
  close();
  const id = "nsel" + (++uid);
  const pop = document.createElement("div");
  pop.className = "nsel-pop";
  pop.id = id;
  pop.setAttribute("role", "listbox");
  pop.innerHTML = Array.from(st.sel.options).map((o, i) =>
    '<div class="nsel-opt' + (o.value ? "" : " none")
    + (i === st.sel.selectedIndex ? " on" : "") + '" role="option" id="' + id + "-" + i + '"'
    + ' data-i="' + i + '" aria-selected="' + (i === st.sel.selectedIndex) + '">'
    + "<span>" + esc(o.textContent) + "</span>"
    + (o.dataset.type ? "<em>" + esc(o.dataset.type) + "</em>" : "")
    + TICK + "</div>").join("");
  document.body.appendChild(pop);
  /* Стаємо рівно на шар вище того вікна, з якого нас відкрили. Спільний
     лічильник nextTop() тут не годиться: він росте з кожним відкриттям,
     а шторку смикають десятки разів за один перехід. */
  const host = st.btn.closest(".modal, .pnl-wrap");
  const z = host ? parseInt(getComputedStyle(host).zIndex, 10) : 0;
  pop.style.zIndex = (z > 0 ? z : 75) + 1;

  st.pop = pop;
  st.id = id;
  st.i = st.sel.selectedIndex >= 0 ? st.sel.selectedIndex
       : (from === -1 ? st.sel.options.length - 1 : 0);
  cur = st;
  st.box.classList.add("open");
  st.btn.setAttribute("aria-expanded", "true");
  st.btn.setAttribute("aria-controls", id);

  pop.addEventListener("mousedown", e => e.preventDefault());   /* не крадемо фокус у кнопки */
  pop.addEventListener("click", e => {
    const o = e.target.closest(".nsel-opt");
    if (o) pick(+o.dataset.i);
  });
  pop.addEventListener("pointerover", e => {
    const o = e.target.closest(".nsel-opt");
    if (o) mark(+o.dataset.i, false);
  });

  place();
  mark(st.i, true);
}

function place(){
  if (!cur || !cur.pop) return;
  const pop = cur.pop, r = cur.btn.getBoundingClientRect();
  /* кнопки вже немає на сторінці (вікно перемалювали) — шторці теж нема чого тут робити */
  if (!cur.btn.isConnected) return close();

  pop.style.minWidth = r.width + "px";
  const below = innerHeight - r.bottom - EDGE;
  const above = r.top - EDGE;
  /* знизу не вміщається, а зверху місця більше — розкриваємо вгору */
  const up = below < Math.min(pop.scrollHeight + 2, MAXH) && above > below;
  pop.classList.toggle("up", up);
  pop.style.maxHeight = Math.max(150, Math.min(MAXH, up ? above : below)) + "px";

  const h = pop.offsetHeight, w = pop.offsetWidth;
  pop.style.top = Math.round(up ? Math.max(EDGE, r.top - h - GAP) : r.bottom + GAP) + "px";
  pop.style.left = Math.round(Math.max(EDGE, Math.min(r.left, innerWidth - w - EDGE))) + "px";
}

function close(){
  if (!cur) return;
  const st = cur, pop = st.pop;
  cur = null;
  st.pop = null;
  st.box.classList.remove("open");
  st.btn.setAttribute("aria-expanded", "false");
  st.btn.removeAttribute("aria-activedescendant");
  if (!pop) return;
  /* зникає швидше, ніж з'явилась — так вікно здається спритнішим */
  pop.classList.add("out");
  const gone = () => pop.remove();
  pop.addEventListener("animationend", gone, {once: true});
  setTimeout(gone, 220);            /* якщо рух вимкнено — прибираємо самі */
}

/* ---------- вибір ---------- */

function mark(i, scroll){
  if (!cur || !cur.pop) return;
  const opts = cur.pop.children;
  if (i < 0 || i >= opts.length) return;
  cur.i = i;
  for (let k = 0; k < opts.length; k++) opts[k].classList.toggle("cur", k === i);
  cur.btn.setAttribute("aria-activedescendant", cur.id + "-" + i);
  if (scroll) opts[i].scrollIntoView({block: "nearest"});
}

function move(d){
  if (!cur) return;
  const n = cur.sel.options.length;
  mark((cur.i + d + n) % n, true);
}

function pick(i){
  if (!cur) return;
  const st = cur;
  st.sel.selectedIndex = i;
  st.sel.dispatchEvent(new Event("change", {bubbles: true}));
  close();
  drawBtn(st);
  st.btn.focus();
}

/* Набір з клавіатури: у журналі буває два десятки колонок, і гортати
   їх стрілками довго. Літери за півсекунди складаються в одне слово. */
function jump(ch){
  const now = Date.now();
  typed = (now - typedAt < 600 ? typed : "") + ch.toLowerCase();
  typedAt = now;
  const opts = Array.from(cur.sel.options);
  const hit = opts.findIndex(o => (o.textContent || "").toLowerCase().startsWith(typed));
  if (hit >= 0) mark(hit, true);
}

function onKey(e, st){
  const on = cur === st;
  if (e.key === "Escape"){
    if (!on) return;
    /* інакше Escape дійшов би до app.js і закрив усе вікно перенесення */
    e.preventDefault(); e.stopPropagation(); close(); return;
  }
  if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp"){
    e.preventDefault();
    if (!on) return open(st, e.key === "ArrowUp" ? -1 : 1);
    if (e.key === "Enter" || e.key === " ") return pick(st.i);
    return move(e.key === "ArrowDown" ? 1 : -1);
  }
  if (!on) return;
  if (e.key === "Home"){ e.preventDefault(); return mark(0, true); }
  if (e.key === "End"){ e.preventDefault(); return mark(st.sel.options.length - 1, true); }
  if (e.key === "Tab") return close();
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey){ e.preventDefault(); jump(e.key); }
}

/* ---------- спільне ---------- */

document.addEventListener("pointerdown", e => {
  if (!cur) return;
  if (e.target.closest(".nsel-pop") || e.target.closest(".nsel-btn")) return;
  close();
});
/* Вікно перенесення прокручується разом зі сторінкою, тож шторку ведемо
   за кнопкою, а не закриваємо: інакше вибір губився б від дотику до колеса. */
addEventListener("scroll", () => {
  if (!cur || tick) return;
  tick = requestAnimationFrame(() => { tick = 0; place(); });
}, true);
addEventListener("resize", () => { if (cur) place(); });

return {upgrade, close, closeAll: close};

})();
