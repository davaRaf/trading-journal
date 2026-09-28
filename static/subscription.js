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
let real = null;                   /* той самий стан без перегляду «як у іншого» */

/* Перегляд для власників: подивитись журнал очима людини з іншим тарифом.
   Лише показ у цьому браузері — сервер права не змінює, ліміти рахує як є. */
const PREVIEW_KEY = "sub_preview";
const PREVIEWS = ["", "free", "early", "month", "quarter", "year", "life"];
function previewOf(){ try{ return localStorage.getItem(PREVIEW_KEY) || ""; }catch(e){ return ""; } }
function withPreview(s){
  const p = s && s.admin ? previewOf() : "";
  if (!p) return s;
  const soon = new Date(Date.now() + ({month: 30, quarter: 91, year: 365}[p] || 0) * 864e5).toISOString();
  /* «Безкоштовно» — новенький без знижок і промокоду (звичайні ціни),
     «Перші клієнти» — безкоштовний з їхніми цінами: як виглядатиме магазин */
  if ((p === "free" || p === "early") && s.prices){
    const pr = Object.assign({}, s.prices, {set: p === "early" ? "early" : "std"});
    for (const k in pr) if (pr[k] && pr[k].std_cents)
      pr[k] = Object.assign({}, pr[k], {cents: p === "early" && s.early ? s.early[k] : pr[k].std_cents});
    return Object.assign({}, s, {plan: "free", active: false, paid_until: null, prices: pr, preview: p});
  }
  return Object.assign({}, s, p === "free" ? {plan: "free", active: false, paid_until: null}
    : p === "life" ? {plan: "life", active: true, paid_until: null}
    : {plan: p, active: true, paid_until: soon}, {preview: p});
}

async function load(){
  if (inPub()){ st = null; return null; }
  try{ real = await api("GET", "/api/billing/state"); st = withPreview(real); }
  catch(e){ st = null; }           /* не відповіло — розділ просто не малюємо */
  return st;
}

function setPreview(p){
  try{ p ? localStorage.setItem(PREVIEW_KEY, p) : localStorage.removeItem(PREVIEW_KEY); }catch(e){}
  st = withPreview(real);
  redraw();
  if (window.__sideMe) __sideMe.tier();
}

function previewBox(){
  if (!real || !real.admin) return "";
  const cur = previewOf();
  const name = p => p === "" ? T.subPrevReal : p === "free" ? T.subFree : p === "early" ? T.subPrevEarly
    : p === "life" ? "Special" : {month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[p];
  return '<div class="sub-prev"><span>' + esc(T.subPrevLab) + "</span><div>"
    + PREVIEWS.map(p => '<button type="button" class="' + (p === cur ? "on" : "") + '" data-prev="' + p + '">'
      + esc(name(p)) + "</button>").join("") + "</div></div>";
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
  if (st.plan === "life") return T.subLife;      /* строку немає — і дати немає */
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
  ring();
  /* Варіант «Б» (рішення власника 28.09.2026): окремого значка перед
     аватаркою немає — тариф тихо підписаний під ніком замість слова
     «Профіль». Special (довічна, яку ми даємо руками) — золотом. */
  const sub = document.getElementById("sideMeSub");
  if (sub){
    const life = st.active && st.plan === "life";
    sub.textContent = !st.active ? T.subTagFree
      : life ? "Special"
      : "Pro · " + ({month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[st.plan] || "").toLowerCase();
    sub.classList.toggle("sub-special", life);
  }
  return "";
}

/* Обідок навколо аватарки — знак того, що підписка діє (рішення власника
   27.09.2026). Колір беремо з оформлення, тому він свій у кожній темі;
   у довічної обідок окремий, теплий — статус, якого не купують.

   Клас чіпляємо на місце аватарки, а не малюємо обідок у sideme.js: там
   профіль, а хто платить — знає тільки цей файл. Стан підписки приїжджає
   пізніше за профіль, тому дзвонимо звідси щоразу, коли малюємо значок. */
function ring(){
  const av = document.getElementById("sideMeAv");
  if (!av) return;
  const life = !!(st && st.active && st.plan === "life");
  av.classList.toggle("sub-live", !!(st && st.active) && !life);
  av.classList.toggle("sub-life", life);
}

function card(plan){
  const p = st.prices[plan];
  if (!p) return "";
  const per = Math.round(p.cents / MONTHS[plan]);
  const best = plan === "year";
  /* Чи є що показувати перекресленим. Знижка живе не в картці, а в наборі
     цін людини: 'early' у тих, хто був до платних підписок, 'fxlab' — у тих,
     хто ввів промокод. У звичайному наборі перекреслювати нічого. */
  const cut = st.prices.set !== "std" && p.std_cents > p.cents;
  const gift = best
    ? '<span class="sub-gift">' + esc(cut ? T.subYourPrice : T.subGift) + "</span>"
    : "";
  /* Скільки коштує місяць без знижки — і скільки відсотків вона знімає.
     Рахуємо від сум, які прийшли з сервера: інакше зміна ціни в config.py
     лишила б тут неправду.

     Перекреслене стоїть під ціною, а не поруч із нею: у картці головне
     число — своя ціна, а «було» тільки пояснює, від чого рахується вигода.
     У звичайному наборі цього рядка немає зовсім (власник прибрав «було/
     стало» 23.09.2026) — там перекреслювати нічого. */
  const was = cut
    ? '<div class="sub-wasrow"><s class="sub-was">'
      + money(Math.round(p.std_cents / MONTHS[plan])) + "</s>"
      + '<span class="sub-off">−'
      + Math.round((1 - p.cents / p.std_cents) * 100) + "%</span></div>"
    : "";
  const tpl = {month: T.subBillM, quarter: T.subBillQ, year: T.subBillY}[plan] || "";
  /* промокод знижує тільки перший платіж — так і пишемо, щоб потім
     повна ціна не стала несподіванкою */
  const bill = st.prices.set === "promo"
    ? T.subBillFirst.replace("%s", money(p.cents)) + " " + tpl.replace("%s", money(p.std_cents)).toLowerCase()
    : tpl.replace("%s", money(p.cents));
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
    + was
    + '<div class="sub-bill">' + esc(bill) + "</div>"
    + '<button type="button" class="sub-btn" data-buy="' + plan + '">' + esc(T.subBuy) + "</button>"
    + "</div>";
}

/* Смужка «ранніх» — над картками.

   Окремого вітального вікна на вході немає (рішення власника 27.09.2026):
   людина приходить сюди з відмови, коли безкоштовне скінчилось, і саме тут
   має прочитати, що ціни в неї знижені. Сказати це раніше, коли вона ще
   нічого не збиралась купувати, означало б продавати тому, хто не питав.

   Сум тут немає: перекреслене «було» і відсоток знижки стоять на самих
   картках (власник, 27.09.2026), а смужка відповідає тільки на питання
   «чому мені дешевше».
*/
function earlyNote(){
  if (!st || !st.prices || st.prices.set !== "early") return "";
  const text = esc(T.subEarlyText);
  return '<div class="sub-early">'
    + '<span class="sub-early-tag">' + esc(T.subEarlyTag) + "</span>"
    + '<div class="sub-early-txt">'
    +   "<b>" + esc(T.subEarlyHead) + "</b>"
    +   "<p>" + text + "</p>"
    + "</div></div>";
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
  if (promoDone || st.prices.set === "promo")
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

/* Скільки днів лишилось. Рахуємо вгору: пів дня — це ще день, і людина
   має побачити «1 день», а не «0». Нижче нуля не опускаємось — прострочене
   сюди просто не потрапляє, підписка вже не active. */
function daysLeft(){
  if (!st || !st.paid_until) return null;
  const end = new Date(st.paid_until);
  if (isNaN(end)) return null;
  return Math.max(0, Math.ceil((end - Date.now()) / 86400000));
}

/* «день / дні / днів» — за правилом слов'янських мов. В англійській усі
   три однакові, тому окремої гілки не треба. */
function dayWord(n){
  const t1 = n % 10, t100 = n % 100;
  if (t1 === 1 && t100 !== 11) return T.subDay1;
  if (t1 >= 2 && t1 <= 4 && (t100 < 12 || t100 > 14)) return T.subDay2;
  return T.subDay5;
}

/* Стан оплаченої підписки.

   Тому, хто вже платить, вітрина тарифів ні до чого: він прийшов сюди
   подивитись, доки оплачено, і скасувати чи змінити картку. Тому зверху
   — строк і кнопка кабінету, а картки ховаються за посиланням: шлях до
   довшого тарифу лишається, але не лізе в очі першим (рішення власника
   25.09.2026).

   Головне число тут — дні, а не дата: «залишилось 62 дні» читається
   з першого погляду, а «до 25.12.2026» вимагає порахувати в голові.
   Дату лишаємо поруч, дрібнішим — вона потрібна, коли дні на межі. */
function liveBox(){
  /* Довічна: ні днів, ні дати, ні «змінити тариф» — міняти нема на що,
     і будь-яке число тут було б вигадкою. */
  if (st.plan === "life")
    return '<div class="sub-live life">'
      + '<div class="sub-live-info">'
      +   '<div class="sub-live-head"><span class="sub-live-dot" aria-hidden="true"></span>'
      +     "<b>" + esc(T.subLifeHead) + "</b></div>"
      +   '<div class="sub-live-till">' + esc(T.subLifeX) + "</div>"
      + "</div>"
      + '<div class="sub-live-act">' + manageBtn() + "</div>"
      + "</div>";
  const n = daysLeft();
  const name = {month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[st.plan] || "";
  const date = st.paid_until ? till(st.paid_until) : "";
  const left = (n === null) ? ""
    : (n === 0
        ? '<div class="sub-live-left last">' + esc(T.subLastDay) + "</div>"
        : '<div class="sub-live-left"><b>' + n + "</b>"
          + '<span>' + esc(dayWord(n)) + "</span>"
          + '<i>' + esc(T.subLeft) + "</i></div>");
  return '<div class="sub-live">'
    + '<div class="sub-live-info">'
    +   '<div class="sub-live-head"><span class="sub-live-dot" aria-hidden="true"></span>'
    +     '<b>' + esc(T.subLiveHead) + "</b>"
    +     '<em>· ' + esc(name) + "</em></div>"
    +   left
    +   (date ? '<div class="sub-live-till">'
                + esc(T.subValid.replace("%s", date)) + "</div>" : "")
    + "</div>"
    + '<div class="sub-live-act">' + manageBtn()
    /* Обидва підписи в кнопці одразу: видно завжди один, але ширину
       задає довший — інакше при перемиканні кнопка росте й зсуває
       сусідню. */
    +   '<button type="button" class="sub-change" id="subChange">'
    +     '<span>' + esc(T.subChange) + "</span>"
    +     '<span>' + esc(T.subChangeBack) + "</span></button></div>"
    + "</div>";
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
  return previewBox() + sectionBody();
}
function sectionBody(){
  const live = !!st.active;
  /* Умови й повернення мають бути видно поруч із кнопкою оплати, а не
     ховатись у підвалі: цього вимагає і платіжний сервіс, і здоровий глузд
     — людина читає їх саме тоді, коли збирається платити. */
  const legal = '<p class="sub-legal">'
    + '<a href="/terms" target="_blank" rel="noopener">' + esc(T.subTerms) + '</a>'
    + '<span>·</span>'
    + '<a href="/refund" target="_blank" rel="noopener">' + esc(T.subRefund) + '</a>'
    + '</p>';
  /* Довічній вітрина ні до чого: купувати нічого, і кнопки «розгорнути
     тарифи» в неї теж немає — картки лишились би прихованими назавжди. */
  if (live && st.plan === "life") return liveBox() + legal;
  /* Що відкриває підписка й що дається без неї — доводи для того, хто ще
     не платить. Тому, хто вже платить, вони нічого не кажуть, тільки
     розтягують розділ, тому в оплаченому стані їх немає. */
  return (live
      ? liveBox()
      /* Тільки надпис, без кнопок (рішення власника 27.09.2026): у того, хто
         зараз не платить, керувати нічим — кабінет платіжки потрібен
         підписці, а не її відсутності. Хто платив колись і хоче туди
         повернутись, знайде кнопку там же, коли підписка діє. */
      : '<div class="sub-state"><span class="sub-chip">'
        + esc(planLabel()) + "</span></div>")
    + '<div class="sub-shop' + (live ? " tucked" : "") + '">'
    +   earlyNote()
    +   '<div class="sub-plans">' + ORDER.map(card).join("") + "</div>"
    +   promoRow()
    + "</div>"
    + (live ? "" : feats() + freeTerms())
    + '<p class="sub-soon" id="subSoon"></p>'
    + legal;
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

/* «Змінити тариф» — картки лежать у розмітці завжди, ховає їх лише клас.
   Так перемикач працює без перемальовування розділу, і місце, на якому
   людина зупинилась, нікуди не стрибає. */
function wireChange(){
  const b = document.getElementById("subChange");
  const box = document.querySelector(".sub-shop");
  if (!b || !box) return;
  b.addEventListener("click", () => {
    const shown = !box.classList.toggle("tucked");
    b.classList.toggle("open", shown);
    b.setAttribute("aria-expanded", shown ? "true" : "false");
    if (shown) box.scrollIntoView({block: "nearest", behavior: "smooth"});
  });
}

function wirePreview(){
  document.querySelectorAll(".sub-prev [data-prev]").forEach(b =>
    b.addEventListener("click", () => setPreview(b.dataset.prev)));
}

function wire(){
  wirePreview();
  wirePromo();
  wireManage();
  wireChange();
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
