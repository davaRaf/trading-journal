/* ============================================================
   Зміна власного пароля — розділом у вікні «Налаштування».

   Старий пароль питаємо навіть у того, хто вже увійшов: сесія живе
   тридцять днів, і незакрита вкладка на чужому комп'ютері не повинна
   давати змогу перебити пароль. Сервер перевіряє те саме — тут це лише
   щоб людина не чекала відповіді дарма.

   Розділ показуємо тільки тому, хто увійшов паролем. Гість і чужий
   журнал його не бачать: settings.js питає section(), а той віддає
   порожній рядок.
   ============================================================ */
(function(){

let user = null;
let busy = false;

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const $id = id => document.getElementById(id);

async function load(){
  try{ user = (await api("GET", "/api/auth/me")).user; }
  catch(e){ user = null; }
  return user;
}

function field(id, label, ac){
  return '<label class="pw-f"><span>' + esc(label) + "</span>"
    + '<input id="' + id + '" type="password" autocomplete="' + ac + '"'
    + ' spellcheck="false"></label>';
}

function section(){
  /* демо й чужий журнал пароля не мають */
  if (typeof DEMO !== "undefined" && DEMO) return "";
  if (window.Pub && Pub.on) return "";
  if (!user || !user.nickname) return "";
  /* у розділі — лише кнопка; поля живуть в окремому вікні (dialog) */
  return '<div class="pw-row"><button class="btn" type="button" id="pwOpen">'
    + esc(T.pwSave) + "</button></div>";
}

/* Вікно зміни пароля. Малюється в тому ж #modal, що й налаштування, тому
   «Назад» і «×» просто відкривають налаштування знову. */
function back(){ if (window.__settings) __settings.open(); else closeModal(); }

function dialog(){
  openModal(
    '<div class="m-head"><h2>' + esc(T.pwTitle) + "</h2>"
    + '<button class="x" type="button" id="pwX" aria-label="' + esc(T.pwBack) + '">×</button></div>'
    + '<div class="m-body st"><section class="st-sec pw">'
    +   '<p class="pw-lead">' + esc(T.pwLead) + "</p>"
    +   '<div class="pw-grid">'
    +     field("pwOld", T.pwOld, "current-password")
    +     field("pwNew", T.pwNew, "new-password")
    +     field("pwNew2", T.pwRepeat, "new-password")
    +   "</div>"
    +   '<div class="pw-row"><span class="pw-msg" id="pwMsg"></span></div>'
    + "</section></div>"
    + '<div class="m-foot"><button class="btn" type="button" id="pwBack">' + esc(T.pwBack) + "</button>"
    + '<span class="sp"></span>'
    + '<button class="btn primary" type="button" id="pwGo">' + esc(T.pwSave) + "</button></div>");
  $id("pwX").onclick = back;
  $id("pwBack").onclick = back;
  $id("pwGo").onclick = save;
  /* Enter у будь-якому з трьох полів — те саме, що натиснути кнопку. */
  ["pwOld", "pwNew", "pwNew2"].forEach(id => {
    const n = $id(id);
    if (n) n.onkeydown = e => { if (e.key === "Enter") save(); };
  });
  const first = $id("pwOld");
  if (first) setTimeout(() => first.focus(), 50);
}

function say(text, ok){
  const n = $id("pwMsg");
  if (!n) return;
  n.textContent = text;
  n.className = "pw-msg" + (ok ? " ok" : text ? " bad" : "");
}

/* Коди помилок сервера — свої слова кожній. Текст сервера не показуємо:
   він один на всі мови, а вікно може стояти будь-якою. */
function errText(e){
  const code = (e && e.code) || "";
  if (code === "bad_old")  return T.pwErrOld;
  if (code === "short")    return T.pwErrShort;
  if (code === "too_many") return T.pwErrMany.replace("%d", e.wait || 60);
  return T.pwErrGeneric;
}

async function save(){
  if (busy) return;
  const oldPw = ($id("pwOld") || {}).value || "";
  const a = ($id("pwNew") || {}).value || "";
  const b = ($id("pwNew2") || {}).value || "";

  if (!oldPw || !a || !b) return say(T.pwErrEmpty);
  if (a.length < 6)       return say(T.pwErrShort);
  if (a !== b)            return say(T.pwErrMatch);
  if (a === oldPw)        return say(T.pwErrSame);

  busy = true;
  const btn = $id("pwGo");
  if (btn) btn.disabled = true;
  say(T.pwSaving);
  try{
    /* Свій запит, а не api(): той віддає тільки номер статусу, а тут
       потрібні код помилки й скільки чекати після перебору. */
    const res = await fetch("/api/me/password", {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({old: oldPw, new: a}),
    });
    let data = {};
    try{ data = await res.json(); }catch(e){}
    if (!res.ok) throw data;
    ["pwOld", "pwNew", "pwNew2"].forEach(id => { const n = $id(id); if (n) n.value = ""; });
    say(T.pwDone, true);
  }catch(e){
    say(errText(e));
  }
  busy = false;
  if (btn) btn.disabled = false;
}

function wire(){
  const btn = $id("pwOpen");
  if (btn) btn.onclick = dialog;
}

window.__pwd = {load: load, section: section, wire: wire};

})();
