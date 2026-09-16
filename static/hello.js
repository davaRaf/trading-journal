/* ============================================================
   Привітання при вході: «Ласкаво просимо <нік>. Раді тебе бачити» на весь екран,
   потім журнал. Оформлення — static/hello.css.

   Коли: після кожного входу в акаунт (login.html стирає позначку) і раз
   за сесію браузера — оновлення сторінки його не повторює. Скрипт у <head>
   index.html ставить клас hello-on лише на «/» (туди сервер пускає тільки
   тих, хто увійшов), тож гість, демо й чужий журнал /u/<нік> його не
   бачать. Немає ніка — екран просто тане.

   Пропустити: клік, дотик або будь-яка клавіша.
   ============================================================ */
(function(){

const root = document.documentElement;
const box = document.getElementById("hello");
/* Інші вікна, що відкриваються самі (пропозиція імпорту з Notion), чекають
   на __hello.done: інакше вони відкривались під привітанням і проступали
   крізь нього, поки воно тане. Привітання немає — обіцянка вже виконана. */
let resolveDone;
const donePromise = new Promise(r => { resolveDone = r; });
window.__hello = {done: donePromise, finish: () => {}};
if (!box || !root.classList.contains("hello-on")){ if (box) box.remove(); resolveDone(); return; }

const KEY = "statsai_hello";
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const HOLD = reduce ? 1700 : 2600;     // скільки стоїть привітання
const OUT  = reduce ? 300 : 560;       // скільки тане
let done = false, timer = 0;

function finish(){
  if (done) return;
  done = true;
  clearTimeout(timer);
  box.classList.add("out");
  removeEventListener("keydown", finish, true);
  setTimeout(() => { root.classList.remove("hello-on"); box.remove(); resolveDone(); }, OUT);
}
box.addEventListener("pointerdown", finish);
addEventListener("keydown", finish, true);

/* Крива росту рахунку: плавний підйом зліва направо, поверх нього шум і
   одна просадка посередині. Щоразу трохи інша, але без стрибків і завжди
   закінчується вгорі — у тій точці, куди вела весь час. */
function curve(){
  const N = 42, pts = [];
  let noise = 0;
  for (let i = 0; i < N; i++){
    const k = i / (N - 1);
    const base = 330 - 230 * Math.pow(k, 1.25);
    noise = noise * 0.8 + (Math.random() - 0.5) * 26;
    const dip = Math.exp(-Math.pow((k - 0.5) / 0.07, 2)) * 28;   // просадка
    const calm = 1 - Math.pow(k, 6);                               // під кінець шум затихає
    pts.push([k * 1000, Math.max(70, Math.min(370, base + noise * calm + dip))]);
  }
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const line = box.querySelector(".hello-curve .line");
  const area = box.querySelector(".hello-curve .area");
  const dot  = box.querySelector(".hello-curve .dot");
  if (line) line.setAttribute("d", d);
  if (area) area.setAttribute("d", d + " L1000 400 L0 400 Z");
  if (dot){ const last = pts[pts.length - 1]; dot.setAttribute("cx", last[0] - 6); dot.setAttribute("cy", last[1]); }
}

function play(nick){
  const set = (sel, text) => { const el = box.querySelector(sel); if (el) el.textContent = text; };
  set(".hello-hi", T.helloHi);
  set(".hello-nick", nick);
  fitNick();
  const glad = box.querySelector(".hello-glad");
  if (glad) glad.innerHTML = esc(T.helloGlad) + "<i>.</i>";
  box.setAttribute("aria-label", T.helloHi + " " + nick + " " + T.helloGlad);
  curve();
  box.classList.add("play");
  try{ sessionStorage.setItem(KEY, "1"); }catch(e){}
  timer = setTimeout(finish, HOLD);
}

/* Нік не рвемо посередині: якщо не влазить у рядок, зменшуємо все речення
   (до 22px). Лише коли й так не влазить — дозволяємо перенос. */
function fitNick(){
  const line = box.querySelector(".hello-line"), nk = box.querySelector(".hello-nick");
  if (!line || !nk) return;
  line.style.fontSize = "";
  nk.style.whiteSpace = "nowrap";
  const room = Math.min(box.clientWidth * 0.92, box.clientWidth - 48);
  let fs = parseFloat(getComputedStyle(line).fontSize);
  while (nk.scrollWidth > room && fs > 22){ fs -= 1; line.style.fontSize = fs + "px"; }
  if (nk.scrollWidth > room) nk.style.whiteSpace = "";
}

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

/* Сервер не відповів за 2.5 с — не тримаємо людину перед порожнім екраном. */
setTimeout(() => { if (!box.classList.contains("play")) finish(); }, 2500);

(async function start(){
  let u = null;
  try{
    const r = await fetch("/api/auth/me", {credentials: "same-origin"});
    if (r.ok) u = (await r.json()).user;
  }catch(e){}
  if (done) return;
  if (!u || !u.nickname) return finish();
  play(u.nickname);
})();

window.__hello.finish = finish;

})();
