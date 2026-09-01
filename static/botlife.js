/* ============================================================
   Живий помічник.

   Три речі поверх того, що вже є:
     1. чат відкривається хмаринкою біля кнопки, а не панеллю на пів екрана
     2. кнопка час від часу підстрибує
     3. інколи поруч спливає питання від помічника — його видно, поки
        людина не відвела очі, і по ньому можна одразу спитати

   Логіку чату не чіпаємо: підміняємо тільки Sheet.open на час виклику,
   тож усі обробники, надсилання й розбір лишаються ті самі, що в
   assistant.js.
   ============================================================ */
(function(){

let cloud = null;
let sayTimer = null;
let saidTimes = 0;

/* ---------- хмаринка з чатом ---------- */
function mountCloud(html, opts){
  closeCloud();
  cloud = document.createElement("div");
  cloud.className = "bl-cloud " + ((opts && opts.cls) || "");
  cloud.innerHTML = html;
  document.body.appendChild(cloud);
  /* через таймер, а не rAF: у фоновій вкладці rAF заморожений,
     і хмаринка лишилась би прозорою */
  setTimeout(() => cloud && cloud.classList.add("in"), 20);
  document.addEventListener("mousedown", outside, true);
  return cloud;
}

function closeCloud(){
  document.removeEventListener("mousedown", outside, true);
  if (!cloud) return;
  const c = cloud;
  cloud = null;
  c.classList.remove("in");
  setTimeout(() => c.remove(), 180);
}

function outside(e){
  if (!cloud) return;
  if (cloud.contains(e.target)) return;
  if (e.target.closest && e.target.closest(".as-fab, .bl-say")) return;
  closeCloud();
}

/* ---------- підміна відкриття ---------- */
function openHere(prefill){
  hideSay();
  if (cloud){ closeCloud(); return; }
  const real = Sheet.open;
  Sheet.open = mountCloud;
  try{ Assistant.open(); }
  finally{ Sheet.open = real; }

  if (prefill){
    const f = cloud && cloud.querySelector(".as-input");
    if (f){ f.value = prefill; f.focus(); }
  }
}

/* закриття теж має вміти прибирати хмаринку */
const realClose = window.closeModal;
window.closeModal = function(){
  if (cloud){ closeCloud(); return; }
  return realClose.apply(this, arguments);
};

window.openAssistant = function(){ openHere(""); };

/* ---------- питання, що спливає біля кнопки ---------- */
function hints(){
  const t = (typeof T !== "undefined") ? T : {};
  return [t.asHint1, t.asHint2, t.asHint3, t.asHint4].filter(Boolean);
}

function hideSay(){
  const s = document.querySelector(".bl-say");
  if (!s) return;
  s.classList.remove("in");
  setTimeout(() => s.remove(), 200);
}

function say(){
  const list = hints();
  if (!list.length) return;
  /* мовчимо, поки відкрито щось інше — інакше лізе поверх роботи */
  if (cloud || document.querySelector(".pnl-wrap")) return;
  const modal = document.getElementById("modal");
  if (modal && !modal.hidden) return;

  hideSay();
  const text = list[saidTimes % list.length];
  const el = document.createElement("button");
  el.className = "bl-say";
  el.type = "button";
  el.innerHTML = '<span>' + text + "</span>";
  el.onclick = () => openHere(text);
  document.body.appendChild(el);
  setTimeout(() => el.classList.add("in"), 20);
  saidTimes++;
  setTimeout(hideSay, 9000);

  /* стрибок — тільки якщо людина не просила менше руху; саму підказку
     показуємо в будь-якому разі, вона не про анімацію */
  const fab = document.querySelector(".as-fab");
  if (fab && !calm()){ fab.classList.add("bl-hop"); setTimeout(() => fab.classList.remove("bl-hop"), 900); }
}

/* Перше питання — коли людина вже освоїлась, далі рідше й лише тричі:
   помічник має нагадувати про себе, а не заважати. */
function schedule(){
  clearTimeout(sayTimer);
  if (saidTimes >= 3) return;
  const delay = saidTimes === 0 ? 25000 : 70000 + Math.round(Math.random() * 40000);
  sayTimer = setTimeout(() => { say(); schedule(); }, delay);
}

function calm(){
  return !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
}

window.addEventListener("load", () => setTimeout(schedule, 1500));

/* щоб можна було подивитись, як це виглядає, не чекаючи хвилини */
window.__bot = {say, open: openHere, hide: hideSay};

})();
