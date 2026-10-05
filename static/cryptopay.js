/* ============================================================
   Оплата криптою: вибір способу і вікно переказу.

   Розділ «Підписка» доводить людину до кнопки «Оформити» — далі
   починається цей файл. Спершу питаємо, чим платити: карткою
   (Creem) чи криптою (USDT у мережі TRON). Карткою — віддаємо
   керування назад, у підписку, вона сама відкриє касу. Криптою —
   виставляємо рахунок і тримаємо вікно, поки йдуть гроші.

   Головне тут не розмітка, а чесний стан. Переказ у блокчейні —
   це не миттєва оплата: гроші йдуть, мережа підтверджує, наш
   обхід помічає. Усе це — хвилини, і всі ці хвилини людина має
   бачити, що відбувається, інакше вона вирішить, що гроші зникли.

   Тому екран каже стан трьома способами одразу: кружком, словом
   і таймером унизу. А коли гроші дійшли — великою галочкою й
   прямою фразою: «Оплата успішно пройшла».

   Вкладку можна закрити будь-коли: підписку вмикає фоновий обхід
   на сервері, а не ця сторінка. Вікно тут — для спокою людини,
   а не для роботи.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* Як часто перепитуємо сервер, поки чекаємо переказ. Шість секунд —
   компроміс: обхід блокчейну все одно ходить раз на півхвилини, а
   частіше питати нашу ж базу сенсу немає. */
const POLL = 6000;

/* Через скільки показувати «я вже переказав». Одразу — не варто: у
   переважній більшості випадків переказ знаходиться сам за хвилину, і
   поле для номера тільки збиває з пантелику. Але тому, хто округлив
   суму, воно потрібне — інакше його гроші не впізнає ніхто. */
const CLAIM_AFTER = 5 * 60;

let wrap = null;          /* вікно в DOM або null */
let S = null;             /* стан вікна */
let pollT = 0, tickT = 0;
let onKey = null;

/* ---------------------------------------------------------- значки ---- */
/* Малюємо самі: у журналі немає набору значків, а emoji в оплаті
   виглядають несерйозно рівно там, де серйозність потрібна найбільше. */
function svg(inner, size){
  const s = size || 20;
  return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none"'
    + ' stroke="currentColor" stroke-width="1.7" stroke-linecap="round"'
    + ' stroke-linejoin="round" aria-hidden="true">' + inner + "</svg>";
}
const icoCard  = () => svg('<rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M2 10h20"/>');
const icoCoin  = () => svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h3.2a1.8 1.8 0 010 3.6H9.5h3.4a1.8 1.8 0 010 3.6H9.5"/>');
const icoNext  = () => svg('<path d="M9 5l7 7-7 7"/>', 18);
const icoClose = () => svg('<path d="M6 6l12 12M18 6L6 18"/>', 17);
const icoCopy  = () => svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1"/>', 15);
const icoOk    = () => svg('<path d="M4 12.5l5 5L20 6.5"/>', 15);
const icoWarn  = () => svg('<path d="M10.3 3.9L2.5 17.4A1.9 1.9 0 004.2 20.3h15.6a1.9 1.9 0 001.7-2.9L13.7 3.9a1.9 1.9 0 00-3.4 0z"/><path d="M12 9.5v4M12 17h.01"/>', 17);
const icoDone  = () => svg('<path d="M4 12.5l5 5L20 6.5"/>', 30);

/* ------------------------------------------------------------ час ----- */
function fmt(sec){
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}
function left(){
  return S && S.endAt ? Math.max(0, (S.endAt - Date.now()) / 1000) : 0;
}

/* ---------------------------------------------------------- вікно ----- */
function mount(){
  if (wrap) return;
  wrap = document.createElement("div");
  wrap.className = "cpay-wrap";
  wrap.innerHTML = '<div class="cpay" role="dialog" aria-modal="true"></div>';
  /* Клік повз вікно закриває — але тільки повз: клік усередині не має
     гасити екран, на якому людина щойно скопіювала адресу. */
  wrap.addEventListener("mousedown", e => { if (e.target === wrap) close(); });
  document.body.appendChild(wrap);
  requestAnimationFrame(() => wrap && wrap.classList.add("in"));
  onKey = e => { if (e.key === "Escape"){ e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
}

function close(){
  if (pollT){ clearInterval(pollT); pollT = 0; }
  if (tickT){ clearInterval(tickT); tickT = 0; }
  if (onKey){ document.removeEventListener("keydown", onKey, true); onKey = null; }
  if (wrap){
    const w = wrap;
    wrap = null;
    w.classList.remove("in");
    setTimeout(() => w.remove(), 200);
  }
  S = null;
}

function render(){
  if (!wrap) return;
  const box = wrap.querySelector(".cpay");
  box.innerHTML = S.mode === "pick" ? pickBody()
                : S.mode === "card" ? cardBody() : payBody();
  bind();
  const first = box.querySelector("button:not(.cpay-x):not([disabled])");
  if (first) first.focus({preventScroll: true});
}

function head(title, sub){
  return '<div class="cpay-head"><div><h3>' + esc(title) + "</h3>"
    + (sub ? "<p>" + sub + "</p>" : "")
    + '</div><button type="button" class="cpay-x" data-x aria-label="'
    + esc(T.cpClose) + '">' + icoClose() + "</button></div>";
}

/* -------------------------------------------------- вибір способу ----- */
function pickBody(){
  const sub = '<span>' + esc(S.planName) + '</span> · <span class="cpay-sum">'
    + esc(S.priceText) + "</span>";
  const way = (kind, ico, t, x, off) =>
    '<button type="button" class="cpay-way' + (off ? " off" : "")
    + '" data-way="' + kind + '"' + (off ? " disabled" : "") + ">"
    + '<span class="cpay-way-ico">' + ico + "</span>"
    + '<span class="cpay-way-t"><b>' + esc(t) + "</b><span>" + esc(x) + "</span></span>"
    + '<span class="cpay-way-go">' + (off ? icoWarn() : icoNext()) + "</span></button>";
  /* Каса картками вимкнена на сервері — кажемо це на самій плитці.
     Клікабельна плитка, яка у відповідь не робить нічого, гірша за
     вимкнену: людина думає, що зламався журнал, а не що оплата ще не
     ввімкнена. */
  const off = S.cardOn === false;
  return head(T.cpPickT, sub)
    + '<div class="cpay-body"><div class="cpay-ways">'
    + way("card", icoCard(), T.cpCardT, off ? T.subSoon : T.cpCardX, off)
    + way("crypto", icoCoin(), T.cpCryptoT, T.cpCryptoX)
    + "</div></div>";
}

/* Екран каси картками: поки сервер її створює — чекаємо, не вийшло —
   кажемо чому. Вікно при цьому не закриваємо: закрите вікно і є те
   «нічого не сталося», на яке скаржились. */
function cardBody(){
  const sub = '<span>' + esc(S.planName) + '</span> · <span class="cpay-sum">'
    + esc(S.priceText) + "</span>";
  if (!S.msg){
    /* Перехід не стався за чотири секунди — віддаємо адресу каси руками.
       Автоматичний перехід інколи не відбувається (розширення, блокувальник),
       і тоді людина сидить перед написом «відкриваємо» без жодного виходу. */
    const by_hand = S.slow && S.url
      ? '<div class="cpay-act"><a class="cpay-btn" href="' + esc(S.url)
        + '" target="_blank" rel="noopener">' + esc(T.cpCardOpen) + "</a></div>"
      : "";
    return head(T.cpPickT, sub)
      + '<div class="cpay-body"><div class="cpay-state wait">'
      + '<span class="cpay-dot"></span><div><b>' + esc(T.cpCardGo) + "</b></div></div>"
      + by_hand + "</div>";
  }
  return head(T.cpPickT, sub)
    + '<div class="cpay-body"><div class="cpay-state dead">'
    + '<span class="cpay-dot"></span><div><b>' + esc(S.msg) + "</b></div></div>"
    + '<div class="cpay-act"><button type="button" class="cpay-btn" data-x>'
    + esc(T.cpClose) + "</button></div></div>";
}

/* --------------------------------------------------- вікно переказу --- */
function steps(){
  const n = S.state === "done" ? 3 : S.state === "check" ? 2 : 1;
  const one = (i, t) => '<span class="cpay-step ' + (i < n ? "done" : i === n ? "on" : "")
    + '"><i></i>' + esc(t) + "</span>";
  return '<div class="cpay-steps">' + one(1, T.cpStep1) + "<hr>"
    + one(2, T.cpStep2) + "<hr>" + one(3, T.cpStep3) + "</div>";
}

function fld(cls, label, value, copy, hint){
  return '<div class="cpay-fld ' + cls + '"><div class="cpay-lbl">' + esc(label) + "</div>"
    + '<div class="cpay-val"><b>' + value + "</b>"
    + (copy ? '<button type="button" class="cpay-copy" data-copy="' + esc(copy) + '">'
        + icoCopy() + "<span>" + esc(T.cpCopy) + "</span></button>" : "")
    + "</div>"
    + (hint ? '<p class="cpay-hint">' + esc(hint) + "</p>" : "")
    + "</div>";
}

/* «Скасувати рахунок?» — питаємо на місці, у тому ж вікні. Окреме
   віконце поверх цього стало б другим шаром поверх налаштувань, а
   питання тут маленьке й стосується того, на що людина дивиться. */
function askBody(){
  return '<div class="cpay-body">'
    + '<div class="cpay-state"><span class="cpay-dot"></span><div><b>'
    + esc(T.cpCancelQ) + "</b><p>" + esc(T.cpCancelX) + "</p></div></div>"
    + '<div class="cpay-act">'
    +   '<button type="button" class="cpay-btn ghost" data-keep>'
    +     esc(T.cpCancelNo) + "</button>"
    +   '<button type="button" class="cpay-btn" data-cancel-yes>'
    +     esc(T.cpCancelYes) + "</button>"
    + "</div></div>";
}

function okBody(){
  return '<div class="cpay-body">' + steps()
    + '<div class="cpay-ok"><div class="cpay-ok-ring">' + icoDone() + "</div>"
    + "<h4>" + esc(T.cpDone) + "</h4><p>" + esc(T.cpDoneX) + "</p></div>"
    + '<div class="cpay-act"><button type="button" class="cpay-btn" data-x>'
    + esc(T.cpGo) + "</button></div></div>";
}

function deadBody(){
  return '<div class="cpay-body">'
    + '<div class="cpay-state dead"><span class="cpay-dot"></span><div>'
    + "<b>" + esc(T.cpDead) + "</b><p>" + esc(T.cpDeadX) + "</p></div></div>"
    + claimBox(true)
    + '<div class="cpay-act">'
    + '<button type="button" class="cpay-btn ghost" data-x>' + esc(T.cpClose) + "</button>"
    + '<button type="button" class="cpay-btn" data-again>' + esc(T.cpAgain) + "</button>"
    + "</div></div>";
}

/* «Я вже переказав»: поле для номера переказу. Відкрите не одразу —
   спершу даємо мережі час знайти гроші самій. */
function claimBox(open){
  const show = open || S.claim;
  return '<div class="cpay-claim">'
    + (show
        ? '<label class="cpay-lbl" for="cpayTx">' + esc(T.cpTxLbl) + "</label>"
          + '<div class="cpay-tx"><input id="cpayTx" type="text" spellcheck="false"'
          + ' autocomplete="off" maxlength="80" placeholder="' + esc(T.cpTxPh) + '">'
          + '<button type="button" data-claim>' + esc(T.cpTxGo) + "</button></div>"
          + '<p class="cpay-hint">' + esc(T.cpTxHint) + "</p>"
        : '<button type="button" class="cpay-claim-go" data-open-claim>'
          + esc(T.cpPaidQ) + "</button>")
    + (S.msg ? '<p class="cpay-msg" role="alert">' + esc(S.msg) + "</p>" : "")
    + "</div>";
}

function payBody(){
  const sub = '<span>' + esc(S.planName) + "</span>"
    + (S.priceText ? ' · <span class="cpay-sum">' + esc(S.priceText) + "</span>" : "");
  const body = S.state === "done" ? okBody()
             : S.state === "dead" ? deadBody()
             : S.asking ? askBody()
             : liveBody();
  return head(T.cpT, sub) + body + (S.state === "done" || S.state === "dead" ? "" : foot());
}

function liveBody(){
  const inv = S.inv;
  const checking = S.state === "check";
  return '<div class="cpay-body">' + steps()
    + '<div class="cpay-grid">'
    +   fld("hot", T.cpAmount,
            esc(inv.amount_text) + "<em>" + esc(inv.coin) + "</em>",
            inv.amount_text, T.cpExact)
    +   fld("cpay-addr", T.cpAddr, esc(inv.wallet), inv.wallet, "")
    +   '<div class="cpay-two">'
    +     fld("", T.cpNet, esc(inv.network), "", "")
    +     fld("", T.cpCoin, esc(inv.coin), "", "")
    +   "</div>"
    + "</div>"
    + '<div class="cpay-warn">' + icoWarn()
    +   "<div><p>" + esc(T.cpWarn) + "</p><p>" + esc(T.cpFee) + "</p></div></div>"
    + '<div class="cpay-state ' + (checking ? "check" : "wait") + '">'
    +   '<span class="cpay-dot"></span><div><b>'
    +   esc(checking ? T.cpCheck : T.cpWait) + "</b><p>"
    +   esc(checking ? T.cpCheckX : T.cpWaitX) + "</p></div></div>"
    + claimBox(false)
    /* Вихід із очікування. Тихо й унизу: передумати можна, але це не те,
       заради чого сюди прийшли. */
    + '<div class="cpay-off"><button type="button" class="cpay-claim-go" data-cancel>'
    +   esc(T.cpCancel) + "</button></div>"
    + "</div>";
}

/* Таймер унизу: скільки ще тримається виставлена сума. */
function foot(){
  const sec = left();
  const low = sec <= 120;
  const part = S.total ? Math.max(0, Math.min(1, sec / S.total)) : 0;
  return '<div class="cpay-foot' + (low ? " low" : "") + '">'
    + '<div class="cpay-time' + (low ? " low" : "") + '">'
    +   "<span>" + esc(T.cpLeft) + "</span><b>" + fmt(sec) + "</b></div>"
    + '<div class="cpay-bar"><i style="width:' + (part * 100).toFixed(2) + '%"></i></div>'
    + "</div>";
}

/* Раз на секунду оновлюємо тільки цифри, не перемальовуючи вікно: інакше
   курсор вилітав би з поля для номера переказу щосекунди. */
function tick(){
  if (!wrap || !S || S.mode !== "pay") return;
  const sec = left();
  const t = wrap.querySelector(".cpay-time b");
  if (t) t.textContent = fmt(sec);
  const bar = wrap.querySelector(".cpay-bar i");
  if (bar && S.total) bar.style.width = (Math.max(0, Math.min(1, sec / S.total)) * 100).toFixed(2) + "%";
  const low = sec <= 120;
  const row = wrap.querySelector(".cpay-time");
  if (row) row.classList.toggle("low", low);
  const ft = wrap.querySelector(".cpay-foot");
  if (ft) ft.classList.toggle("low", low);
  /* Час вийшов — сума більше не наша, рахунок треба виставляти наново. */
  if (sec <= 0 && (S.state === "wait" || S.state === "check")){
    S.state = "dead";
    render();
    return;
  }
  /* Поле «я вже переказав» з'являється не одразу, а коли чекати вже довго. */
  if (!S.claim && S.total && (S.total - sec) >= CLAIM_AFTER){
    const b = wrap.querySelector("[data-open-claim]");
    if (b){ S.claim = true; render(); }
  }
}

/* ------------------------------------------------------- перевірка ---- */
/* Сервер — єдине джерело правди: гроші помічає фоновий обхід, а не ця
   сторінка. Ми лише питаємо, що він уже знає. */
async function poll(){
  if (!wrap || !S || S.mode !== "pay") return;
  let r;
  try{ r = await api("GET", "/api/billing/state"); }
  catch(e){ return; }                     /* не відповіло — спитаємо за шість секунд */
  if (!wrap || !S) return;
  const inv = r && r.invoice;
  if (inv && S.inv && inv.id === S.inv.id){
    /* Рахунок ще чекає. Годинник беремо серверний: вкладка могла спати,
       і локальний відлік за цей час збився б. */
    S.inv = inv;
    S.endAt = Date.now() + inv.seconds_left * 1000;
    return;
  }
  /* Підписка стала іншою, ніж була, коли ми відкривали вікно, — значить
     гроші дійшли. Просто «active» тут не годиться: той, хто продовжує
     підписку наперед, був активним і до переказу, і одного цього слова
     вистачило б, щоб показати йому «оплачено» задарма. */
  if (r && r.active && changed(r)){ win(); return; }
  /* Рахунку на сервері вже немає, а час іще є — мовчки чекаємо далі.
     Годинники в нас і на сервері збігаються не до секунди, і оголошувати
     через це «час вийшов» зарано: відлік унизу сам скаже, коли справді
     вийшов. */
}

function changed(r){
  if (!S.wasLive) return true;            /* був без підписки — тепер із нею */
  if (r.plan !== S.plan0) return true;    /* перейшов на інший тариф */
  return !!(r.paid_until && r.paid_until !== S.until0);
}

/* Гроші дійшли. */
function win(){
  S.state = "done";
  S.msg = "";
  if (pollT){ clearInterval(pollT); pollT = 0; }
  if (tickT){ clearInterval(tickT); tickT = 0; }
  render();
  /* Розділ «Підписка» і обідок навколо аватарки мають одразу показати
     нову підписку — інакше під вікном лишиться вчорашня правда. */
  if (window.__sub && __sub.load)
    __sub.load().then(() => {
      if (__sub.badge) __sub.badge();
      if (__sub.redraw) __sub.redraw();
    }).catch(() => {});
}

/* ---------------------------------------------------------- події ----- */
function bind(){
  const box = wrap && wrap.querySelector(".cpay");
  if (!box) return;

  box.querySelectorAll("[data-x]").forEach(b =>
    b.addEventListener("click", close));

  box.querySelectorAll("[data-way]").forEach(b =>
    b.addEventListener("click", async () => {
      if (b.dataset.way === "card"){
        const go = S.onCard;
        if (!go) return close();
        /* Касу відкриває «Підписка», але чекаємо її тут: вона або
           відправляє людину на Creem, або повертає причину — і причину
           має бачити те саме вікно, в якому натиснули. */
        S.mode = "card";
        S.msg = "";
        render();
        const res = (await go()) || {};
        if (!wrap || !S || S.mode !== "card") return;
        if (res.url){                   /* касу дали — чекаємо переходу */
          S.url = res.url;
          setTimeout(() => {
            if (wrap && S && S.mode === "card" && !S.msg){ S.slow = true; render(); }
          }, 4000);
          return;
        }
        S.msg = res.why || T.subPayFail;
        render();
      } else {
        start(S.plan, S.planName, S.priceText);
      }
    }));

  box.querySelectorAll("[data-copy]").forEach(b =>
    b.addEventListener("click", () => copy(b)));

  const again = box.querySelector("[data-again]");
  if (again) again.addEventListener("click", () =>
    start(S.plan, S.planName, S.priceText));

  const off = box.querySelector("[data-cancel]");
  if (off) off.addEventListener("click", () => { S.asking = true; render(); });

  const keep = box.querySelector("[data-keep]");
  if (keep) keep.addEventListener("click", () => { S.asking = false; render(); });

  const yes = box.querySelector("[data-cancel-yes]");
  if (yes) yes.addEventListener("click", () => {
    yes.disabled = true;
    drop();
  });

  const opener = box.querySelector("[data-open-claim]");
  if (opener) opener.addEventListener("click", () => { S.claim = true; render(); });

  const go = box.querySelector("[data-claim]");
  if (go){
    const inp = box.querySelector("#cpayTx");
    go.addEventListener("click", () => claim(go, inp));
    inp.addEventListener("keydown", e => { if (e.key === "Enter") claim(go, inp); });
  }
}

/* Погасити рахунок. Гроші, які вже пішли, від цього не пропадають:
   сервер тримає скасований рахунок ще добу й закриє його переказом,
   коли той дійде. */
async function drop(){
  try{ await api("POST", "/api/billing/crypto/cancel"); }
  catch(e){}
  close();
  if (window.__sub && __sub.load)
    __sub.load().then(() => { if (__sub.redraw) __sub.redraw(); }).catch(() => {});
}

/* Копіювання: сучасний спосіб із запасним на випадок відмови — адресу
   гаманця людина мусить отримати за будь-якої погоди. */
function copy(btn){
  const text = btn.dataset.copy || "";
  const done = () => {
    btn.classList.add("ok");
    const lab = btn.querySelector("span");
    if (lab) lab.textContent = T.cpCopied;
    setTimeout(() => {
      btn.classList.remove("ok");
      if (lab) lab.textContent = T.cpCopy;
    }, 1800);
  };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done, () => fallback(text, done));
  } else fallback(text, done);
}
function fallback(text, done){
  const a = document.createElement("textarea");
  a.value = text;
  a.setAttribute("readonly", "");
  a.style.cssText = "position:fixed;top:-1000px;opacity:0";
  document.body.appendChild(a);
  a.select();
  try{ document.execCommand("copy"); done(); }catch(e){}
  a.remove();
}

/* «Я вже переказав, ось номер». Перевіряє сервер у блокчейні — на слово
   тут не вірять, і правильно роблять. */
async function claim(btn, inp){
  const tx = (inp.value || "").trim();
  if (!tx || btn.disabled) return;
  btn.disabled = true;
  S.msg = "";
  S.state = "check";
  render();
  try{
    await api("POST", "/api/billing/crypto/claim", {tx: tx});
    win();
  }catch(e){
    if (!wrap || !S) return;
    S.state = left() > 0 ? "wait" : "dead";
    S.claim = true;
    S.msg = T["cpErr_" + ((e && e.code) || "")] || T.cpErrAny;
    render();
    const again = wrap.querySelector("#cpayTx");
    if (again){ again.value = tx; again.focus(); }
  }
}

/* ------------------------------------------------------- запуск ------- */
/* Виставляємо рахунок і відкриваємо вікно переказу. */
async function start(plan, planName, priceText){
  mount();
  S = {mode: "pay", plan: plan, planName: planName, priceText: priceText,
       inv: null, endAt: 0, total: 0, state: "wait", claim: false, msg: ""};
  wrap.querySelector(".cpay").innerHTML = head(T.cpT, "")
    + '<div class="cpay-body"><div class="cpay-state wait">'
    + '<span class="cpay-dot"></span><div><b>' + esc(T.cpMaking) + "</b></div></div></div>";
  bind();
  let inv;
  try{ inv = await api("POST", "/api/billing/crypto", {plan: plan}); }
  catch(e){
    if (!wrap) return;
    wrap.querySelector(".cpay").innerHTML = head(T.cpT, "")
      + '<div class="cpay-body"><div class="cpay-state dead">'
      + '<span class="cpay-dot"></span><div><b>' + esc(T.cpFail) + "</b></div></div>"
      + '<div class="cpay-act"><button type="button" class="cpay-btn" data-x>'
      + esc(T.cpClose) + "</button></div></div>";
    bind();
    return;
  }
  if (!wrap) return;
  show(inv, planName, priceText);
}

/* Показати вже виставлений рахунок: після перезавантаження сторінки або
   зі смужки в розділі «Підписка». */
function show(inv, planName, priceText){
  mount();
  /* Якою підписка була до переказу — щоб потім упізнати, що вона стала
     іншою. Без цієї мітки продовження наперед виглядало б оплаченим ще
     до того, як гроші вийшли з гаманця. */
  const was = (window.__sub && __sub.state && __sub.state()) || {};
  S = {mode: "pay", plan: inv.plan, planName: planName || "", priceText: priceText || "",
       inv: inv, endAt: Date.now() + inv.seconds_left * 1000,
       total: inv.seconds_left || 1, state: "wait", claim: false, msg: "",
       wasLive: !!was.active, plan0: was.plan || "", until0: was.paid_until || null};
  render();
  if (tickT) clearInterval(tickT);
  if (pollT) clearInterval(pollT);
  tickT = setInterval(tick, 1000);
  pollT = setInterval(poll, POLL);
}

/* Вибір способу. Карткою — повертаємо керування в «Підписку»: касу
   відкриває вона, і робить це рівно так само, як робила завжди. */
function choose(plan, planName, priceText, onCard, cardOn){
  mount();
  S = {mode: "pick", plan: plan, planName: planName, priceText: priceText,
       onCard: onCard, cardOn: cardOn !== false, msg: ""};
  render();
}

window.__cpay = {choose: choose, open: start, show: show, close: close};

})();
