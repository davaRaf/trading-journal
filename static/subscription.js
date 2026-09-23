/* ============================================================
   Розділ «Підписка» у вікні налаштувань + значок тарифу біля ніка.

   Влаштований як backup.js: load() читає стан, section() віддає
   розмітку, wire() чіпляє події вже після вставки.

   Ціни приходять із сервера (/api/billing/state), а не зашиті тут:
   у людини може бути свій набір — «ранні» платять менше назавжди, —
   і браузер не має про це здогадуватись сам.

   Лічильника «лишилось N угод» тут немає навмисне (рішення власника
   22.09.2026). Єдине, що показуємо, — скільки лишилось звернень до
   помічника: інакше його відмова виглядала б поломкою.
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

/* Значок біля ніка: FREE / 1М / 3М / 12М. Без слів і без дати —
   дата живе у підказці й у самому розділі. */
function badge(){
  if (!st) return "";
  const sign = st.active ? {month: "1М", quarter: "3М", year: "12М"}[st.plan] : "FREE";
  if (!sign) return "";
  const cls = "sub-tier" + (st.active ? " on" : "") + (st.plan === "year" ? " y" : "");
  return '<button type="button" class="' + cls + '" data-tip="' + esc(planLabel()) + '"'
    + ' aria-label="' + esc(T.subTitle + " · " + planLabel()) + '"'
    + ' onclick="__settings.open(&quot;subscription&quot;)">' + esc(sign) + "</button>";
}

/* Перекреслена сума під ціною.

   У звичайних цінах показуємо, скільки те саме вийшло б помісячно
   (€11,99 × 12), у «ранніх» — звичайну ціну цього ж тарифу: у них
   вигода саме проти неї, а не проти місяців у подарунок. */
function was(plan, p){
  const early = st.prices.set === "early";
  if (early){
    if (plan === "month"){
      const off = Math.round((1 - p.cents / p.std_cents) * 100);
      return "<s>" + money(p.std_cents) + "</s> → " + T.subSave.replace("%d", off);
    }
    return "<s>" + money(p.std_cents) + "</s> → " + money(p.cents);
  }
  if (plan === "month") return "&nbsp;";
  const full = st.prices.month.cents * MONTHS[plan];
  return "<s>" + money(full) + "</s> → " + money(p.cents);
}

function card(plan){
  const p = st.prices[plan];
  if (!p) return "";
  const per = Math.round(p.cents / MONTHS[plan]);
  const best = plan === "year";
  const gift = best
    ? '<span class="sub-gift">' + esc(st.prices.set === "early" ? T.subYourPrice : T.subGift) + "</span>"
    : "";
  const bill = {month: T.subBillM, quarter: T.subBillQ, year: T.subBillY}[plan];
  const name = {month: T.subMonth, quarter: T.subQuarter, year: T.subYear}[plan];
  const val = (per / 100).toFixed(2).replace(".", ",");
  return '<div class="sub-plan' + (best ? " best" : "") + '" data-p="' + plan + '">'
    + gift
    + '<div class="sub-bg" aria-hidden="true"><span class="sub-word">StatsAI</span></div>'
    + '<div class="sub-name">' + esc(name) + "</div>"
    + '<div class="sub-cost"><span class="cur">€</span><span class="val">' + esc(val) + "</span>"
    +   '<span class="cnt">' + esc(T.subPerMonth) + "</span></div>"
    + '<div class="sub-was">' + was(plan, p) + "</div>"
    + '<div class="sub-bill">' + esc(bill) + "</div>"
    + '<button type="button" class="sub-btn" data-buy="' + plan + '">' + esc(T.subBuy) + "</button>"
    + "</div>";
}

/* Скільки звернень до помічника лишилось. Єдиний видимий залишок:
   людина має розуміти, чому помічник раптом відмовив. */
function aiLine(){
  if (!st || typeof st.ai_left !== "number") return "";
  return '<div class="sub-ai"><span>' + esc(T.subAiLeft) + " <b>" + st.ai_left
    + "</b> " + esc(T.subAiOf) + " <b>" + st.ai_cap + "</b></span>"
    + "<small>" + esc(T.subAiNote) + "</small></div>";
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
function section(){
  if (!st) return "";
  return '<div class="sub-state"><span class="sub-chip' + (st.active ? " paid" : "") + '">'
    +   esc(planLabel()) + "</span></div>"
    + '<div class="sub-plans">' + ORDER.map(card).join("") + "</div>"
    + feats()
    + aiLine()
    + '<p class="sub-soon" id="subSoon"></p>';
}

function wire(){
  const box = document.querySelector(".sub-plans");
  if (!box) return;
  box.addEventListener("click", e => {
    const b = e.target.closest("[data-buy]");
    if (!b) return;
    /* Платіжки ще немає (фаза 6) — чесно про це й кажемо, а не робимо
       кнопку, яка мовчки нічого не робить. */
    const note = document.getElementById("subSoon");
    if (note) note.textContent = T.subSoon;
  });
}

window.__sub = {load: load, section: section, wire: wire, badge: badge,
                state: () => st};

/* Стан читаємо одразу, не чекаючи, поки відкриють налаштування: значок
   тарифу стоїть у верхній смузі й має бути там з першої секунди. */
load().then(() => { if (window.__sideMe) __sideMe.tier(); }).catch(() => {});

})();
