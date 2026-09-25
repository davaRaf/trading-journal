/* ============================================================
   Розділ «Підписка» в налаштуваннях — поки тільки вітрина.

   Тарифи й ціни показуємо (їх має бачити платіжний сервіс під час
   перевірки сайту), але купити ще не можна: кнопки неактивні з
   підписом «Скоро», лімітів теж немає. Справжня підписка (оплата,
   ліміти, кабінет) живе окремо — static/subscription.js у гілці
   billing-core; коли її вмикатимуть, цей файл прибрати.

   Тексти лежать тут, а не в i18n.js: так вітрина не перетинається з
   ключами sub* справжньої підписки. Мова — глобальна LANG журналу.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* Ті самі числа, що в config.py: PRICES["std"], FREE_* і IMPORT_WINDOW_DAYS */
const PRICES = {month: 1199, quarter: 2799, year: 9999};
const MONTHS = {month: 1, quarter: 3, year: 12};
const ORDER = ["month", "quarter", "year"];
const FREE = {trades: 30, bt: 30, imports: 3, days: 30, ai: 15};

const TX = {
  uk: {
    title: "Підписка", month: "Місяць", quarter: "Квартал", year: "Рік",
    perMonth: "/ міс", soon: "Незабаром",
    billM: "Списуємо %s щомісяця", billQ: "Списуємо %s раз на три місяці", billY: "Списуємо %s раз на рік",
    gift: "−4 МІСЯЦІ",
    opens: "Що відкриває підписка",
    f: ["<b>Нові угоди без обмежень</b> — на сайті та в боті",
        "<b>Перенесення з Notion</b> і щоденна синхронізація",
        "<b>Помічник, розбір дня і звірка «Моєї ТС»</b> без місячної порції",
        "Усе записане залишається назавжди, навіть без підписки"],
    freeHead: "Що є без підписки",
    free: ["Угоди: <b>%d</b> — записані руками або в боті",
           "Угоди в режимі бектесту: <b>%d</b> — окремим рахунком",
           "Перенесення з Notion або файлом: <b>%d</b> у перші %d днів",
           "Звернення до помічника: <b>%d</b> щомісяця"],
    terms: "Умови використання", refund: "Повернення коштів",
  },
  ru: {
    title: "Подписка", month: "Месяц", quarter: "Квартал", year: "Год",
    perMonth: "/ мес", soon: "Скоро",
    billM: "Списываем %s ежемесячно", billQ: "Списываем %s раз в три месяца", billY: "Списываем %s раз в год",
    gift: "−4 МЕСЯЦА",
    opens: "Что открывает подписка",
    f: ["<b>Новые сделки без ограничений</b> — на сайте и в боте",
        "<b>Перенос из Notion</b> и ежедневная синхронизация",
        "<b>Помощник, разбор дня и сверка «Моей ТС»</b> без месячной порции",
        "Всё записанное остаётся навсегда, даже без подписки"],
    freeHead: "Что есть без подписки",
    free: ["Сделки: <b>%d</b> — записанные руками или в боте",
           "Сделки в режиме бэктеста: <b>%d</b> — отдельным счётом",
           "Переносы из Notion или файлом: <b>%d</b> в первые %d дней",
           "Обращения к помощнику: <b>%d</b> ежемесячно"],
    terms: "Условия использования", refund: "Возврат средств",
  },
  en: {
    title: "Subscription", month: "Month", quarter: "Quarter", year: "Year",
    perMonth: "/ mo", soon: "Coming soon",
    billM: "%s billed monthly", billQ: "%s billed every three months", billY: "%s billed once a year",
    gift: "−4 MONTHS",
    opens: "What the subscription opens",
    f: ["<b>New trades without limits</b> — on the site and in the bot",
        "<b>Notion import</b> and daily sync",
        "<b>Assistant, day review and strategy check</b> beyond the monthly batch",
        "Everything you wrote stays forever, even without a subscription"],
    freeHead: "What you get without a subscription",
    free: ["Trades: <b>%d</b> — added by hand or in the bot",
           "Trades in backtest mode: <b>%d</b> — counted separately",
           "Imports from Notion or a file: <b>%d</b> within the first %d days",
           "Assistant requests: <b>%d</b> every month"],
    terms: "Terms of use", refund: "Refunds",
  },
};
const tx = () => TX[typeof LANG === "string" && TX[LANG] ? LANG : "ru"];

/* €11,99 — кома, як у решті журналу; англійською — крапка */
function money(cents){
  const s = (cents / 100).toFixed(2);
  return "€" + (tx() === TX.en ? s : s.replace(".", ","));
}

function tick(){
  return '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"'
    + ' stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M3 8.5l3.5 3.5L13 4.5"/></svg>';
}

function card(plan){
  const t = tx(), cents = PRICES[plan];
  const per = Math.round(cents / MONTHS[plan]);
  const best = plan === "year";
  const bill = {month: t.billM, quarter: t.billQ, year: t.billY}[plan].replace("%s", money(cents));
  const sep = t === TX.en ? "." : ",";
  return '<div class="sub-plan' + (best ? " best" : "") + '" data-p="' + plan + '">'
    + (best ? '<span class="sub-gift">' + esc(t.gift) + "</span>" : "")
    + '<div class="sub-bg" aria-hidden="true"><span class="sub-word">StatsAI</span></div>'
    + '<div class="sub-name">' + esc(t[plan]) + "</div>"
    + '<div class="sub-cost"><span class="cur">€</span>'
    +   '<span class="val">' + Math.floor(per / 100) + '<span class="cc">' + sep + String(per % 100).padStart(2, "0") + "</span></span>"
    +   '<span class="cnt">' + esc(t.perMonth) + "</span></div>"
    + '<div class="sub-bill">' + esc(bill) + "</div>"
    /* купити поки не можна — кнопка лише показує, що оплата буде */
    + '<button type="button" class="sub-btn" disabled aria-disabled="true">' + esc(t.soon) + "</button>"
    + "</div>";
}

function section(){
  if (window.Pub && window.Pub.on) return "";          /* чужий журнал — не наша справа */
  const t = tx();
  const free = [FREE.trades, FREE.bt, [FREE.imports, FREE.days], FREE.ai].map((n, i) => {
    let s = t.free[i];
    [].concat(n).forEach(v => { s = s.replace("%d", v); });
    return "<li>" + s + "</li>";
  });
  return '<div class="sub-plans">' + ORDER.map(card).join("") + "</div>"
    + '<div class="sub-fhead">' + esc(t.opens) + "</div>"
    + '<ul class="sub-feats">' + t.f.map(r => "<li>" + tick() + "<span>" + r + "</span></li>").join("") + "</ul>"
    + '<div class="sub-fhead">' + esc(t.freeHead) + "</div>"
    + '<ul class="sub-free">' + free.join("") + "</ul>"
    + '<p class="sub-legal">'
    +   '<a href="/terms" target="_blank" rel="noopener">' + esc(t.terms) + "</a><span>·</span>"
    +   '<a href="/refund" target="_blank" rel="noopener">' + esc(t.refund) + "</a></p>";
}

window.__plans = {section, title: () => tx().title};
})();
