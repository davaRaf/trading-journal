/* ============================================================
   Чужий журнал: /u/<нік>.

   Людина відкрила свій журнал іншим — і тепер його можна подивитись
   зсередини, а не одним знімком за посиланням. Розділи, календар і
   аналітика вже вміють малювати будь-який список угод, тому окремої
   сторінки немає: той самий застосунок, тільки угоди чужі й писати не
   можна. Що саме віддавати назовні, вирішує сервер (app.py,
   PUBLIC_FIELDS) — тут ми лише не показуємо того, чого в чужому
   журналі бути не може: «Аналіз дня», «Мою ТС», підключення й запис.

   Дивитись може лише той, у кого є свій акаунт. Без нього замість
   журналу стоїть запрошення завести свій — так само, як гостю.
   ============================================================ */
(function(){

let nick = "";     // чий журнал дивимось
let on = false;
let mine = false;  // свій же журнал очима інших

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* Адреса — єдине джерело: /u/<нік> вмикає режим, будь-яка інша сторінка ні. */
function detect(){
  const m = location.pathname.match(/^\/u\/([\w.\-]{1,40})\/?$/);
  nick = m ? decodeURIComponent(m[1]) : "";
  on = !!nick;
  return on;
}

/* Полоса зверху: чий це журнал і як повернутись до свого. */
function bar(){
  const el = document.createElement("div");
  el.className = "pbar";
  el.innerHTML = '<b>@' + esc(nick) + "</b>"
    + '<span class="tx">' + esc(T.pubBar.replace("%s", "@" + nick)) + "</span>"
    + '<span class="sp"></span>'
    + '<a class="pgo" href="/">' + esc(T.pubMine) + "</a>";
  document.body.appendChild(el);
  document.body.classList.add("has-pbar");
}

/* У чужому журналі нема чого записувати й нема особистих розділів:
   прибираємо їх зовсім, щоб людина не тикала в мертві кнопки. */
function sidebar(){
  ["#newTradeBtn", '.nav a[data-v="day"]', '.nav a[data-v="ts"]', "#conn",
   "#publicBtn", "#logoutBtn"].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.remove();
  });
  const lab = document.getElementById("journalLab");
  if (lab) lab.textContent = "@" + nick;
}

/* Свій же журнал підписуємо інакше: людина прийшла перевірити, як він
   виглядає збоку, і лякати її словом «чужий» не треба. */
async function whose(){
  try{
    const r = await fetch("/api/auth/me", {credentials: "same-origin"});
    const d = await r.json();
    const me = d.user && d.user.nickname || "";
    mine = me.toLowerCase() === nick.toLowerCase();
  }catch(e){ mine = false; }
  if (mine) relang();
}

/* Замість журналу — одна сторінка з поясненням. Використовуємо, коли
   дивитись нічого: журнал закритий або людина ще без акаунта. */
function screen(title, text, invite){
  document.documentElement.setAttribute("data-pub-stop", "1");
  const bar = document.querySelector(".pbar");
  if (bar) bar.remove();
  document.body.classList.remove("has-pbar");
  const main = document.getElementById("main");
  if (!main) return;
  main.innerHTML = '<div class="pstop"><div class="pstop-mk">'
    + '<svg width="20" height="20"><use href="#logomark"/></svg></div>'
    + "<h1>" + esc(title) + "</h1><p>" + esc(text) + "</p>"
    + (invite
        ? '<div class="pstop-btns"><a class="btn primary" href="/login#signup">'
          + esc(T.gsSignup) + '</a><a class="btn" href="/login">'
          + esc(T.gsLogin) + "</a></div>"
        : '<div class="pstop-btns"><a class="btn" href="/">'
          + esc(T.pubMine) + "</a></div>")
    + "</div>";
}

/* Чому не вдалось завантажити чужий журнал. Повертаємо true, якщо
   пояснили самі — тоді загальний обробник у app.js мовчить. */
function fail(e){
  const msg = String((e && e.message) || "");
  if (msg === "API 401"){ screen(T.pubNeedTitle, T.pubNeedText, true); return true; }
  if (msg === "API 404"){ screen(T.pubClosedTitle, T.pubClosedText, false); return true; }
  return false;
}

/* Куди насправді йде запит. Своїх адрес у чужому журналі немає: те, що
   не перелічене тут, не питаємо взагалі — інакше на чужій сторінці
   малювались би власні нотатки й ТС. */
function url(u){
  const who = encodeURIComponent(nick);
  if (u === "/api/trades") return "/api/u/" + who + "/trades";
  if (u.indexOf("/api/u/") === 0) return u;
  if (u.indexOf("/api/auth/") === 0) return u;
  if (u.indexOf("/api/calendar") === 0) return u;
  return "";
}

function shot(file){
  return "/ushot/" + encodeURIComponent(nick) + "/" + encodeURIComponent(file);
}

/* Мову міняють на льоту — полосу переписуємо разом з рештою. */
function relang(){
  const bar = document.querySelector(".pbar");
  if (!bar) return;
  const tx = bar.querySelector(".tx");
  if (tx) tx.textContent = mine ? T.pubBarMine : T.pubBar.replace("%s", "@" + nick);
  const go = bar.querySelector(".pgo");
  if (go) go.textContent = T.pubMine;
}

function start(){
  if (!on) return;
  document.documentElement.setAttribute("data-pub", nick);
  bar();
  sidebar();
  whose();
}

window.Pub = {
  detect: detect,
  start: start,
  fail: fail,
  relang: relang,
  url: url,
  shot: shot,
  screen: screen,
  get on(){ return on; },
  get nick(){ return nick; },
  /* Той самий зміст, що й Guest.block: місце виклику просто виходить. */
  block: function(){
    if (!on) return false;
    if (typeof openModal === "function"){
      openModal('<div class="gate-w"><div class="gate-mk">'
        + '<svg width="18" height="18"><use href="#logomark"/></svg></div>'
        + "<h3>" + esc(T.pubBlocked) + "</h3>"
        + '<a class="btn primary wide" href="/">' + esc(T.pubMine) + "</a>"
        + '<button type="button" class="gate-later" onclick="closeModal()">'
        + esc(T.gsLater) + "</button></div>");
    }
    return true;
  },
};

})();
