/* ============================================================
   Мобільна оболонка: шапка зверху, вкладки знизу, шторка з меню.

   Нічого свого не малює — бере ті самі елементи, що вже стоять у
   бічній панелі (посилання розділів, калькулятор, підключення, мова,
   оформлення, вихід), і розкладає їх по-іншому. Тому переклади,
   підказки й обробники лишаються ті самі, а на десктопі (>900px) усе
   це просто сховане стилями.
   ============================================================ */
(function(){

const side = document.querySelector(".side");
if (!side) return;

/* ---- шапка ---- */
const top = document.createElement("header");
top.className = "mtop";
top.innerHTML =
  '<a class="mlogo" href="#dashboard"><span class="mark"><svg class="logo" aria-hidden="true">'
  + '<use href="#logomark"/></svg></span>Stats<i>AI</i></a>'
  + '<span class="sp"></span>'
  + '<button class="mnew" type="button" onclick="openForm()">'
  + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span></span></button>'
  + '<button class="mburger" type="button" aria-label="Меню">'
  + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M4 12h16M4 17h16" '
  + 'stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>';
document.body.insertBefore(top, document.body.firstChild);

/* ---- вкладки знизу: копії посилань з .nav ---- */
const tabs = document.createElement("nav");
tabs.className = "mtabs";
document.body.appendChild(tabs);

function paintTabs(){
  const links = side.querySelectorAll(".nav a");
  tabs.innerHTML = "";
  links.forEach(a => {
    const c = a.cloneNode(true);
    c.removeAttribute("data-tip");
    tabs.appendChild(c);
  });
  syncTabs();
}
function syncTabs(){
  const cur = (location.hash || "#dashboard").slice(1);
  tabs.querySelectorAll("a").forEach(a => a.classList.toggle("on", a.dataset.v === cur));
  const nt = document.getElementById("newTradeBtn");
  const lbl = top.querySelector(".mnew span");
  if (nt && lbl) lbl.textContent = (nt.querySelector("span") || {}).textContent || "+";
}

/* ---- шторка меню ---- */
const wrap = document.createElement("div");
wrap.className = "mmenu-wrap";
wrap.innerHTML = '<div class="ov"></div><aside class="mmenu"><div class="mhead"><b>StatsAI</b>'
  + '<button class="x" type="button" aria-label="Закрити">×</button></div></aside>';
document.body.appendChild(wrap);
const menu = wrap.querySelector(".mmenu");

/* Блоки переносимо в шторку, коли вона відкривається, і повертаємо назад,
   коли закривається: так на десктопі вони завжди на своєму місці, а
   обробники в них не губляться, бо це ті самі вузли. */
const MOVABLE = [".grp", ".conn", ".side-foot"];
const homes = new Map();
function openMenu(){
  MOVABLE.forEach(sel => {
    const el = side.querySelector(sel);
    if (!el) return;
    homes.set(el, {parent: el.parentNode, next: el.nextSibling});
    menu.appendChild(el);
  });
  wrap.classList.add("in");
  document.body.style.overflow = "hidden";
}
function closeMenu(){
  wrap.classList.remove("in");
  document.body.style.overflow = "";
  homes.forEach((h, el) => h.parent.insertBefore(el, h.next));
  homes.clear();
}
top.querySelector(".mburger").onclick = openMenu;
wrap.querySelector(".ov").onclick = closeMenu;
wrap.querySelector(".x").onclick = closeMenu;
/* клік по будь-якій кнопці в шторці — закриваємо, дія вже пішла */
menu.addEventListener("click", e => {
  if (e.target.closest("button, a")) setTimeout(closeMenu, 60);
});
window.addEventListener("resize", () => { if (innerWidth > 900 && wrap.classList.contains("in")) closeMenu(); });

paintTabs();
window.addEventListener("hashchange", syncTabs);
/* мова змінює підписи в .nav — перемальовуємо вкладки слідом */
const realApply = window.applyLang;
if (typeof realApply === "function"){
  window.applyLang = function(){ const r = realApply.apply(this, arguments); paintTabs(); return r; };
}
/* інші файли теж підписують свої пункти після старту — ловимо це */
new MutationObserver(paintTabs).observe(side.querySelector(".nav"), {subtree: true, childList: true, characterData: true});

})();
