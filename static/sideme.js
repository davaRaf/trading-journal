/* ============================================================
   Свій профіль угорі бічної панелі (#sideMe в index.html).

   Аватар і нік — одна кнопка в Налаштування → Профіль, на всю ширину,
   щоб нік читався цілком. «Вийти» — у Налаштуваннях, розділ «Акаунт». Дані — з /api/auth/me; після зміни
   ніка чи фото me.js кличе __sideMe.paint, і рядок оновлюється
   одразу. Гостю чи в чужому журналі без входу показувати нічого:
   рядок ховаємо, а в підвалі показуємо кнопку «Налаштування». На телефоні рядок їде в шторку разом з
   іншими блоками (mobile.js).
   ============================================================ */
(function(){

const box = document.getElementById("sideMe");
if (!box) return;

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* Останній відомий профіль: його беруть картинки «поділитись», щоб
   підписати малюнок автором (sharelink.js, tradeimg.js). */
let me = null;

function paint(u){
  me = (u && u.nickname) ? u : null;
  if (!u || !u.nickname) return anon();
  box.hidden = false;
  const av = document.getElementById("sideMeAv");
  const nick = document.getElementById("sideMeNick");
  if (av) av.innerHTML = u.avatar
    ? '<img class="me-av" style="--s:32px" src="' + esc(u.avatar) + '" alt="">'
    : '<span class="me-av" style="--s:32px">' + esc(u.nickname.charAt(0).toUpperCase()) + "</span>";
  if (nick) nick.textContent = u.nickname;
  const btn = document.getElementById("sideMeBtn");
  if (btn) btn.setAttribute("aria-label", u.nickname + " · " + (T.stProfile || ""));
}

/* Без акаунта: рядок зникає, «Налаштування» (там мова) з'являються
   звичайною кнопкою в підвалі. */
function anon(){
  box.hidden = true;
  const st = document.getElementById("settingsBtn");
  if (st) st.hidden = false;
}

async function load(){
  let u = null;
  try{
    const r = await fetch("/api/auth/me", {credentials: "same-origin"});
    if (r.ok) u = (await r.json()).user;
  }catch(e){}
  paint(u);
}

window.__sideMe = {paint: paint, load: load, user: () => me};
load();

})();
