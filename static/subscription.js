/* ============================================================
   Розділ «Підписка» у вікні налаштувань + значок тарифу біля ніка.

   Влаштований як backup.js: load() читає стан, section() віддає
   розмітку, wire() чіпляє події вже після вставки.

   Ціни приходять із сервера (/api/billing/state), а не зашиті тут:
   у людини може бути свій набір — «ранні» платять менше назавжди, —
   і браузер не має про це здогадуватись сам.

   Лічильників тут немає жодних — ні по угодах, ні по зверненнях до
   помічника (рішення власника 22 і 23.09.2026). Про вичерпане людина
   дізнається з відмови, а не з цифри, яка щодня зменшується.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const inPub = () => !!(window.Pub && window.Pub.on);

/* Скільки місяців у тарифі — щоб показати ціну «за місяць». */
const MONTHS = {month: 1, quarter: 3, year: 12};
const ORDER = ["month", "quarter", "year"];

let st = null;                     /* останній стан із сервера */

async function load(){
  if (inPub()){ st = null; return null; }
  try{ st = await api("GET", "/api/billing/state"); }
  catch(e){ st = null; }           /* не відповіло — розділ просто не малюємо */
  return st;
}

/* €11,99 — кома, як у решті журналу, і без зайвого нуля в кінці. */
function money(cents){
  const s = (cents / 100).toFixed(2).replace(".", ",");
  return "€" + s;
}

function tick(){
  return '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"'
    + ' stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M3 8.5l3.5 3.5L13 4.5"/></svg>';
}

/* Дата «до 22.09.2027» — коротко, цифрами: її читають боком ока. */
function till(iso){
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = n => String(n).padStart(2, "0");
  return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear();
}

/* Підпис тарифу: «Безкоштовно» або «Рік · до 22.09.2027». */
function planLabel(){
  if (!st || !st.active) return T.subFree;
  const name = {month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[st.plan] || "";
  const d = st.paid_until ? till(st.paid_until) : "";
  return name + (d ? " · " + T.subTill + " " + d : "");
}

/* Значок тарифу: FREE / 1М / 3М / 12М. Без слів і без дати — дата живе
   у підказці й у самому розділі.

   Не кнопка, а span: значок стоїть усередині плашки профілю, а кнопка в
   кнопці — розмітка, яку браузер розбирає як доведеться. Мишею він веде
   в «Підписку», з клавіатури спрацьовує сама плашка. */
function badge(){
  if (!st) return "";
  const sign = st.active ? {month: "1М", quarter: "3М", year: "12М"}[st.plan] : "FREE";
  if (!sign) return "";
  const cls = "sub-tier" + (st.active ? " on" : "") + (st.plan === "year" ? " y" : "");
  return '<span class="' + cls + '" data-tip="' + esc(planLabel()) + '"'
    + ' title="' + esc(T.subTitle + " · " + planLabel()) + '"'
    + ' onclick="event.stopPropagation();__settings.open(&quot;subscription&quot;)">'
    + esc(sign) + "</span>";
}

function card(plan){
  const p = st.prices[plan];
  if (!p) return "";
  const per = Math.round(p.cents / MONTHS[plan]);
  const best = plan === "year";
  const gift = best
    ? '<span class="sub-gift">' + esc(st.prices.set === "early" ? T.subYourPrice : T.subGift) + "</span>"
    : "";
  /* Під ціною — сума, яку справді спишуть. Перекреслених «було/стало»
     тут немає: власник прибрав їх 23.09.2026, лишається тільки ціна. */
  const bill = ({month: T.subBillM, quarter: T.subBillQ, year: T.subBillY}[plan] || "")
    .replace("%s", money(p.cents));
  const name = {month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[plan];
  /* Копійки дрібнішим кеглем: у ціні головне ціле число, «,99» —
     хвіст, який не має сперечатися з ним за увагу. */
  const whole = Math.floor(per / 100);
  const cents = String(per % 100).padStart(2, "0");
  return '<div class="sub-plan' + (best ? " best" : "") + '" data-p="' + plan + '">'
    + gift
    + '<div class="sub-bg" aria-hidden="true"><span class="sub-word">StatsAI</span></div>'
    + '<div class="sub-name">' + esc(name) + "</div>"
    + '<div class="sub-cost"><span class="cur">€</span>'
    +   '<span class="val">' + whole + '<span class="cc">,' + cents + "</span></span>"
    +   '<span class="cnt">' + esc(T.subPerMonth) + "</span></div>"
    + '<div class="sub-bill">' + esc(bill) + "</div>"
    + '<button type="button" class="sub-btn" data-buy="' + plan + '">' + esc(T.subBuy) + "</button>"
    + "</div>";
}

/* Що дається без підписки. Це умови, а не лічильник: числа беремо
   з сервера, щоб змінений ліміт не залишив тут стару обіцянку. */
function freeTerms(){
  const f = st && st.free;
  if (!f || !f.trades) return "";
  const rows = [
    T.subFreeTrades.replace("%d", f.trades),
    T.subFreeBt.replace("%d", f.bt),
    T.subFreeImports.replace("%d", f.imports).replace("%d", f.import_days),
    T.subFreeAi.replace("%d", f.ai),
  ];
  return '<div class="sub-fhead">' + esc(T.subFreeHead) + "</div>"
    + '<ul class="sub-free">' + rows.map(r => "<li>" + r + "</li>").join("") + "</ul>";
}

function feats(){
  const rows = [T.subF1, T.subF2, T.subF3, T.subF4];
  return '<div class="sub-fhead">' + esc(T.subOpens) + "</div>"
    + '<ul class="sub-feats">'
    + rows.map(r => "<li>" + tick() + "<span>" + r + "</span></li>").join("")
    + "</ul>";
}

/* Порожній рядок означає «показувати нема чого»: чужий журнал або
   сервер не відповів. */
/* Промокод — під картками, бо міняє саме їх: людина дивиться на ціни, і
   те, що їх змінює, має лежати поруч, а не в кінці розділу.

   Поле відкрите завжди. Ховати його за посиланням означало б, що той, у
   кого код є, мусить спершу здогадатися його шукати.

   Показуємо тільки тим, у кого звичайні ціни: у решти вже знижений набір,
   і поле нічого б не змінило. Після вдалого коду на його місці лишається
   підтвердження — зникати мовчки не можна, людина не зрозуміє, спрацювало
   чи ні.
*/
let promoDone = false;

function promoRow(){
  if (!st || !st.prices) return "";
  if (promoDone)
    return '<div class="sub-promo done">' + tick()
      + '<span>' + esc(T.subPromoOk) + '</span></div>';
  if (st.prices.set !== "std") return "";
  return '<div class="sub-promo" id="subPromo">'
    + '<label class="sub-promo-lbl" for="subPromoIn">' + esc(T.subPromoLbl) + '</label>'
    + '<div class="sub-promo-row">'
    +   '<input id="subPromoIn" class="sub-promo-in" type="text" autocomplete="off"'
    +     ' spellcheck="false" maxlength="32" placeholder="' + esc(T.subPromoPh) + '">'
    +   '<button type="button" class="sub-promo-go">' + esc(T.subPromoGo) + '</button>'
    + '</div>'
    + '<p class="sub-promo-msg" role="alert" hidden></p>'
    + '</div>';
}

/* Кнопка ведення підписки. Показуємо тільки тому, хто вже платив: до
   першої оплати кабінету на боці Creem просто не існує. Саме тут людина
   скасує продовження чи замінить картку — без листів у підтримку. */
function manageBtn(){
  if (!st || !st.portal) return "";
  return '<button type="button" class="sub-manage" id="subManage">'
    +   esc(T.subManage) + "</button>";
}

function section(){
  if (!st) return "";
  return '<div class="sub-state"><span class="sub-chip' + (st.active ? " paid" : "") + '">'
    +   esc(planLabel()) + "</span>" + manageBtn() + "</div>"
    + '<div class="sub-plans">' + ORDER.map(card).join("") + "</div>"
    + promoRow()
    + feats()
    + freeTerms()
    + '<p class="sub-soon" id="subSoon"></p>'
    /* Умови й повернення мають бути видно поруч із кнопкою оплати, а не
       ховатись у підвалі: цього вимагає і платіжний сервіс, і здоровий глузд
       — людина читає їх саме тоді, коли збирається платити. */
    + '<p class="sub-legal">'
    +   '<a href="/terms" target="_blank" rel="noopener">' + esc(T.subTerms) + '</a>'
    +   '<span>·</span>'
    +   '<a href="/refund" target="_blank" rel="noopener">' + esc(T.subRefund) + '</a>'
    + '</p>';
}

/* Ціни змінились — перемальовуємо розділ на місці. Вікно налаштувань
   бере розмітку один раз, при відкритті, тому оновити його інакше нема як. */
function redraw(){
  const host = document.querySelector(".st-sec.sub");
  if (!host) return;
  host.innerHTML = section();
  wire();
  if (window.__sub && __sub.badge) badge();
}

function wirePromo(){
  const box = document.getElementById("subPromo");
  if (!box) return;
  const inp = box.querySelector(".sub-promo-in");
  const go = box.querySelector(".sub-promo-go");
  const msg = box.querySelector(".sub-promo-msg");

  const send = async () => {
    const code = inp.value.trim();
    if (!code || go.disabled) return;
    go.disabled = true;                /* видно, що запит пішов */
    msg.hidden = true;
    try{
      st = await api("POST", "/api/billing/promo", {code: code});
      promoDone = true;
      redraw();                        /* картки вже з новими сумами */
    }catch(e){
      /* Сервер каже кодом, слова до нього лежать тут — трьома мовами. */
      msg.textContent = T["subPromo_" + ((e && e.code) || "")] || T.subPromo_promo_bad;
      msg.hidden = false;
      go.disabled = false;
      inp.focus();
      inp.select();
    }
  };
  go.addEventListener("click", send);
  inp.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
}

function wireManage(){
  const b = document.getElementById("subManage");
  if (!b) return;
  b.addEventListener("click", async () => {
    const note = document.getElementById("subSoon");
    if (note) note.textContent = "";
    b.disabled = true;
    try{
      const r = await api("POST", "/api/billing/portal");
      if (!r || !r.url) throw new Error("no url");
      /* Кабінет чужий, тому окремою вкладкою: журнал лишається відкритим,
         і повернутись у нього можна не втрачаючи місця. */
      window.open(r.url, "_blank", "noopener");
    }catch(err){
      if (note) note.textContent = T.subManageFail;
    }finally{
      b.disabled = false;
    }
  });
}

function wire(){
  wirePromo();
  wireManage();
  const box = document.querySelector(".sub-plans");
  if (!box) return;
  box.addEventListener("click", async e => {
    const b = e.target.closest("[data-buy]");
    if (!b || b.disabled) return;
    const note = document.getElementById("subSoon");
    if (note) note.textContent = "";
    /* Гасимо кнопку одразу: касу створює сервер, це пів секунди, і за цей
       час нетерплячий устигає натиснути тричі й завести три оплати. */
    b.disabled = true;
    try{
      const r = await api("POST", "/api/billing/checkout", {plan: b.dataset.buy});
      if (!r || !r.url) throw new Error("no url");
      location.href = r.url;            /* далі вже сторінка Creem */
    }catch(err){
      b.disabled = false;
      if (note)
        note.textContent = (err && err.code === "no_pay") ? T.subSoon : T.subPayFail;
    }
  });
}

/* ============================================================
   Повернення з каси.

   Гроші й звістка про них приходять різними шляхами: людину Creem
   повертає на сайт одразу, а підтвердження нам шле окремим запитом, і
   воно може спізнитись на секунду-другу. Якщо просто відкрити журнал,
   людина побачить, що підписки немає, і вирішить, що гроші пропали.

   Тому: чекаємо й перепитуємо сервер, а на екрані тримаємо смужку, яка
   чесно каже, що відбувається.
   ============================================================ */
const PAID_TRIES = 12;                 /* ~25 секунд, далі вже не наша швидкість */

function paidNote(kind){
  let el = document.querySelector(".sub-paid");
  if (!el){
    el = document.createElement("div");
    el.className = "sub-paid";
    document.body.appendChild(el);
  }
  el.dataset.kind = kind;
  el.textContent = kind === "ok" ? T.subPaidOk
                 : kind === "slow" ? T.subPaidSlow : T.subPaidWait;
  if (kind !== "wait") setTimeout(() => el.remove(), 7000);
}

async function afterPay(){
  paidNote("wait");
  for (let i = 0; i < PAID_TRIES; i++){
    await new Promise(r => setTimeout(r, 2000));
    try{ await load(); }catch(e){ continue; }
    if (st && st.active){
      badge();
      paidNote("ok");
      return;
    }
  }
  paidNote("slow");
}

window.__sub = {load: load, section: section, wire: wire, badge: badge,
                state: () => st};

/* Стан читаємо одразу, не чекаючи, поки відкриють налаштування: значок
   тарифу стоїть у верхній смузі й має бути там з першої секунди. */
load().then(() => { if (window.__sideMe) __sideMe.tier(); }).catch(() => {});


/* Повернення з оплати: Creem додає наш хвостик ?paid=1. Прибираємо його
   з адреси одразу, щоб оновлення сторінки не запускало перевірку знову. */
(function(){
  if (!/[?&]paid=1/.test(location.search)) return;
  const clean = location.pathname
    + location.search.replace(/([?&])paid=1&?/, "$1").replace(/[?&]$/, "")
    + location.hash;
  history.replaceState(null, "", clean);
  if (window.Pub && Pub.on) return;
  afterPay();
})();

})();
