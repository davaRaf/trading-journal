/* Вікно «Як оплатити»: чи каже воно хоч щось, коли вибрали картку.

   Скарга 01.10.2026: на сервері тиснеш «оплатити карткою» — і нічого не
   відбувається. Відбувалось: вікно закривалось наперед, каса не
   створювалась, а причина падала абзацом у підвал розділу «Підписка»,
   під перелік можливостей, де її ніхто не бачить.

   Перевіряємо саму розмітку, яку віддає вікно: вимкнену касу видно
   заздалегідь, а відмова лишається у вікні, де натискали.

   Запуск: node test_pay_pick.js */
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync("static/cryptopay.js", "utf8");

const T = {cpPickT:"Как оплатить", cpClose:"Закрыть", cpCardGo:"Открываем кассу…",
  cpCardT:"Картой", cpCardX:"Visa, Mastercard — через Creem", cpCardOpen:"Открыть кассу",
  cpCryptoT:"Криптой", cpCryptoX:"USDT в сети TRON",
  subSoon:"Оплата скоро заработает", subPayFail:"Не удалось открыть оплату"};

/* Вузол рівно настільки, наскільки ним користується cryptopay.js: тримає
   рядок розмітки, а пошук по ньому робить регуляркою — нам потрібні
   кнопки зі своїми data-мітками, а не справжнє дерево. */
function node(){
  const n = {html: "", cls: new Set(), kids: [], btns: {},
    classList: {add: c => n.cls.add(c), remove: c => n.cls.delete(c),
                contains: c => n.cls.has(c), toggle: c => n.cls.add(c)},
    addEventListener(){}, removeEventListener(){}, remove(){}, parentNode: null,
    get innerHTML(){ return n.html; },
    set innerHTML(v){ n.html = v; n.btns = {}; },
    set className(v){ String(v).split(" ").forEach(c => c && n.cls.add(c)); },
    appendChild(k){ n.kids.push(k); return k; },
    querySelector(sel){ return sel.indexOf(".cpay") === 0 ? n : n.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel){
      const m = /\[data-([a-z-]+)\]/.exec(sel);
      if (!m) return [];
      const out = [];
      const re = new RegExp('<button[^>]*data-' + m[1] + '(?:="([^"]*)")?[^>]*>', "g");
      let hit;
      while ((hit = re.exec(n.html))){
        const tag = hit[0];
        if (/:not\(\[disabled\]\)/.test(sel) && / disabled/.test(tag)) continue;
        /* Кнопку під той самий тег віддаємо ту саму: обробник вішає bind(),
           а тисне на неї тест, і це має бути одна кнопка, а не дві. */
        let b = n.btns[tag];
        if (!b){
          b = {dataset: {}, disabled: / disabled/.test(tag), tag: tag,
               focus(){}, addEventListener(e, f){ b["on" + e] = f; }};
          const way = /data-way="([^"]*)"/.exec(tag);
          if (way) b.dataset.way = way[1];
          n.btns[tag] = b;
        }
        out.push(b);
      }
      return out;
    }};
  return n;
}

function boot(){
  const body = node();
  /* Довге чекання переходу проганяємо одразу: тест не має сидіти чотири
     секунди, а коротке (закриття вікна) лишаємо справжнім. */
  const fastWait = (f, ms) => (ms >= 4000 ? f() : setTimeout(f, ms));
  const ctx = {T, setTimeout: fastWait, setInterval, clearInterval, console, Date,
    requestAnimationFrame: f => f(),
    document: {body: body, createElement: () => node(),
               addEventListener(){}, removeEventListener(){}},
    api: async () => { throw new Error("тест не ходить по сеть"); }};
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx, {filename: "cryptopay.js"});
  /* Вікно — єдина дитина body; його ж .cpay і віддає querySelector. */
  ctx.__box = () => body.kids[body.kids.length - 1];
  return ctx;
}

let bad = 0;
const ok = (c, msg) => { console.log((c ? "ok   " : "ПРОВАЛ ") + msg); if (!c) bad++; };

(async () => {
  /* 1. Каса картками вимкнена на сервері */
  let ctx = boot();
  ctx.__cpay.choose("month", "Месяц", "$14", () => ({}), false);
  let html = ctx.__box().html;
  ok(/data-way="card"[^>]*disabled|disabled[^>]*data-way="card"/.test(html),
     "каса вимкнена → плитка «Картой» не натискається");
  ok(html.includes(T.subSoon), "каса вимкнена → на плитці написано, чому");
  ok(/data-way="crypto"/.test(html) && !/data-way="crypto"[^>]*disabled/.test(html),
     "каса вимкнена → крипта лишається робочою");

  /* 2. Каса працює, але сервер відмовив */
  ctx = boot();
  let asked = 0;
  ctx.__cpay.choose("year", "Год", "$99",
                    async () => { asked++; return {why: T.subPayFail}; }, true);
  html = ctx.__box().html;
  ok(!/data-way="card"[^>]*disabled/.test(html), "каса працює → плитка жива");
  ok(html.includes(T.cpCardX), "каса працює → на плитці звичайний підпис");

  const card = ctx.__box().querySelectorAll("[data-way]").find(b => b.dataset.way === "card");
  card.onclick();
  ok(ctx.__box().html.includes(T.cpCardGo), "натиснули → вікно каже «відкриваємо касу»");
  await new Promise(r => setTimeout(r, 0));
  ok(asked === 1, "касу замовили рівно раз");
  ok(ctx.__box().html.includes(T.subPayFail), "відмова → причина лишилась у вікні");
  ok(ctx.__box().html.includes(T.cpClose), "відмова → у вікні є чим його закрити");
  ok(ctx.__box() !== undefined && !ctx.__box().cls.has("gone"), "вікно не зникло наперед");

  /* 3. Касу дали, але перехід не стався — має з'явитись посилання руками */
  ctx = boot();
  const LINK = "https://www.creem.io/checkout/abc";
  ctx.__cpay.choose("month", "Месяц", "$14", async () => ({url: LINK}), true);
  const card2 = ctx.__box().querySelectorAll("[data-way]").find(b => b.dataset.way === "card");
  card2.onclick();
  await new Promise(r => setTimeout(r, 0));
  html = ctx.__box().html;
  ok(!html.includes(T.subPayFail), "касу дали → помилки немає");
  ok(html.includes(T.cpCardGo), "касу дали → напис «відкриваємо» лишився");
  ok(html.includes(LINK) && html.includes(T.cpCardOpen),
     "перехід не стався → у вікні з'явилось посилання на касу руками");

  process.exit(bad ? 1 : 0);
})();
