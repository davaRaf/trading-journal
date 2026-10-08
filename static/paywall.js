/* ============================================================
   Плашка відмови: безкоштовне скінчилось.

   Одна на всі місця — угода, перенесення, помічник. Сервер каже
   тільки привід (402 і reason), слова до нього лежать тут: інакше
   кожна точка складала б свій текст і вони розійшлися б.

   Лічильника «лишилось N із 20» тут немає й бути не може (рішення
   власника 22.09.2026). Людина дізнається про межу, коли в неї
   впреться, — і одразу бачить, що робити далі.

   Окремий шар, а не звичайне вікно: відмова приходить поверх уже
   відкритої форми угоди, і підмінити її вміст означало б стерти
   те, що людина щойно набрала.
   ============================================================ */
(function(){

/* Привід → заголовок і пояснення. Ключі ті самі, що в billing.py. */
const WHY = {
  trades_limit:  ["pwTradeT", "pwTradeX"],
  bt_limit:      ["pwBtT",    "pwBtX"],
  imports_limit: ["pwImpT",   "pwImpX"],
  import_window: ["pwImpT",   "pwWinX"],
  bt_notion:     ["pwBtNotT", "pwBtNotX"],
  bt_notion_limit: ["pwBtLimT", "pwBtLimX"],
  voice_limit:   ["pwVoiceT", "pwVoiceX"],
  ai_limit:      ["pwAiT",    "pwAiX"],
  ai_cap:        ["pwCapT",   "pwCapX"],
};

let back = null;

function close(){
  if (!back) return;
  back.remove();
  back = null;
  if (window.ScrollLock) ScrollLock.off();
  document.removeEventListener("keydown", onKey);
}

function onKey(e){
  if (e.key === "Escape"){ e.stopPropagation(); close(); }
}

function show(reason){
  /* Скінчились бектест-перенесення — тут не плашка, а покупка: ползунок
     і сума. Решта приводів веде в тарифи або просто повідомляє. */
  if (reason === "bt_notion_limit") return pack();
  const keys = WHY[reason] || WHY.trades_limit;
  /* ai_cap — не про гроші: у стелю впирається той, хто вже платить,
     і кликати його в тарифи безглуздо. */
  const sell = reason !== "ai_cap";
  close();
  back = document.createElement("div");
  back.className = "pw-back";
  back.style.zIndex = window.nextTop ? nextTop() : 9000;
  back.innerHTML =
    '<div class="pw-w" role="dialog" aria-modal="true">'
    /* Логотипа й напису StatsAI тут немає (рішення власника 27.09.2026):
       людина вже в журналі, називати себе ще раз ні до чого — вікно має
       бути чисте, з одним заголовком і однією дією. */
    + '<h3>' + esc(T[keys[0]] || "") + '</h3>'
    + '<p>' + esc(T[keys[1]] || "") + '</p>'
    + (sell ? '<button type="button" class="pw-go">' + esc(T.pwPlans) + '</button>' : '')
    + '<button type="button" class="pw-later">' + esc(T.pwLater) + '</button>'
    + '</div>';
  back.addEventListener("click", e => { if (e.target === back) close(); });
  const go = back.querySelector(".pw-go");
  if (go) go.addEventListener("click", () => {
    close();
    if (window.__settings) __settings.open("subscription");
  });
  back.querySelector(".pw-later").addEventListener("click", close);
  document.body.appendChild(back);
  if (window.ScrollLock) ScrollLock.on();
  document.addEventListener("keydown", onKey);
  if (go) go.focus();
}

/* ============================================================
   Докупка бектест-перенесень: ползунок і сума.

   Чому вікно, а не розділ у налаштуваннях: людина впирається в межу
   посеред перенесення, і вести її звідси в інше місце означає втратити
   і налаштоване перенесення, і саму думку доплатити.

   Ціни рахує сервер і віддає всі разом (їх вісімнадцять) — ползунок
   показує суму одразу, без запиту на кожне смикання. Назад на сервер
   їде тільки кількість: суму він рахує заново, бо цифрам зі сторінки
   в грошах вірити не можна.
   ============================================================ */

/* €3,99 — кома, як у решті журналу. */
function money(cents){
  return "€" + (cents / 100).toFixed(2).replace(".", ",");
}

/* Умови докупки: беремо з уже прочитаного стану підписки, а немає —
   питаємо сервер. Вікно при цьому вже відкрите: чекати мережі з пустим
   екраном гірше, ніж домалювати суму через мить. */
async function packInfo(){
  const have = window.__sub && __sub.state && __sub.state();
  if (have && have.bt_pack) return have.bt_pack;
  const res = await fetch("/api/billing/state", {headers: {"Accept": "application/json"}});
  const d = await res.json().catch(() => ({}));
  return d.bt_pack || null;
}

function pack(){
  close();
  back = document.createElement("div");
  back.className = "pw-back";
  back.style.zIndex = window.nextTop ? nextTop() : 9000;
  back.innerHTML =
    '<div class="pw-w pw-pack" role="dialog" aria-modal="true">'
    + '<h3>' + esc(T.pwBtLimT || "") + '</h3>'
    + '<p>' + esc(T.pwBtLimX || "") + '</p>'
    + '<div class="pk-count"><b class="pk-n">\u2014</b>'
    +   '<span class="pk-word"></span></div>'
    + '<div class="pk-sum"><span class="pk-each"></span>'
    +   '<span class="pk-off"></span></div>'
    + '<div class="pk-row">'
    +   '<button type="button" class="pk-step pk-less" aria-label="'
    +     esc(T.pwPackLess || "") + '">\u2212</button>'
    +   '<div class="pk-sl">'
    +     '<input type="range" class="pk-range" min="3" max="20" step="1"'
    +     ' value="3" aria-label="' + esc(T.pwBtLimT || "") + '">'
    +     '<span class="pk-tr"></span><span class="pk-fl"></span>'
    +     '<span class="pk-th"></span><span class="pk-bub"></span>'
    +   '</div>'
    +   '<button type="button" class="pk-step pk-more" aria-label="'
    +     esc(T.pwPackMore || "") + '">+</button>'
    + '</div>'
    + '<div class="pk-scale"><span class="pk-lo">3</span>'
    +   '<span class="pk-hi">20</span></div>'
    + '<div class="pk-note" role="status"></div>'
    + '<button type="button" class="pw-go" disabled>' + esc(T.pwPackGo || "")
    +   '</button>'
    + '<button type="button" class="pw-later">' + esc(T.pwLater) + '</button>'
    + '</div>';
  back.addEventListener("click", e => { if (e.target === back) close(); });
  back.querySelector(".pw-later").addEventListener("click", close);
  document.body.appendChild(back);
  if (window.ScrollLock) ScrollLock.on();
  document.addEventListener("keydown", onKey);

  const w = back;
  const dlg = w.querySelector(".pw-pack");
  const range = w.querySelector(".pk-range");
  const sl = w.querySelector(".pk-sl");
  const num = w.querySelector(".pk-n");
  const word = w.querySelector(".pk-word");
  const bub = w.querySelector(".pk-bub");
  const each = w.querySelector(".pk-each");
  const save = w.querySelector(".pk-off");
  const less = w.querySelector(".pk-less");
  const more = w.querySelector(".pk-more");
  const note = w.querySelector(".pk-note");
  const go = w.querySelector(".pw-go");

  packInfo().then(info => {
    if (!back || back !== w) return;              /* вікно вже закрили */
    if (!info){ note.textContent = T.pwPackFail || ""; return; }
    range.min = info.min; range.max = info.max; range.value = info.min;
    w.querySelector(".pk-lo").textContent = info.min;
    w.querySelector(".pk-hi").textContent = info.max;
    const price = n => (info.prices || {})[String(n)] || 0;
    const base = price(info.min) / info.min;      /* від чого рахуємо вигоду */
    const span = Math.max(1, info.max - info.min);
    /* Каси немає (немає ключа чи товару) — кнопку не вмикаємо зовсім. */
    const noPay = !info.on;

    /* Розмиття на бігу. Рахуємо не крок, а швидкість: від стрілки чи
       «+» виходить майже нуль і число лишається чітким, а від ривка
       мишею — повні п'ять пікселів, як на барабані лічильника.
       Зсув по вертикалі домальовує напрямок: вгору чи вниз. */
    const still = window.matchMedia
      && matchMedia('(prefers-reduced-motion: reduce)').matches;
    let was = info.min, wasAt = 0, soon = null;

    function spin(n){
      if (still) return;
      const now = Date.now();
      const dt = Math.max(16, now - wasAt);
      const fast = Math.abs(n - was) / dt * 1000;   /* штук за секунду */
      const up = n > was ? -1 : 1;
      was = n; wasAt = now;
      const b = Math.min(5, fast / 12);
      if (b < 0.4) return sharp();
      num.style.filter = 'blur(' + b.toFixed(2) + 'px)';
      num.style.transform = 'translateY(' + (up * Math.min(4, b)).toFixed(1)
        + 'px)';
      bub.style.filter = 'blur(' + (b / 2).toFixed(2) + 'px)';
      clearTimeout(soon);
      soon = setTimeout(sharp, 110);
    }

    /* Зупинились — число наздоганяє себе й стає чітким. */
    function sharp(){
      clearTimeout(soon);
      num.style.filter = '';
      num.style.transform = '';
      bub.style.filter = '';
    }

    function draw(){
      const n = +range.value, c = price(n);
      spin(n);
      num.textContent = n;
      bub.textContent = n;
      /* Три-чотири перенесення, але п'ять перенесень: у трьох мовах
         слово при числі різне, тому обидві форми лежать у перекладі. */
      word.textContent = (n === 3 || n === 4) ? (T.pwPackWordA || "")
                                              : (T.pwPackWordB || "");
      /* Частка, а не відсоток: нею CSS рахує й ширину заливки, і зсув
         кульки з поправкою на її власні 22 пікселі. */
      sl.style.setProperty("--pk", (n - info.min) / span);
      each.textContent = (T.pwPackEach || "%s")
        .replace("%s", money(Math.round(c / n)));
      const off = Math.round(100 * (1 - (c / n) / base));
      /* Не ховаємо, а гасимо: місце під пилюлю лишається зайнятим,
         інакше на четвертому перенесенні підстрибує вся картка. */
      save.style.visibility = off > 0 ? "" : "hidden";
      save.textContent = (T.pwPackSave || "%s").replace("%s", off);
      go.textContent = (T.pwPackPay || "%s").replace("%s", money(c));
      go.disabled = !c || noPay;
      less.disabled = n <= info.min;
      more.disabled = n >= info.max;
    }

    function step(to){
      const n = Math.min(info.max, Math.max(info.min, to));
      if (+range.value === n) return;
      range.value = n;
      draw();
    }

    range.addEventListener("input", draw);
    less.addEventListener("click", () => step(+range.value - 1));
    more.addEventListener("click", () => step(+range.value + 1));
    /* Поки тягнуть — картка в стані «on»: кулька більшає, над нею
       спливає число. Відпустили — все на місце. */
    function grab(){
      dlg.classList.add("on");
      /* Відпускають часто вже не над ползунком — миша зривається
         вбік. Тому кінець тягання ловимо на вікні, інакше картка
         застрягає в стані «тягнуть» і більше не слухається. */
      window.addEventListener("pointerup", calm);
      window.addEventListener("pointercancel", calm);
    }

    function calm(){
      dlg.classList.remove("on");
      sharp();
      window.removeEventListener("pointerup", calm);
      window.removeEventListener("pointercancel", calm);
    }

    range.addEventListener("pointerdown", grab);
    range.addEventListener("blur", calm);
    /* Оплата, якщо зірветься, вмикає кнопки назад — і тоді треба
       перемалювати, щоб «−» і «+» знову знали свої межі. */
    w.__pkDraw = draw;
    draw();

    if (noPay){ note.textContent = T.pwPackSoon || ""; return; }
    go.onclick = () => buy(+range.value, info.cap, w, note, go);
  });
}

/* Оплата. Касу відкриваємо в новій вкладці, а вікно лишаємо тут: під ним
   стоїть налаштоване перенесення, і забирати його через оплату не можна.
   Далі чекаємо, поки підтвердження від Creem доїде до нашого сервера, і
   питаємо стан — підняли стелю чи ні. */
const PACK_TRIES = 30;          /* ~60 секунд, далі вже не наша швидкість */

async function buy(n, capWas, w, note, go){
  /* На час оплати замикаємо і ползунок, і «−/+»: кількість уже
     поїхала в касу, міняти її тут більше нема сенсу. */
  const lock = v => w.querySelectorAll('.pk-range, .pk-step')
                      .forEach(el => { el.disabled = v; });
  go.disabled = true;
  lock(true);
  note.textContent = "";
  let url = "";
  try{
    const res = await fetch("/api/billing/bt-imports", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({n: n}),
    });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(d.code === "no_pay" ? (T.pwPackSoon || "")
                                                     : (T.pwPackFail || ""));
    url = d.url || "";
  }catch(e){
    note.textContent = e.message || T.pwPackFail || "";
    go.disabled = false;
    lock(false);
    if (w.__pkDraw) w.__pkDraw();
    return;
  }
  window.open(url, "_blank", "noopener");
  note.textContent = T.pwPackWait || "";
  for (let i = 0; i < PACK_TRIES; i++){
    await new Promise(r => setTimeout(r, 2000));
    if (!back || back !== w) return;              /* закрили — більше не чекаємо */
    let info = null;
    try{
      if (window.__sub && __sub.load) await __sub.load();
      info = await packInfo();
    }catch(e){ continue; }
    if (info && info.cap > capWas){
      /* Стеля піднялась. Вікно не закриваємо саме: під ним чекає
         налаштоване перенесення, і натиснути «Продовжити» має людина. */
      note.textContent = (T.pwPackOk || "%s").replace("%s", info.cap);
      go.textContent = T.pwPackGo || "";
      go.disabled = false;
      go.onclick = close;
      return;
    }
  }
  note.textContent = T.pwPackSlow || "";
  go.disabled = false;
  go.textContent = T.pwLater || "";
  go.onclick = close;
}


window.Paywall = {
  show: show,
  close: close,
  /* Місце виклику ловить помилку й мовчить: плашку вже показано.
     Позначка soft саме про це — «людині вже сказали». */
  soft: function(reason){
    show(reason);
    const e = new Error("need_sub");
    e.soft = true;
    return e;
  },
};

})();
