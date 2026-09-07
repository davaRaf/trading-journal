/* ============================================================
   Підтвердження пошти — розділом у вікні «Налаштування».

   Лист із посиланням іде сам при реєстрації. Тут людина бачить, чим
   скінчилось: адреса прийнята — чи лист десь загубився і його треба
   надіслати ще раз.

   Доступу підтвердження не відкриває й не закриває: журнал працює
   однаково. Воно потрібне для одного — щоб «забув пароль» мало куди
   написати. Тому й сказано тут саме так, без погроз відключенням.

   Розділ показуємо тільки в своєму журналі: гість і чужа сторінка
   пошти не мають (settings.js питає section(), той віддає порожньо).
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

function section(){
  if (typeof DEMO !== "undefined" && DEMO) return "";
  if (window.Pub && Pub.on) return "";
  if (!user || !user.email) return "";

  const ok = !!user.email_confirmed;
  let h = '<div class="ec-row"><span class="ec-mark' + (ok ? " ok" : "") + '"></span>'
    + '<b class="ec-mail">' + esc(user.email) + "</b>"
    + '<span class="ec-state">' + esc(ok ? T.ecOk : T.ecNo) + "</span></div>";
  if (!ok){
    h += '<p class="ec-lead">' + esc(T.ecLead) + "</p>"
      + '<div class="ec-act"><button class="btn" type="button" id="ecGo">'
      +   esc(T.ecSend) + "</button>"
      +   '<span class="ec-msg" id="ecMsg"></span></div>';
  }
  return h;
}

function say(text, ok){
  const n = $id("ecMsg");
  if (!n) return;
  n.textContent = text;
  n.className = "ec-msg" + (ok ? " ok" : text ? " bad" : "");
}

async function send(){
  if (busy) return;
  busy = true;
  const btn = $id("ecGo");
  if (btn) btn.disabled = true;
  say(T.ecSending);
  try{
    /* Свій запит, а не api(): той віддає лише номер статусу, а тут
       потрібно знати, скільки чекати після частих натискань. */
    const res = await fetch("/api/me/confirm", {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lang: (window.LANG || "uk")}),
    });
    let data = {};
    try{ data = await res.json(); }catch(e){}
    if (!res.ok) throw data;
    say(T.ecSent, true);
  }catch(e){
    say((e && e.code) === "too_many"
        ? T.ecMany.replace("%d", e.wait || 60) : T.ecFail);
    if (btn) btn.disabled = false;
    busy = false;
    return;
  }
  /* Кнопку лишаємо вимкненою: лист уже в дорозі, і другий такий самий
     нічого не змінить, а от лічильник на сервері зачепить. */
  busy = false;
}

function wire(){
  const btn = $id("ecGo");
  if (btn) btn.onclick = send;
}

window.__mailcheck = {load: load, section: section, wire: wire};

})();
