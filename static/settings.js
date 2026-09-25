/* ============================================================
   Вікно «Налаштування».

   Раніше всі розділи йшли однією стрічкою: мова, відкритий журнал,
   пошта, пароль, 2FA, пристрої, копія — і власник сказав, що не видно,
   де який розділ і забагато тексту. Тепер (рішення 15.09.2026, варіант A):

   — на комп'ютері зліва меню розділів, справа лише вибраний;
   — на телефоні спершу список розділів, натиснув — розділ на весь
     екран зі стрілкою «назад». Смуги вкладок з прокруткою немає.

   Першим пунктом — профіль (static/me.js). Решта розділів — ті самі
   модулі, що й були (profile.js, mailcheck.js, pwd.js, twofa.js,
   backup.js): вони віддають свою розмітку, тут лише рамка навколо.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* У чужому журналі (/u/<нік>) особисті розділи ховаємо: там людина
   дивиться не своє. Лишається мова — нею читають сторінку. */
const inPub = () => !!(window.Pub && window.Pub.on);
const phone = () => matchMedia("(max-width:560px)").matches;

let tab = "profile";      // вибраний розділ
let screen = null;        // на телефоні: null — список, інакше розділ

const ICON = {
  globe:  '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
  mail:   '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 6.5 8.5 6.5 8.5-6.5"/>',
  shield: '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3z"/><path d="m9 12 2 2 4-4"/>',
  eye:    '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  box:    '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>',
  paint:  '<circle cx="12" cy="12" r="9"/><path d="M12 3a4.5 4.5 0 000 9 4.5 4.5 0 010 9"/>',
  chev:   '<path d="m9 6 6 6-6 6"/>',
  back:   '<path d="m15 6-6 6 6 6"/>',
  x:      '<path d="M6 6l12 12M18 6 6 18"/>',
  star:   '<path d="M12 3.6l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.8l5.9-.9z"/>',
};
const ic = (n, cls) => '<svg class="stx-ic' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" aria-hidden="true">' + ICON[n] + "</svg>";

function langs(){
  const names = {uk: "Українська", ru: "Русский", en: "English"};
  return '<div class="st-langs" role="group" aria-label="' + esc(T.stLang) + '">'
    + ["uk", "ru", "en"].map(c =>
        '<button type="button" class="' + (c === LANG ? "on" : "") + '"'
        + ' aria-pressed="' + (c === LANG) + '"'
        + ' onclick="__settings.lang(&quot;' + c + '&quot;)">' + names[c] + "</button>").join("")
    + "</div>";
}

function block(title, guts, cls){
  if (!guts) return "";
  return '<section class="st-sec' + (cls ? " " + cls : "") + '">'
    + (title ? '<h4 class="st-h">' + esc(title) + "</h4>" : "") + guts + "</section>";
}

/* Розділи. html() — вміст, todo() — «є що зробити» (жовта крапка). */
function sections(){
  const me = window.__me && __me.user();
  const own = !inPub();
  const list = [];
  if (own && me) list.push({id: "profile", title: T.stProfile, profile: true,
    html: () => __me.pane(), wire: () => __me.wire()});
  list.push({id: "general", title: T.stGeneral, icon: "globe", html: () => block("", langs())});
  /* Оформлення — не особисте: тема лежить у браузері, тож розділ є і в
     чужому журналі. Раніше це було окреме вікно з кнопки в панелі. */
  if (window.__skin) list.push({id: "skin", title: T.thModalTitle, icon: "paint",
    html: () => block("", __skin.section(), "th")});
  if (own){
    const ec = window.__mailcheck ? __mailcheck.section() : "";
    const pw = window.__pwd ? __pwd.section() : "";
    /* «Вийти» живе тут: у бічній панелі лишився тільки свій профіль */
    const out = me ? '<p class="pw-lead">' + esc(T.stLogoutLead) + "</p>"
      + '<button class="btn danger" type="button" id="stLogout">' + esc(T.sdLogout) + "</button>" : "";
    if (ec || pw || out) list.push({id: "account", title: T.stAccount, icon: "mail",
      todo: !!(me && !me.email_confirmed && ec),
      html: () => block(T.ecTitle, ec, "ec") + block(T.pwTitle, pw, "pw") + block(T.sdLogoutTip, out, "pw"),
      wire: () => { if (ec) __mailcheck.wire(); if (pw) __pwd.wire();
        const lo = document.getElementById("stLogout"); if (lo) lo.onclick = () => logout(); }});
    const tf = window.__twofa ? __twofa.section() : "";
    const lo = window.__twofa ? __twofa.sessions() : "";
    if (tf || lo) list.push({id: "security", title: T.stSecurity, icon: "shield",
      todo: !!(me && !me.twofa),
      html: () => block(T.tfTitle, tf, "tf") + block(T.loTitle, lo, "tf"),
      wire: () => __twofa.wire()});
    /* Підписка — поки вітрина тарифів без оплати (static/plans.js) */
    const sub = window.__plans ? __plans.section() : "";
    if (sub) list.push({id: "subscription", title: __plans.title(), icon: "star", sep: true,
      html: () => block("", sub, "sub")});
    const pp = window.__profile ? __profile.section() : "";
    if (pp) list.push({id: "open", title: T.ppTitle, icon: "eye", sep: true,
      html: () => block("", pp, "pp"), wire: () => __profile.wire()});
    const bk = window.__backup ? __backup.section() : "";
    if (bk) list.push({id: "backup", title: T.bkTitle, icon: "box",
      html: () => block("", bk, "bk"), wire: () => { if (__backup.wire) __backup.wire(); }});
  }
  return list;
}

function navItem(s){
  const lead = s.profile
    ? __me.avatar(26) + '<span class="stx-me"><b>' + esc(__me.user().nickname) + "</b><small>" + esc(T.stProfile) + "</small></span>"
    : ic(s.icon) + "<span>" + esc(s.title) + "</span>";
  return (s.sep ? '<div class="stx-sep"></div>' : "")
    + '<button type="button" role="tab" class="stx-nav-i' + (s.profile ? " me" : "") + '" data-st="' + s.id + '"'
    + ' aria-selected="' + (s.id === tab) + '">' + lead
    + (s.todo ? '<span class="stx-dot" title="' + esc(T.stTodo) + '"></span>' : "") + "</button>"
    + (s.profile ? '<div class="stx-sep"></div>' : "");
}

function paneHead(s){
  return '<div class="stx-pane-h"><h3>' + esc(s.title)
    + (s.profile ? '<span class="stx-free">' + esc(T.meFree) + "</span>" : "") + "</h3></div>";
}

function closeBtn(){
  return '<button class="stx-x" type="button" onclick="closeModal()" aria-label="' + esc(T.mrClose) + '">' + ic("x") + "</button>";
}

function draw(){
  const list = sections();
  if (!list.some(s => s.id === tab)) tab = list[0].id;
  let html;
  if (!phone()){
    const cur = list.find(s => s.id === tab);
    html = '<div class="stx">'
      + '<div class="stx-head"><h2>' + esc(T.stTitle) + "</h2>" + closeBtn() + "</div>"
      + '<div class="stx-body">'
      +   '<nav class="stx-nav" role="tablist" aria-label="' + esc(T.stTitle) + '">' + list.map(navItem).join("") + "</nav>"
      +   '<div class="stx-pane" role="tabpanel">' + paneHead(cur) + cur.html() + "</div>"
      + "</div></div>";
    openModal(html);
    if (cur.wire) cur.wire();
    return;
  }
  /* телефон */
  const cur = screen && list.find(s => s.id === screen);
  if (!cur){
    screen = null;
    const rows = list.map(s =>
      (s.sep ? '<div class="stx-gap"></div>' : "")
      + '<button type="button" class="stx-row" data-sc="' + s.id + '">'
      + (s.profile
          ? __me.avatar(36) + '<span class="stx-row-t"><b>' + esc(__me.user().nickname) + "</b><small>" + esc(T.stProfileSub) + "</small></span>"
          : '<span class="stx-row-ic">' + ic(s.icon) + '</span><span class="stx-row-t"><b>' + esc(s.title) + "</b></span>")
      + (s.todo ? '<span class="stx-todo">' + esc(T.stTodo) + "</span>" : "")
      + ic("chev", "chev") + "</button>").join("");
    html = '<div class="stx is-phone">'
      + '<div class="stx-head"><h2>' + esc(T.stTitle) + "</h2>" + closeBtn() + "</div>"
      + '<div class="stx-pane"><div class="stx-list">' + rows + "</div></div></div>";
    openModal(html);
    return;
  }
  html = '<div class="stx is-phone">'
    + '<div class="stx-head"><button type="button" class="stx-back" data-sc="" aria-label="' + esc(T.pwBack) + '">' + ic("back") + "</button>"
    /* на телефоні заголовок розділу вже в шапці — вдруге над фото не пишемо */
    + "<h2>" + esc(cur.title) + (cur.profile ? ' <span class="stx-free">' + esc(T.meFree) + "</span>" : "") + "</h2>"
    + closeBtn() + "</div>"
    + '<div class="stx-pane">' + cur.html() + "</div></div>";
  openModal(html);
  if (cur.wire) cur.wire();
}

/* Клік по меню — делегуванням на вікно: розмітка перемальовується цілком.
   Перемальовуємо після кліку, а не посеред нього: інші слухачі того ж
   кліку (підказки тощо) інакше знаходили б уже викинуті з сторінки вузли. */
document.addEventListener("click", e => {
  const box = e.target.closest && e.target.closest(".stx");
  if (!box) return;
  const t = e.target.closest("[data-st]");
  if (t){ tab = t.dataset.st; setTimeout(() => { draw(); focusPane(); }, 0); return; }
  const sc = e.target.closest("[data-sc]");
  if (sc){ screen = sc.dataset.sc || null; if (screen) tab = screen; setTimeout(draw, 0); }
});

function focusPane(){
  const b = document.querySelector('.stx-nav [aria-selected="true"]');
  if (b) b.focus();
}

async function open(where){
  if (!inPub()) await Promise.all([
    window.__me ? __me.load() : null,
    window.__profile ? __profile.load() : null,
    window.__mailcheck ? __mailcheck.load() : null,
    window.__pwd ? __pwd.load() : null,
    window.__twofa ? __twofa.load() : null,
    window.__backup ? __backup.load() : null,
  ]);
  /* Повернення з під-вікна (пароль, 2FA) — на той самий розділ; звичайне
     відкриття — з профілю, а на телефоні зі списку. */
  if (typeof where === "string"){ tab = where; screen = phone() ? where : null; }
  else if (!document.querySelector(".stx")){ tab = "profile"; screen = null; }
  draw();
}

/* Мову міняє той самий applyLang: він перемальовує застосунок, а вікно
   перемальовуємо слідом новою мовою — не закриваючи. */
function lang(code){
  if (code === LANG) return;
  applyLang(code);
  draw();
}

/* Перехід між шириною телефона й комп'ютера — перемальовуємо відкрите вікно. */
matchMedia("(max-width:560px)").addEventListener("change", () => {
  if (document.querySelector(".stx")){ if (phone()) screen = tab; draw(); }
});

window.__settings = {open: open, lang: lang, redraw: draw};

})();
