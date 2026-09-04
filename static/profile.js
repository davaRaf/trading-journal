/* ============================================================
   Відкритий журнал: перемикач і посилання на себе.

   За замовчуванням журнал закритий. Тут людина сама вирішує показати
   його іншим — і одразу бачить, що саме побачать, а що ні. Посилання
   робиться з ніка, тому окремого «публічного імені» заводити не треба.
   ============================================================ */
(function(){

let user = null;

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function link(){
  return location.origin + "/u/" + encodeURIComponent(user.nickname);
}

/* Начинка без обгортки: та сама і в своєму вікні, і розділом у вікні
   «Налаштування» (static/settings.js). */
function inner(){
  const on = !!user.public_journal;
  return '<p class="pp-lead">' + esc(T.ppLead) + "</p>"
    + '<label class="pp-sw"><input type="checkbox" id="ppOn"' + (on ? " checked" : "") + ">"
    +   "<b>" + esc(T.ppOn) + "</b></label>"
    + '<div class="pp-link' + (on ? "" : " off") + '" id="ppLinkBox">'
    +   '<div class="pp-cap">' + esc(T.ppLink) + "</div>"
    +   '<div class="pp-row"><input class="pp-url" id="ppUrl" readonly value="'
    +     esc(link()) + '">'
    +     '<button class="btn" type="button" id="ppCopy">' + esc(T.ppCopy) + "</button></div>"
    /* Обидва підписи лежать у розмітці завжди, показується той, що
       відповідає стану: інакше поява рядка смикала вікно по висоті. */
    +   '<div class="pp-note"><span class="n-on">' + esc(T.ppOpenNote) + "</span>"
    +     '<span class="n-off">' + esc(T.ppClosedNote) + "</span></div>"
    + "</div>"
    + '<ul class="pp-what"><li class="yes">' + esc(T.ppShow) + "</li>"
    +   '<li class="no">' + esc(T.ppHide) + "</li></ul>";
}

function body(){
  return '<div class="m-body pp">' + inner() + "</div>";
}

/* Для вікна налаштувань: спершу load() — воно читає людину, потім
   section() дає розмітку, після вставки в сторінку — wire(). Порожній
   рядок означає «показувати нема чого»: гість або людина без ніка. */
async function load(){
  try{ user = (await api("GET", "/api/auth/me")).user; }
  catch(e){ user = null; }
  return user;
}

function section(){
  return user && user.nickname ? inner() : "";
}

function paint(){
  const box = document.getElementById("ppLinkBox");
  if (!box) return;
  box.classList.toggle("off", !user.public_journal);
}

function wire(){
  const sw = document.getElementById("ppOn");
  if (sw) sw.onchange = async () => {
    sw.disabled = true;
    try{
      const r = await api("POST", "/api/me/public", {on: sw.checked});
      user.public_journal = !!r.public_journal;
    }catch(e){
      sw.checked = !!user.public_journal;      // не вийшло — вертаємо як було
    }
    sw.disabled = false;
    paint();
  };
  const copy = document.getElementById("ppCopy");
  if (copy) copy.onclick = async () => {
    const field = document.getElementById("ppUrl");
    try{ await navigator.clipboard.writeText(link()); }
    catch(e){ if (field){ field.select(); document.execCommand("copy"); } }
    copy.textContent = T.ppCopied;
  };
}

async function open(){
  if (window.Guest && Guest.block(T.ppTitle)) return;
  try{
    user = (await api("GET", "/api/auth/me")).user;
  }catch(e){ user = null; }
  if (!user || !user.nickname){ alert(T.ppNeedNick); return; }
  openModal(
    '<div class="m-head"><h2>' + esc(T.ppTitle) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(T.mrClose) + '">×</button></div>'
    + body()
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(T.mrClose) + "</button></div>");
  wire();
}

window.__profile = {open: open, load: load, section: section, wire: wire};

})();
