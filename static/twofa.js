/* ============================================================
   Двоетапний вхід (2FA) і «вийти на всіх пристроях» — розділи у вікні
   «Налаштування». Сервер — /api/me/2fa/* і /api/me/logout-all в app.py.

   Увімкнення в два кроки, як і на сервері: спершу ключ для застосунку,
   потім перший код із нього. Лише після коду 2FA вмикається — інакше
   людина могла б замкнути себе захистом, якого її телефон не знає.
   Запасні коди показуємо один раз: сервер тримає тільки їхні відбитки.

   QR малюємо тут же, у браузері (static/qrcode.js, MIT): у ньому секрет,
   тож жодних сторонніх сервісів-генераторів картинок. Бібліотеку тягнемо
   лише коли людина натиснула «Увімкнути» — решті сторінок вона не потрібна.
   Не вантажиться — лишаються ключ вручну й «Відкрити в застосунку».
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

function hidden(){
  return (typeof DEMO !== "undefined" && DEMO) || (window.Pub && Pub.on) || !user || !user.nickname;
}

/* Свій запит, а не api(): потрібні код помилки й скільки чекати. */
async function post(url, body){
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try{ data = await res.json(); }catch(e){}
  if (!res.ok) throw data;
  if (data.user) user = data.user;
  return data;
}

function errText(e){
  const code = (e && e.code) || "";
  if (code === "twofa_bad")     return T.tfErrBad;
  if (code === "twofa_expired") return T.tfErrExpired;
  if (code === "too_many")      return T.tfErrMany.replace("%d", e.wait || 60);
  return T.pwErrGeneric;
}

/* state: true — успіх (зелене), "busy" — чекаємо (звичайне), інше — помилка.
   «Перевіряю…» не має бути червоним: це ще не помилка. */
function say(id, text, state){
  const n = $id(id);
  if (!n) return;
  n.textContent = text;
  n.className = "pw-msg" + (state === true ? " ok" : state === "busy" || !text ? "" : " bad");
}

/* назад — у розділ «Безпека» нового вікна налаштувань, а не на його початок */
function back(){ if (window.__settings) __settings.open("security"); else closeModal(); }

function codeField(id, label){
  return '<label class="pw-f tf-f"><span>' + esc(label) + "</span>"
    + '<input id="' + id + '" type="text" inputmode="numeric" autocomplete="one-time-code"'
    + ' maxlength="11" spellcheck="false" autocapitalize="off" placeholder="123456"></label>';
}

function onEnter(id, fn){
  const n = $id(id);
  if (n) n.onkeydown = e => { if (e.key === "Enter") fn(); };
}

function focusLater(id){ setTimeout(() => { const n = $id(id); if (n) n.focus(); }, 50); }

function copy(text, btn){
  const done = () => { if (btn){ btn.textContent = T.tfCopied; setTimeout(() => btn.textContent = btn.dataset.lbl, 1600); } };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done, () => {});
  }
}

/* ------------------------------------------------ розділи в налаштуваннях */

function section(){
  if (hidden()) return "";
  const on = !!user.twofa;
  const state = '<div class="tf-state"><span class="ec-mark' + (on ? " ok" : "") + '" aria-hidden="true"></span>'
    + "<b>" + esc(on ? T.tfOnState : T.tfOffState) + "</b></div>";
  const lead = '<p class="tf-lead">' + esc(on
    ? T.tfLeadOn.replace("%d", user.twofa_backup_left || 0) : T.tfLeadOff) + "</p>";
  const btns = on
    ? '<button class="btn" type="button" id="tfNewBackup">' + esc(T.tfNewBackup) + "</button>"
      + '<button class="btn danger" type="button" id="tfOff">' + esc(T.tfDisable) + "</button>"
    : '<button class="btn primary" type="button" id="tfOn">' + esc(T.tfEnable) + "</button>";
  return state + lead + '<div class="pw-row">' + btns + "</div>";
}

function sessions(){
  if (hidden()) return "";
  return '<p class="tf-lead">' + esc(T.loLead) + "</p>"
    + '<div class="pw-row"><button class="btn" type="button" id="loAll">' + esc(T.loBtn) + "</button>"
    + '<span class="pw-msg" id="loMsg" role="status" aria-live="polite"></span></div>';
}

function wire(){
  const on = $id("tfOn"), off = $id("tfOff"), nb = $id("tfNewBackup"), lo = $id("loAll");
  if (on) on.onclick = startEnable;
  if (off) off.onclick = () => askCode("disable");
  if (nb) nb.onclick = () => askCode("backup");
  if (lo) lo.onclick = logoutAll;
}

/* ------------------------------------------------------- QR-код */

let qrLib = null;
function loadQr(){
  if (window.qrcode) return Promise.resolve(true);
  if (!qrLib) qrLib = new Promise(done => {
    const s = document.createElement("script");
    s.src = "/static/qrcode.js?v=1";
    s.onload = () => done(!!window.qrcode);
    s.onerror = () => { qrLib = null; done(false); };
    document.head.appendChild(s);
  });
  return qrLib;
}

/* Один <path> замість сотень квадратиків: різкі краї на будь-якому
   масштабі. Поле тиші — 4 модулі, як вимагає стандарт, інакше камера
   на темному фоні сторінки може код не впізнати. */
function qrSvg(text){
  const q = qrcode(0, "M");
  q.addData(text);
  q.make();
  const n = q.getModuleCount(), pad = 4, size = n + pad * 2;
  let d = "";
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++)
      if (q.isDark(y, x)) d += "M" + (x + pad) + " " + (y + pad) + "h1v1h-1z";
  return '<svg viewBox="0 0 ' + size + " " + size + '" role="img" aria-label="' + esc(T.tfQrAria) + '"'
    + ' shape-rendering="crispEdges"><rect width="' + size + '" height="' + size + '" fill="#fff"/>'
    + '<path d="' + d + '" fill="#000"/></svg>';
}

/* ------------------------------------------------------- увімкнення */

async function startEnable(){
  let data, hasQr;
  try{ [data, hasQr] = await Promise.all([post("/api/me/2fa/setup"), loadQr()]); }
  catch(e){ return alert(errText(e)); }
  let qr = "";
  if (hasQr){ try{ qr = qrSvg(data.uri); }catch(e){ qr = ""; } }
  const groups = data.secret.match(/.{1,4}/g).join(" ");
  openModal(
    '<div class="m-head"><h2>' + esc(T.tfTitle) + "</h2>"
    + '<button class="x" type="button" id="tfX" aria-label="' + esc(T.pwBack) + '">×</button></div>'
    + '<div class="m-body st"><section class="st-sec tf">'
    +   '<ol class="tf-steps">'
    +     "<li>" + esc(T.tfStep1) + "</li>"
    +     "<li>" + esc(T.tfStep2)
    +       '<div class="tf-pair' + (qr ? "" : " no-qr") + '">'
    +         (qr ? '<div class="tf-qr" id="tfQr">' + qr + "</div>" : "")
    +         '<div class="tf-manual">'
    +           (qr ? '<p class="tf-lead">' + esc(T.tfManual) + "</p>" : "")
    +           '<div class="tf-key"><code id="tfKey" aria-label="' + esc(T.tfKeyAria) + '">' + esc(groups) + "</code>"
    +           '<button class="btn" type="button" id="tfCopyKey" data-lbl="' + esc(T.tfCopy) + '">' + esc(T.tfCopy) + "</button></div>"
    +           '<a class="btn tf-app" href="' + esc(data.uri) + '">' + esc(T.tfOpenApp) + "</a>"
    +         "</div>"
    +       "</div>"
    +     "</li>"
    +     "<li>" + esc(T.tfStep3) + codeField("tfCode", T.tfCode) + "</li>"
    +   "</ol>"
    +   '<div class="pw-row"><span class="pw-msg" id="tfMsg" role="alert"></span></div>'
    + "</section></div>"
    + '<div class="m-foot"><button class="btn" type="button" id="tfBack">' + esc(T.pwBack) + "</button>"
    + '<span class="sp"></span>'
    + '<button class="btn primary" type="button" id="tfGo">' + esc(T.tfConfirm) + "</button></div>");
  $id("tfX").onclick = back;
  $id("tfBack").onclick = back;
  $id("tfCopyKey").onclick = e => copy(data.secret, e.currentTarget);
  const go = () => confirmEnable(data.setup);
  $id("tfGo").onclick = go;
  onEnter("tfCode", go);
  focusLater("tfCode");
}

async function confirmEnable(setup){
  if (busy) return;
  const code = ($id("tfCode") || {}).value || "";
  if (!code.trim()) return say("tfMsg", T.tfErrEmpty);
  busy = true;
  const btn = $id("tfGo"); if (btn) btn.disabled = true;
  say("tfMsg", T.tfBusy, "busy");
  try{
    const data = await post("/api/me/2fa/enable", {setup: setup, code: code});
    showBackup(data.backup_codes || [], true);
  }catch(e){
    say("tfMsg", errText(e));
    if (e && e.code === "twofa_expired") setTimeout(startEnable, 1200);
  }
  busy = false;
  if (btn) btn.disabled = false;
}

/* ------------------------------------------------- запасні коди */

function showBackup(codes, fresh){
  const text = codes.join("\n");
  openModal(
    '<div class="m-head"><h2>' + esc(T.tfBackupTitle) + "</h2></div>"
    + '<div class="m-body st"><section class="st-sec tf">'
    +   (fresh ? '<p class="pw-msg ok tf-ok" role="status">' + esc(T.tfOnDone) + "</p>" : "")
    +   '<p class="tf-lead">' + esc(T.tfBackupLead) + "</p>"
    +   '<ul class="tf-codes" aria-label="' + esc(T.tfBackupTitle) + '">'
    +     codes.map(c => "<li><code>" + esc(c) + "</code></li>").join("")
    +   "</ul>"
    +   '<div class="pw-row">'
    +     '<button class="btn" type="button" id="tfCopyAll" data-lbl="' + esc(T.tfCopyAll) + '">' + esc(T.tfCopyAll) + "</button>"
    +     '<button class="btn" type="button" id="tfSave">' + esc(T.tfDownload) + "</button>"
    +   "</div>"
    + "</section></div>"
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn primary" type="button" id="tfDone">' + esc(T.tfDone) + "</button></div>");
  $id("tfCopyAll").onclick = e => copy(text, e.currentTarget);
  $id("tfSave").onclick = () => {
    const blob = new Blob(["StatsAI — " + T.tfBackupTitle + "\n\n" + text + "\n"], {type: "text/plain"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "statsai-backup-codes.txt";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  $id("tfDone").onclick = back;
}

/* ------------------------------- вимкнути / нові запасні — лише з кодом */

function askCode(kind){
  const off = kind === "disable";
  openModal(
    '<div class="m-head"><h2>' + esc(off ? T.tfDisableTitle : T.tfNewBackup) + "</h2>"
    + '<button class="x" type="button" id="tfX" aria-label="' + esc(T.pwBack) + '">×</button></div>'
    + '<div class="m-body st"><section class="st-sec tf">'
    +   '<p class="tf-lead">' + esc(off ? T.tfAskDisable : T.tfAskBackup) + "</p>"
    +   codeField("tfCode", T.tfCodeOrBackup)
    +   '<div class="pw-row"><span class="pw-msg" id="tfMsg" role="alert"></span></div>'
    + "</section></div>"
    + '<div class="m-foot"><button class="btn" type="button" id="tfBack">' + esc(T.pwBack) + "</button>"
    + '<span class="sp"></span>'
    + '<button class="btn ' + (off ? "danger" : "primary") + '" type="button" id="tfGo">'
    +   esc(off ? T.tfDisable : T.tfNewBackup) + "</button></div>");
  $id("tfX").onclick = back;
  $id("tfBack").onclick = back;
  const go = () => sendCode(kind);
  $id("tfGo").onclick = go;
  onEnter("tfCode", go);
  focusLater("tfCode");
}

async function sendCode(kind){
  if (busy) return;
  const code = ($id("tfCode") || {}).value || "";
  if (!code.trim()) return say("tfMsg", T.tfErrEmpty);
  busy = true;
  const btn = $id("tfGo"); if (btn) btn.disabled = true;
  say("tfMsg", T.tfBusy, "busy");
  try{
    const data = await post("/api/me/2fa/" + kind, {code: code});
    busy = false;
    if (kind === "backup") return showBackup(data.backup_codes || [], false);
    return back();
  }catch(e){
    say("tfMsg", errText(e));
  }
  busy = false;
  if (btn) btn.disabled = false;
}

/* ------------------------------------------- вийти на всіх пристроях */

async function logoutAll(){
  if (busy) return;
  const sure = window.Ask
    ? await Ask.yes(T.loAsk, {ok: T.loYes, cancel: T.askNo, danger: true})
    : confirm(T.loAsk);
  if (!sure) return;
  busy = true;
  const btn = $id("loAll"); if (btn) btn.disabled = true;
  try{
    await post("/api/me/logout-all");
    say("loMsg", T.loDone, true);
  }catch(e){
    say("loMsg", T.pwErrGeneric);
  }
  busy = false;
  if (btn) btn.disabled = false;
}

window.__twofa = {load: load, section: section, sessions: sessions, wire: wire};

})();
