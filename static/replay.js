/* ============================================================
   Перемотка (replay.js) — прогін по історичному графіку.

   Суть режиму: людина обирає дату в минулому, бачить графік тільки до
   неї й крокує вперед по свічці. Майбутнього на екрані немає — у цьому
   вся різниця між прогоном і розгляданням історії, де рука сама тягнеться
   підглянути, чим усе скінчилось.

   Дані беремо з /api/candles (candles.py): готові свічки потрібного
   таймфрейму за проміжок дат. Джерело — Dukascopy, FXCM, Oanda чи
   Binance: у кожного своя ціна, і це видно на графіку.

   Час усюди UTC. Свій часовий пояс брокера (GMT+2, GMT+3, закриття в
   Нью-Йорку) — наступний крок: від нього залежить, де закінчується
   денна свічка, і для ICT це важливіше за саме джерело.

   Малюнки лежать окремим полотном поверх графіка: Lightweight Charts
   своїх інструментів не має. Точку запам'ятовуємо не пікселями, а
   парою «логічний номер свічки + ціна» — тоді лінія не з'їжджає ні
   при прокрутці, ні при зміні масштабу.
   ============================================================ */
(function () {
"use strict";

/* ───────────────────────────── стан ──────────────────────────────── */

const LS = "tj_rp";
const LSW = "tj_rp_wl";          /* список праворуч: тільки те, що додали самі */
/* Довжина свічки в секундах — щоб знати, чи вона вже закрилась. */
const TFSEC = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "4h": 14400, "1d": 86400 };
let S = {                        /* що показуємо */
  symbol: "EURUSD", tf: "15m", source: "",
  digits: 5, title: "EUR/USD",
};
let META = { symbols: [], sources: [], tfs: [] };
let WL = [];                     /* короткий список інструментів праворуч */
let symMode = "go";              /* вікно вибору: перейти чи додати до списку */

let ALL = [];                    /* усі завантажені свічки, по зростанню часу */
let cut = 0;                     /* скільки з них показано (решта — майбутнє) */
let run = null;                  /* прогін: {from, till, loading} або null */
let timer = null;                /* таймер автопрогравання */
/* Пауза між свічками на самоході. Менше число — швидше. */
const SPEEDS = [[1000, "0,5×"], [500, "1×"], [200, "2×"], [80, "5×"], [25, "10×"]];
let speed = 500;

let deals = [];                  /* угоди прогону */
let openDeal = null;             /* відкрита позиція або null */
let lines = [];                  /* цінові лінії відкритої позиції */

let draws = [];                  /* малюнки: {t, a, b, price, s} */
let tool = "cursor";
let pend = null;                 /* незавершений малюнок */
let armed = false;               /* перша точка вже стоїть, чекаємо другу */
let moved = false;               /* чи тягнули мишу із затиснутою кнопкою */
let downAt = null;               /* де натиснули, у пікселях */
let lastAt = null;               /* де зараз курсор — щоб перемалювати по Shift */

const $ = (id) => document.getElementById(id);
const chartEl = $("chart");
const cv = $("draw");
const ctx = cv.getContext("2d");

let chart, series;

/* ─────────────────────────── допоміжне ───────────────────────────── */

function pip() { return Math.pow(10, -(S.digits - 1)); }
function fmt(p) { return p == null ? "—" : p.toFixed(S.digits); }
function iso(d) { return d.toISOString().slice(0, 10); }
function addDays(d, n) { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x; }

function hint(text, ms) {
  const el = $("hint");
  el.textContent = text; el.hidden = false;
  clearTimeout(hint._t);
  if (ms !== 0) hint._t = setTimeout(() => { el.hidden = true; }, ms || 2600);
}

function save() {
  try { localStorage.setItem(LS, JSON.stringify({ symbol: S.symbol, tf: S.tf, source: S.source })); }
  catch (e) { /* приватне вікно — не біда */ }
}
function load() {
  try {
    const v = JSON.parse(localStorage.getItem(LS) || "{}");
    if (v.symbol) S.symbol = v.symbol;
    if (v.tf) S.tf = v.tf;
    if (v.source) S.source = v.source;
  } catch (e) { /* байдуже */ }
}

/* Список праворуч починається з одного інструмента — того, що на
   графіку. Решту людина додає плюсом сама: постійно бачити всі два
   десятки пар нікому не треба. */
function loadWL() {
  try { WL = JSON.parse(localStorage.getItem(LSW) || "null"); } catch (e) { WL = null; }
  if (!Array.isArray(WL)) WL = [];
  WL = WL.filter((c) => META.symbols.some((s) => s.symbol === c));
  if (WL.indexOf(S.symbol) < 0) WL.unshift(S.symbol);
}
function saveWL() {
  try { localStorage.setItem(LSW, JSON.stringify(WL)); } catch (e) { /* байдуже */ }
}

/* ───────────────────────────── графік ────────────────────────────── */

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function makeChart() {
  chart = LightweightCharts.createChart(chartEl, {
    layout: { background: { color: css("--panel") }, textColor: css("--dim"), fontSize: 11,
              fontFamily: css("--mono") || "monospace", attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    /* autoScale вимкнений навмисно. З ним шкала цін підбирається під те,
       що зараз видно, і графік стрибає вгору-вниз від кожного протягування
       вбік. Без нього діапазон стоїть, а посунути його вгору-вниз чи
       розтягнути свічки людина може сама — мишею або за шкалу праворуч. */
    rightPriceScale: { borderColor: css("--line"), autoScale: false,
                       scaleMargins: { top: .08, bottom: .08 } },
    timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false,
                 rightOffset: 6, barSpacing: 8 },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: css("--faint"), width: 1, style: 3, labelBackgroundColor: css("--text") },
      horzLine: { color: css("--faint"), width: 1, style: 3, labelBackgroundColor: css("--text") },
    },
    handleScroll: true, handleScale: true,
    autoSize: true,
  });

  series = chart.addCandlestickSeries({
    upColor: css("--up"), downColor: css("--down"),
    wickUpColor: css("--up"), wickDownColor: css("--down"),
    borderUpColor: css("--up"), borderDownColor: css("--down"),
    priceFormat: { type: "price", precision: S.digits, minMove: Math.pow(10, -S.digits) },
  });

  chart.timeScale().subscribeVisibleLogicalRangeChange(() => { paint(); keepView(); });
  chart.subscribeCrosshairMove(onCross);
  /* Розмір лишаємо на бібліотеку (autoSize). Коли ми міряли контейнер
     самі й тут-таки міняли розмір графіка, ResizeObserver бачив цю зміну
     і міряв знову — графік смикався туди-сюди від будь-якого руху миші. */
  new ResizeObserver(fitCanvas).observe(chartEl.parentElement);
  fitCanvas();
}


/* Бібліотека сповіщає про зміну часової шкали, а про цінову — ні. Через
   те фігури лишались на старих місцях, коли розтягуєш свічки за шкалу
   праворуч. Тримаємо легкий дозор: двічі на кадр питаємо, де тепер
   опорна точка, і перемальовуємо лише коли вона зрушила. */
let lastSig = "";

function watchView() {
  requestAnimationFrame(watchView);
  if (!chart || !series || !ALL.length) return;
  const b = ALL[cut - 1];
  if (!b) return;
  const y = series.priceToCoordinate(b.close);
  const x = chart.timeScale().logicalToCoordinate(cut - 1);
  const sig = y + "|" + x;
  if (sig === lastSig) return;
  lastSig = sig;
  paint();
}

function onCross(param) {
  const bar = param.seriesData && param.seriesData.get(series);
  showOhlc(bar || ALL[cut - 1]);
  paint(param);
}

function showOhlc(b) {
  if (!b) { $("ohlc").textContent = ""; return; }
  const up = b.close >= b.open;
  const dt = new Date(b.time * 1000);
  const when = dt.toISOString().slice(0, 16).replace("T", " ");
  $("ohlc").innerHTML =
    "<b>" + S.title + " · " + S.tf + " · " + (S.source || "").toUpperCase() + "</b> " +
    '<span class="' + (up ? "u" : "d") + '">' +
    "O" + fmt(b.open) + " H" + fmt(b.high) + " L" + fmt(b.low) + " C" + fmt(b.close) +
    "</span>  <span>" + when + " UTC</span>";
}

/* ───────────────────────────── дані ──────────────────────────────── */

async function fetchBars(from, till) {
  const q = new URLSearchParams({
    symbol: S.symbol, tf: S.tf, from: iso(from), to: iso(till),
  });
  if (S.source) q.set("source", S.source);
  const r = await fetch("/api/candles?" + q.toString());
  if (r.status === 401) { location.href = "/login"; return null; }
  const j = await r.json().catch(() => ({}));
  if (r.status === 503) {
    const e = new Error(j.error || "джерело не відповідає");
    e.feed = true;
    throw e;
  }
  if (!r.ok) throw new Error(j.error || ("помилка " + r.status));
  S.digits = j.digits;
  S.source = j.source;
  return (j.bars || []).map((b) => ({
    time: b[0], open: b[1], high: b[2], low: b[3], close: b[4], volume: b[5],
  }));
}

/* Сервер віддає щонайбільше місяць за раз — тож довгі проміжки беремо
   шматками. Дублікати на стиках прибираємо по часу. */
async function loadRange(from, till, what) {
  const out = [];
  const total = Math.ceil(((till - from) / 86400000 + 1) / 31) || 1;
  let a = new Date(from), n = 0;
  while (a <= till) {
    let b = addDays(a, 30);
    if (b > till) b = new Date(till);
    n += 1;
    /* Джерело віддає історію не миттєво, тож мовчати не можна: людина
       має бачити, що йде робота, а не порожній екран. */
    hint((what || "Вантажимо") + " " + S.symbol + " · " + n + " з " + total + "…", 0);
    out.push(...(await fetchBars(a, b) || []));
    a = addDays(b, 1);
  }
  const seen = new Set();
  return out.filter((b) => (seen.has(b.time) ? false : (seen.add(b.time), true)))
            .sort((x, y) => x.time - y.time);
}

/* Масштаб і місце, де стоїть графік, живуть між заходами: людина
   підібрала зручну щільність свічок — не змушувати робити це щоразу.
   Пишемо не частіше ніж раз на півсекунди, бо подія летить на кожен кадр. */
const LSV = "tj_rp_view";
let viewTimer = null;

function keepView() {
  if (viewTimer) return;
  viewTimer = setTimeout(() => {
    viewTimer = null;
    const ts = chart.timeScale();
    try {
      localStorage.setItem(LSV, JSON.stringify({ bs: ts.options().barSpacing }));
    } catch (e) { /* приватне вікно */ }
  }, 500);
}

function useView() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem(LSV) || "null"); } catch (e) { v = null; }
  if (!v || !v.bs) return false;
  /* Запам'ятовуємо лише щільність свічок, не місце. Місце зберігати
     небезпечно: наступного разу свічок інша кількість, і збережена
     позиція легко виносить графік у порожнечу, звідки ще треба
     здогадатись повернутись. Тому відкриваємось завжди на свіжому краю. */
  chart.timeScale().applyOptions({ barSpacing: v.bs });
  return true;
}

/* Скинути утримуваний діапазон. `hard` — коли треба саме перерахувати
   зараз (подвійний клік по шкалі): сам лише прапорець нічого не змінює,
   бібліотека перебирає межі, коли їй віддають дані. */
/* Підібрати діапазон по даних і одразу знову замкнути: межі лягають по
   свічках, але далі не переобчислюються самі. */
function refit() {
  const ps = series.priceScale();
  ps.applyOptions({ autoScale: true });
  requestAnimationFrame(() => ps.applyOptions({ autoScale: false }));
}

function redraw() {
  series.applyOptions({
    priceFormat: { type: "price", precision: S.digits, minMove: Math.pow(10, -S.digits) },
  });
  refit();
  series.setData(ALL.slice(0, cut));
  showOhlc(ALL[cut - 1]);
  showPrices();
  paint();
}

/* Коли джерело мовчить (а Dukascopy, наприклад, блокує за частоту),
   сидіти перед порожнім графіком нема сенсу: у більшості інструментів є
   запасне джерело, і чесніше мовчки перемкнутись, сказавши про це. */
function switchSource() {
  const m = META.symbols.find((x) => x.symbol === S.symbol);
  const have = (m && m.sources) || [];
  const next = have.find((c) => c !== S.source);
  if (!next) return false;
  const was = S.source;
  S.source = next;
  save();
  buildSources();
  hint("«" + was + "» не відповідає — малюємо по «" + next + "»", 5000);
  return true;
}

/* Звичайний перегляд: останні тижні, усе видно. */
async function showLatest(again) {
  stopRun();
  hint("Вантажимо " + S.symbol + "…", 0);
  try {
    const till = new Date();
    ALL = await loadRange(addDays(till, -45), till);
    cut = ALL.length;
    if (!ALL.length) {
      hint("У джерела «" + (S.source || "") + "» немає свіжих даних по " +
           S.symbol + ". Оберіть інше джерело.", 6000);
      series.setData([]); return;
    }
    redraw();
    if (!useView()) chart.timeScale().fitContent();
    $("hint").hidden = true;
  } catch (e) {
    if (e.feed && !again && switchSource()) return showLatest(true);
    hint(e.message, 7000);
  }
}

/* ──────────────────────────── прогін ─────────────────────────────── */

async function startRun(fromISO, again, keepAt) {
  const from = new Date(fromISO + "T00:00:00Z");
  if (isNaN(from)) { hint("Оберіть дату", 3000); return; }
  stopRun();
  hint("Готуємо прогін…", 0);
  try {
    /* передісторія — щоб було що аналізувати перед першим входом */
    const before = await loadRange(addDays(from, -45), addDays(from, -1));
    /* keepAt — мить історії, на якій стояли до перемикання таймфреймy або
       джерела. Тоді вантажимо не місяць від старту, а весь проміжок до
       того місця: інакше людина поверталась би до дати старту й губила
       всі свої угоди. */
    const month = addDays(from, 30);
    const edge = keepAt ? addDays(new Date(keepAt * 1000), 30) : month;
    const till = edge > month ? edge : month;
    const after = await loadRange(from, till);
    ALL = before.concat(after);
    cut = before.length;
    if (!cut) { hint("Перед цією датою історії немає", 4500); return; }
    run = { from: from, till: till, loading: false };
    if (keepAt) {
      /* Показуємо лише свічки, що на цю мить уже закрились. На старшому
         таймфреймі поточна свічка ще формується, і намалювати її цілою
         означало б показати її ж майбутні максимум і мінімум — тобто дати
         підглянути вперед. Краще відстати на один бар, ніж збрехати. */
      const len = TFSEC[S.tf] || 0;
      let n = 0;
      while (n < ALL.length && ALL[n].time + len <= keepAt) n += 1;
      if (n > cut) cut = n;
      markLines();          /* угоди прогону лишаються, лінії перемальовуємо */
    } else {
      deals = []; openDeal = null; clearLines();
    }
    drawDeals();
    redraw();
    /* Показуємо останні свічки перед датою старту. Просто лишити масштаб
       від попереднього перегляду не можна: там була інша кількість свічок,
       і графік опинявся за краєм екрана. */
    const ts = chart.timeScale();
    let span = 140;
    try {
      const v = JSON.parse(localStorage.getItem(LSV) || "null");
      if (v && v.bs) span = Math.max(30, Math.round((cv.clientWidth || 900) / v.bs));
    } catch (e) { /* байдуже */ }
    ts.setVisibleLogicalRange({ from: Math.max(0, cut - span), to: cut + 8 });
    $("hint").hidden = true;
    /* Дірки в архіві трапляються — у FXCM, наприклад, немає травня-липня
       2026-го. Мовчки показати три свічки замість місяця означало б
       змусити людину гадати, чому графік порожній. */
    if (cut < 60) {
      hint("Перед " + fromISO + " у джерела «" + (S.source || "") + "» лише " +
           cut + " свічок. Спробуйте іншу дату або інше джерело.", 7000);
    }
  } catch (e) {
    if (e.feed && !again && switchSource()) return startRun(fromISO, true);
    hint(e.message, 7000);
  }
}

/* ── шторки смужки перемотки: швидкість і таймфрейм ────────────────
   Свої, а не ті, що в панелі малювання: ті прив'язані до .props і до її
   координат. Тут потрібно небагато — список під кнопкою, тож хай буде
   простий і свій. */

function buildRwPops() {
  const nice = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                 "1h": "1h", "4h": "4h", "1d": "D" };
  $("rwPopSpeed").innerHTML = SPEEDS.map(([ms, title]) =>
    '<button data-ms="' + ms + '"' + (ms === speed ? ' class="on"' : "") + ">" +
    title + "</button>").join("");
  $("rwPopTf").innerHTML = META.tfs.map((t) =>
    '<button data-tf="' + t + '"' + (t === S.tf ? ' class="on"' : "") + ">" +
    (nice[t] || t) + "</button>").join("");
}

function closeRwPops() {
  document.querySelectorAll(".rwpop").forEach((el) => el.classList.remove("open"));
  $("rwSpeed").classList.remove("on");
  $("rwTf").classList.remove("on");
}

function rwPop(id, btn) {
  const el = $(id);
  const open = !el.classList.contains("open");
  closeRwPops();
  if (!open) return;
  /* шторка стає під своєю кнопкою */
  const br = btn.getBoundingClientRect();
  const pr = $("rwBar").getBoundingClientRect();
  el.style.left = Math.round(br.left - pr.left) + "px";
  /* смужку могли підтягти до стелі — тоді список відкривається донизу */
  el.classList.toggle("down", br.top < 220);
  el.classList.add("open");
  btn.classList.add("on");
  const er = el.getBoundingClientRect();
  if (er.right > window.innerWidth - 6) {
    el.style.left = Math.round(window.innerWidth - 6 - er.width - pr.left) + "px";
  }
}

/* ── вибір бару на графіку ──────────────────────────────────────────
   «Обрати бар» не питає дату в окремому віконці: за курсором іде смуга
   на всю висоту, і видно, куди саме цілишся. Тицьнули — звідти й
   починається прогін, а все правіше ховається. */

let picking = false;
let pickX = null;

function startPick() {
  picking = true;
  pickX = null;
  cv.style.pointerEvents = "auto";
  cv.classList.add("pick");
  $("rwStart").classList.add("on");
  hint("Тицьніть на свічку, з якої почати. Esc — скасувати", 0);
}

function stopPick() {
  if (!picking) return;
  picking = false;
  pickX = null;
  cv.classList.remove("pick");
  /* повертаємо полотну ту прозорість, яку диктує обраний інструмент */
  cv.style.pointerEvents = tool === "cursor" ? "none" : "auto";
  $("rwStart").classList.remove("on");
  $("hint").hidden = true;
  paint();
}

async function pickBar(x) {
  const lg = chart.timeScale().coordinateToLogical(x);
  stopPick();
  if (lg == null || !ALL.length) return;
  const i = Math.max(0, Math.min(cut - 1, Math.round(lg)));
  const t = ALL[i].time;
  await startRun(iso(new Date(t * 1000)), false, t);
}

/* Ставимо смужку в задану точку, не випускаючи її за край екрана. */
function putBar(x, y) {
  const el = $("rwBar");
  if (isNaN(x) || isNaN(y)) return;
  const left = Math.max(4, Math.min(window.innerWidth - el.offsetWidth - 4, x));
  const top = Math.max(4, Math.min(window.innerHeight - el.offsetHeight - 4, y));
  el.dataset.free = "1";
  el.style.left = left + "px";
  el.style.top = top + "px";
  el.style.bottom = "auto";
}

function stopRun() {
  pause();
  run = null;
  closeRwPops();
}

/* Смужка працює завжди, навіть коли прогін ще не починали: натиснули
   крок або пуск — прогін заводиться сам, від лівого краю того, що зараз
   видно. Усе, що правіше, стає майбутнім і відкривається свічка за
   свічкою. Так не треба спершу щось обирати, щоб просто подивитись. */
async function ensureRun() {
  if (run) return true;
  if (!ALL.length) { hint("Спершу має завантажитись графік", 3000); return false; }
  const vr = chart.timeScale().getVisibleLogicalRange();
  let i = vr ? Math.round(vr.from) : 0;
  i = Math.max(0, Math.min(cut - 1, i));
  const t = ALL[i].time;
  await startRun(iso(new Date(t * 1000)), false, t);
  return !!run;
}

/* Дотягуємо наступний місяць, поки людина дивиться поточний. */
async function ensureAhead() {
  if (!run || run.loading) return;
  if (ALL.length - cut > 120) return;
  run.loading = true;
  try {
    const from = addDays(run.till, 1);
    const till = addDays(from, 30);
    if (from > new Date()) { hint("Історія скінчилась — це вже сьогодні", 4000); pause(); return; }
    const more = await loadRange(from, till);
    const last = ALL.length ? ALL[ALL.length - 1].time : 0;
    ALL = ALL.concat(more.filter((b) => b.time > last));
    run.till = till;
  } catch (e) {
    hint("Дані не довантажились: " + e.message, 4000);
    pause();
  } finally {
    run.loading = false;
  }
}

function step() {
  if (cut >= ALL.length) { ensureAhead(); return; }
  const bar = ALL[cut];
  cut += 1;
  series.update(bar);
  keepInView(bar);
  checkDeal(bar);
  showOhlc(bar);
  showPrices();
  paint();
  ensureAhead();
}

/* Нова свічка може вийти за межі того, що видно. Тоді — і тільки тоді —
   переобчислюємо діапазон, інакше людина втратить ціну з очей. */
function keepInView(bar) {
  const top = series.priceToCoordinate(bar.high);
  const bot = series.priceToCoordinate(bar.low);
  const h = cv.clientHeight || chartEl.clientHeight;
  if (top == null || bot == null || top < 8 || bot > h - 8) refit();
}

function stepBack() {
  if (cut <= 1) return;
  cut -= 1;
  series.setData(ALL.slice(0, cut));
  showOhlc(ALL[cut - 1]);
  showPrices();
  paint();
}

function play() {
  if (timer || !run) return;
  timer = setInterval(step, speed);
  $("rwPlayIco").innerHTML = '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>';
}
function pause() {
  if (timer) { clearInterval(timer); timer = null; }
  $("rwPlayIco").innerHTML = '<path d="M8 5l11 7-11 7z"/>';
}

/* ──────────────────────────── угоди ──────────────────────────────── */

const SPREAD = 1;                /* пунктів; поки однаковий для всіх */

function prices() {
  const b = ALL[cut - 1];
  if (!b) return null;
  return { bid: b.close, ask: b.close + SPREAD * pip() };
}

function showPrices() {
  const p = prices();
  $("bidTxt").textContent = p ? fmt(p.bid) : "—";
  $("askTxt").textContent = p ? fmt(p.ask) : "—";
  $("spreadTxt").textContent = p ? SPREAD.toFixed(1) : "—";
  if (openDeal) drawDeals();
}

function clearLines() {
  lines.forEach((l) => { try { series.removePriceLine(l); } catch (e) {} });
  lines = [];
}

function markLines() {
  clearLines();
  if (!openDeal) return;
  const mk = (price, color, title) =>
    lines.push(series.createPriceLine({
      price: price, color: color, lineWidth: 1, lineStyle: 2,
      axisLabelVisible: true, title: title,
    }));
  mk(openDeal.entry, css("--accent"), openDeal.side === "buy" ? "BUY" : "SELL");
  if (openDeal.sl) mk(openDeal.sl, css("--down"), "SL");
  if (openDeal.tp) mk(openDeal.tp, css("--up"), "TP");
}

function openPos(side, lot, slPips, tpPips) {
  const p = prices();
  if (!p) { hint("Немає ціни", 2500); return; }
  const entry = side === "buy" ? p.ask : p.bid;
  const dir = side === "buy" ? 1 : -1;
  openDeal = {
    side: side, lot: lot, entry: entry,
    sl: slPips > 0 ? entry - dir * slPips * pip() : null,
    tp: tpPips > 0 ? entry + dir * tpPips * pip() : null,
    at: ALL[cut - 1].time,
  };
  markLines();
  drawDeals();
}

function closePos(price, why) {
  if (!openDeal) return;
  const dir = openDeal.side === "buy" ? 1 : -1;
  const pips = ((price - openDeal.entry) * dir) / pip();
  deals.push({
    side: openDeal.side, lot: openDeal.lot, entry: openDeal.entry,
    exit: price, pips: pips, why: why, at: openDeal.at,
  });
  openDeal = null;
  clearLines();
  drawDeals();
}

/* На кожній новій свічці перевіряємо, чи не зачепило стоп або тейк.
   Порядок важливий: якщо свічка накрила обидва рівні, чесніше вважати,
   що спрацював стоп — усередині хвилини ми не знаємо, що було першим. */
function checkDeal(bar) {
  if (!openDeal) return;
  const d = openDeal;
  if (d.side === "buy") {
    if (d.sl && bar.low <= d.sl) return closePos(d.sl, "SL");
    if (d.tp && bar.high >= d.tp) return closePos(d.tp, "TP");
  } else {
    if (d.sl && bar.high >= d.sl) return closePos(d.sl, "SL");
    if (d.tp && bar.low <= d.tp) return closePos(d.tp, "TP");
  }
}

function drawDeals() {
  const box = $("pos");
  const rows = [];
  let sum = 0;

  if (openDeal) {
    const p = prices();
    const cur = openDeal.side === "buy" ? (p ? p.bid : openDeal.entry)
                                        : (p ? p.ask : openDeal.entry);
    const dir = openDeal.side === "buy" ? 1 : -1;
    const live = ((cur - openDeal.entry) * dir) / pip();
    rows.push(
      '<div class="row open ' + openDeal.side + '">' +
      '<span class="side">' + openDeal.side.toUpperCase() + "</span>" +
      '<span class="r ' + (live >= 0 ? "u" : "d") + '">' + live.toFixed(1) + "</span>" +
      '<span class="px">вхід ' + fmt(openDeal.entry) + "</span>" +
      '<button class="cl" data-close="1">закрити</button>' +
      "</div>");
  }
  deals.slice().reverse().forEach((d) => {
    sum += d.pips;
    rows.push(
      '<div class="row ' + d.side + '">' +
      '<span class="side">' + d.side.toUpperCase() + "</span>" +
      '<span class="r ' + (d.pips >= 0 ? "u" : "d") + '">' + d.pips.toFixed(1) + "</span>" +
      '<span class="px">' + fmt(d.entry) + " → " + fmt(d.exit) +
      (d.why ? " · " + d.why : "") + "</span>" +
      "</div>");
  });
  box.innerHTML = rows.length ? rows.join("")
    : '<div class="empty">Угод поки немає. Відкрийте позицію кнопкою BUY або SELL.</div>';

  const el = $("pnlSum");
  el.textContent = (sum >= 0 ? "+" : "") + sum.toFixed(1);
  el.className = sum >= 0 ? "u" : "d";
}

/* ──────────────────────────── малюнки ────────────────────────────── */

/* Скільки пікселів екрана в одному пікселі розмітки. На Windows зі
   збільшенням 125 % чи 150 % це 1,25 і 1,5 — і саме через нього лінія
   виходила блідою та розмитою: товщина в 2 px лягала між рядками
   пікселів, і замість чистого кольору виходила сіра каша. Тому нижче
   і товщину, і положення лінії кладемо рівно на сітку екрана. */
let DPR = 1;

function lineW(w) { return Math.max(1, Math.round(w * DPR)) / DPR; }

function onGrid(v, w) {
  const dev = Math.round(lineW(w) * DPR);
  return (dev % 2 ? Math.floor(v * DPR) + .5 : Math.round(v * DPR)) / DPR;
}
function onGridT(v) { return Math.round(v * DPR) / DPR; }

function fitCanvas() {
  const r = chartEl.getBoundingClientRect();
  DPR = window.devicePixelRatio || 1;
  /* цілі розміри в пікселях розмітки: інакше полотно розтягується на
     дробову частку й розмиває все, що на ньому намальовано */
  const w = Math.round(r.width), h = Math.round(r.height);
  cv.width = Math.round(w * DPR);
  cv.height = Math.round(h * DPR);
  cv.style.width = w + "px";
  cv.style.height = h + "px";
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  placeProps();
  paint();
}

/* Пікселі -> «номер свічки + ціна». Саме в такому вигляді малюнок
   переживає прокрутку й зміну масштабу. */
/* Малюнки тримаються часу, а не номера свічки.

   Номер залежить від таймфрейму: на денному свічка №300 — це один день,
   на годинному — зовсім інший. Через це імбаланс, відмічений на денному,
   на годинному опинявся казна-де. Час же однаковий на всіх таймфреймах,
   тому точка — це {t: час, p: ціна}, а номер свічки рахується щоразу під
   те, що зараз на екрані.

   Між свічками час ділимо лінійно, а за межами ряду — рівними кроками
   таймфрейму: так лінія, протягнута у вихідні або в майбутнє, лишається
   там, де її поклали. */
function lToT(l) {
  const n = ALL.length;
  const step = TFSEC[S.tf] || 60;
  if (!n) return l * step;
  const i = Math.floor(l), f = l - i;
  if (i < 0) return ALL[0].time + (i + f) * step;
  if (i >= n - 1) return ALL[n - 1].time + (i - (n - 1) + f) * step;
  return ALL[i].time + (ALL[i + 1].time - ALL[i].time) * f;
}

function tToL(t) {
  const n = ALL.length;
  const step = TFSEC[S.tf] || 60;
  if (!n) return t / step;
  if (t <= ALL[0].time) return (t - ALL[0].time) / step;
  if (t >= ALL[n - 1].time) return (n - 1) + (t - ALL[n - 1].time) / step;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (ALL[mid].time <= t) lo = mid; else hi = mid;
  }
  const a = ALL[lo].time, b = ALL[hi].time;
  return lo + (b > a ? (t - a) / (b - a) : 0);
}

function toPoint(x, y) {
  const lg = chart.timeScale().coordinateToLogical(x);
  const pr = series.coordinateToPrice(y);
  return (lg == null || pr == null) ? null : { t: lToT(lg), p: pr };
}
function toXY(pt) {
  const x = chart.timeScale().logicalToCoordinate(tToL(pt.t));
  const y = series.priceToCoordinate(pt.p);
  return (x == null || y == null) ? null : { x: x, y: y };
}

const FIB = [0, .236, .382, .5, .618, .786, 1];

/* Чим малюємо зараз. Нова фігура успадковує останній вибір — так само,
   як у будь-якому редакторі: підібрав колір один раз і малюєш далі. */
let STYLE = { color: "#2b62e3", textColor: "#171b24", width: 2, dash: 0,
              alpha: 1, textAlpha: 1 };

let sel = -1;                    /* виділена фігура */
let hover = -1;                  /* фігура під курсором */
let grab = null;                 /* що тягнемо: кінець або всю фігуру */

/* ── влучання ── */

function distSeg(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = dx * dx + dy * dy;
  let t = len ? ((px - x1) * dx + (py - y1) * dy) / len : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

const NEAR = 7;

function hitOne(d, x, y) {
  if (d.t === "hline") {
    const yy = series.priceToCoordinate(d.p);
    return yy != null && Math.abs(y - yy) <= NEAR;
  }
  const a = toXY(d.a);
  if (!a) return false;
  if (d.t === "text") {
    return Math.abs(x - a.x) < 90 && Math.abs(y - a.y) < 14;
  }
  const b = d.b ? toXY(d.b) : null;
  if (!b) return false;
  if (d.t === "trend") return distSeg(x, y, a.x, a.y, b.x, b.y) <= NEAR;
  if (d.t === "rect") {
    const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x);
    const y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
    return x >= x0 - NEAR && x <= x1 + NEAR && y >= y0 - NEAR && y <= y1 + NEAR;
  }
  if (d.t === "fib") {
    const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x);
    if (x < x0 - NEAR || x > x1 + NEAR) return false;
    return FIB.some((k) => {
      const yy = series.priceToCoordinate(d.a.p + (d.b.p - d.a.p) * k);
      return yy != null && Math.abs(y - yy) <= NEAR;
    });
  }
  return false;
}

/* Зверху лежить те, що намальовано пізніше — його й беремо першим. */
function hitAt(x, y) {
  for (let i = draws.length - 1; i >= 0; i--) if (hitOne(draws[i], x, y)) return i;
  return -1;
}

/* Кружечки на кінцях виділеної фігури — за них її й розтягують. */
function handles(d) {
  if (d.t === "hline") {
    const y = series.priceToCoordinate(d.p);
    return y == null ? [] : [{ k: "p", x: cv.clientWidth / 2, y: y }];
  }
  const a = toXY(d.a);
  if (!a) return [];
  if (d.t === "text" || !d.b) return [{ k: "a", x: a.x, y: a.y }];
  const b = toXY(d.b);
  return b ? [{ k: "a", x: a.x, y: a.y }, { k: "b", x: b.x, y: b.y }] : [];
}

function handleAt(x, y) {
  if (sel < 0) return null;
  return handles(draws[sel]).find((h) => Math.hypot(x - h.x, y - h.y) <= 8) || null;
}

/* ── малювання ── */

/* Напис має власний колір: лінію часто хочеться бачити яскравою, а
   підпис до неї — спокійним, і навпаки. */
function label(d, txt, x, y) {
  ctx.save();
  ctx.setLineDash([]);
  ctx.fillStyle = d.textColor || d.color || STYLE.textColor;
  ctx.globalAlpha = d.textAlpha == null ? 1 : d.textAlpha;
  ctx.fillText(txt, onGridT(x), onGridT(y));
  ctx.restore();
}

function paint() {
  if (!chart) return;
  const w = cv.clientWidth, h = cv.clientHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.font = "12px " + (css("--sans") || "sans-serif");

  const list = pend ? draws.concat([pend]) : draws;
  list.forEach((d, i) => {
    const color = d.color || STYLE.color;
    const wid = d.width || STYLE.width;
    const op = d.alpha == null ? 1 : d.alpha;
    /* Підсвітку фігури під курсором кладемо ПІД саму фігуру. Зверху
       вона затуманювала лінію, і щойно намальована лінія — а курсор
       якраз над нею — здавалась блідою та брудною. */
    const isPend = pend && i === list.length - 1;
    if (!isPend && i === hover && i !== sel) halo(d, color, wid);

    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = lineW(wid);
    ctx.globalAlpha = op;
    const dash = d.dash || 0;
    ctx.setLineDash(dash ? [dash, dash + 2] : []);

    if (d.t === "hline") {
      const y0 = series.priceToCoordinate(d.p);
      if (y0 == null) return;
      const y = onGrid(y0, wid);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      label(d, d.s || fmt(d.p), 6, y - 5);
      drawMark(d, i, list);
      return;
    }
    const a = toXY(d.a); const b = d.b ? toXY(d.b) : null;
    if (!a) return;

    if (d.t === "text") {
      label(d, d.s || "", a.x, a.y);
      drawMark(d, i, list);
      return;
    }
    if (!b) return;

    if (d.t === "trend") {
      let ax = a.x, ay = a.y, bx = b.x, by = b.y;
      /* рівну лінію (ту саму, що з Shift) теж кладемо на сітку */
      if (Math.abs(ay - by) < .6) ay = by = onGrid((ay + by) / 2, wid);
      if (Math.abs(ax - bx) < .6) ax = bx = onGrid((ax + bx) / 2, wid);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      if (d.s) label(d, d.s, (ax + bx) / 2 + 6, (ay + by) / 2 - 6);
    } else if (d.t === "rect") {
      const x0 = onGrid(Math.min(a.x, b.x), wid), x1 = onGrid(Math.max(a.x, b.x), wid);
      const y0 = onGrid(Math.min(a.y, b.y), wid), y1 = onGrid(Math.max(a.y, b.y), wid);
      ctx.globalAlpha = op * .12;
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.globalAlpha = op;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      if (d.s) label(d, d.s, x0 + 5, y0 - 5);
    } else if (d.t === "fib") {
      const x1 = Math.min(a.x, b.x), x2 = Math.max(a.x, b.x);
      FIB.forEach((k) => {
        const p = d.a.p + (d.b.p - d.a.p) * k;
        const y0 = series.priceToCoordinate(p);
        if (y0 == null) return;
        const y = onGrid(y0, wid);
        ctx.globalAlpha = op * ((k === 0 || k === 1) ? 1 : .55);
        ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = css("--dim");
        const txt = k.toFixed(3).replace(/0+$/, "").replace(/\.$/, "") + "  " + fmt(p);
        const tw = ctx.measureText(txt).width;
        ctx.fillText(txt, onGridT(x2 + 5 + tw > w ? Math.max(2, x1 - tw - 5) : x2 + 5), onGridT(y - 3));
        ctx.fillStyle = color;
        ctx.globalAlpha = op;
        ctx.setLineDash(dash ? [dash, dash + 2] : []);
      });
      if (d.s) label(d, d.s, x1 + 5, Math.min(a.y, b.y) - 5);
    }
    ctx.globalAlpha = 1;
    drawMark(d, i, list);
  });
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;

  /* Смуга вибору бару. Малюється останньою, поверх усього: поки її
     ведуть, важливо бачити саме її, а не фігури під нею. */
  if (picking && pickX != null) {
    ctx.strokeStyle = css("--accent");
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(Math.round(pickX) + .5, 0);
    ctx.lineTo(Math.round(pickX) + .5, h);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

/* Фігуру під курсором ледь підсвічуємо — малюється до неї, знизу. */
function halo(d, color, wid) {
  ctx.save();
  ctx.setLineDash([]);
  ctx.globalAlpha = .22;
  ctx.lineWidth = lineW(wid) + 6;
  ctx.strokeStyle = color;
  strokeShape(d);
  ctx.restore();
}

/* Виділену обводимо кружечками на кінцях. */
function drawMark(d, i, list) {
  if (pend && i === list.length - 1) return;
  if (i !== sel) return;
  ctx.save();
  ctx.setLineDash([]);
  handles(d).forEach((hh) => {
    ctx.beginPath();
    ctx.arc(hh.x, hh.y, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = css("--panel");
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = css("--accent");
    ctx.stroke();
  });
  ctx.restore();
}

function strokeShape(d) {
  if (d.t === "hline") {
    const y = series.priceToCoordinate(d.p);
    if (y == null) return;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cv.clientWidth, y); ctx.stroke();
    return;
  }
  const a = toXY(d.a), b = d.b ? toXY(d.b) : null;
  if (!a || !b) return;
  if (d.t === "trend") { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
  if (d.t === "rect" || d.t === "fib") ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
}

/* ── смужка властивостей ── */

const LSP = "tj_rp_props";
const LSB = "tj_rp_bar";    /* де людина поставила смужку перемотки */
const LSC = "tj_rp_recent";

/* Палітра: рядок сірих і сітка кольорів. Роблю її з HSL, а не списком —
   так відтінки лягають рівно й не треба тримати сотню шістнадцяткових. */
const HUES = [355, 20, 42, 86, 142, 172, 198, 222, 268, 320];
const LEVELS = [
  { s: 78, l: 62 }, { s: 82, l: 52 }, { s: 86, l: 44 },
  { s: 74, l: 34 }, { s: 66, l: 26 },
];

function palette() {
  const greys = ["#ffffff", "#e6e9ef", "#cdd3dd", "#aab2c0", "#8a93a3",
                 "#6b7383", "#4e5665", "#363d4a", "#232934", "#171b24"];
  const rows = [greys];
  LEVELS.forEach((lv) =>
    rows.push(HUES.map((h) => "hsl(" + h + " " + lv.s + "% " + lv.l + "%)")));
  return rows;
}

function recent(add) {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(LSC) || "[]"); } catch (e) { list = []; }
  if (add) {
    list = [add].concat(list.filter((c) => c !== add)).slice(0, 6);
    try { localStorage.setItem(LSC, JSON.stringify(list)); } catch (e) { /* байдуже */ }
  }
  return list;
}

function buildPal(el) {
  const field = el.dataset.for;               /* color або textColor */
  el.innerHTML =
    '<div class="grid">' +
    palette().map((row) => row.map((c) =>
      '<button data-c="' + c + '" style="background:' + c + '"></button>').join("")).join("") +
    "</div>" +
    '<div class="line"></div>' +
    '<div class="foot">' +
    '<div class="recent"></div>' +
    /* саме label, а не button: браузер не пускає <input> усередину
       кнопки й мовчки виносить його назовні */
    '<label class="pick" title="Свій колір">' +
    '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
    '<input type="color"></label>' +
    "</div>" +
    '<div class="op"><div class="cap">Непрозорість</div>' +
    '<div class="row"><input type="range" min="10" max="100" step="5" value="100">' +
    '<input class="val" value="100%"></div></div>';

  el.querySelector(".grid").onclick = (e) => {
    const b = e.target.closest("[data-c]");
    if (b) { setProp(field, b.dataset.c); recent(b.dataset.c); fillRecent(el); markProps(); }
  };
  el.querySelector(".recent").onclick = (e) => {
    const b = e.target.closest("[data-c]");
    if (b) { setProp(field, b.dataset.c); markProps(); }
  };
  const pick = el.querySelector(".pick input");
  pick.oninput = () => { setProp(field, pick.value); recent(pick.value); fillRecent(el); markProps(); };

  const rng = el.querySelector("input[type=range]");
  const val = el.querySelector(".val");
  rng.oninput = () => {
    val.value = rng.value + "%";
    setProp(field === "color" ? "alpha" : "textAlpha", Number(rng.value) / 100);
  };
  val.onchange = () => {
    const n = Math.max(10, Math.min(100, parseInt(val.value, 10) || 100));
    rng.value = n; val.value = n + "%";
    setProp(field === "color" ? "alpha" : "textAlpha", n / 100);
  };
  fillRecent(el);
}

function fillRecent(el) {
  el.querySelector(".recent").innerHTML = recent().map((c) =>
    '<button data-c="' + c + '" style="background:' + c + '"></button>').join("");
}

function buildWidths() {
  $("wRows").innerHTML = [1, 2, 3, 4].map((w) =>
    '<button data-w="' + w + '">' +
    '<svg viewBox="0 0 40 8"><path d="M2 4h36" stroke-width="' + w + '"/></svg>' +
    "<span>" + w + "px</span></button>").join("");
  $("wRows").onclick = (e) => {
    const b = e.target.closest("[data-w]");
    if (b) { setProp("width", Number(b.dataset.w)); closePops(); }
  };
}

/* ── шторки ── */

function closePops(keep) {
  document.querySelectorAll(".pop").forEach((p) => {
    if (p !== keep) p.classList.remove("open");
  });
  document.querySelectorAll(".ptrig").forEach((b) => {
    b.classList.toggle("on", !!keep && b.dataset.pop === keep.dataset.name);
  });
}

function togglePop(name, btn) {
  const el = $("pop" + name[0].toUpperCase() + name.slice(1));
  if (!el) return;
  el.dataset.name = name;
  const open = !el.classList.contains("open");
  closePops();
  if (!open) return;
  /* шторка тримається своєї кнопки й не вилазить за край вікна */
  const pr = $("props").getBoundingClientRect();
  const br = btn.getBoundingClientRect();
  el.style.left = Math.round(br.left - pr.left) + "px";
  el.classList.add("open");
  btn.classList.add("on");
  const er = el.getBoundingClientRect();
  if (er.right > window.innerWidth - 6) {
    el.style.left = Math.round(window.innerWidth - 6 - er.width - pr.left) + "px";
  }
  if (er.left < 6) el.style.left = Math.round(6 - pr.left) + "px";
  $("props").classList.toggle("up", pr.top + pr.height + er.height + 16 > window.innerHeight);
}

function buildProps() {
  document.querySelectorAll(".pal").forEach(buildPal);
  buildWidths();

  $("popDash").querySelector(".rows").onclick = (e) => {
    const b = e.target.closest("[data-d]");
    if (b) { setProp("dash", Number(b.dataset.d)); closePops(); }
  };

  document.querySelectorAll(".ptrig").forEach((b) => {
    b.addEventListener("mousedown", (e) => e.stopPropagation());
    b.onclick = (e) => { e.stopPropagation(); togglePop(b.dataset.pop, b); };
  });
  $("props").addEventListener("mousedown", (e) => e.stopPropagation());

  $("pText").onclick = () => { closePops(); editText(); };
  $("pDel").onclick = () => {
    if (sel < 0) return;
    draws.splice(sel, 1);
    sel = -1; hover = -1;
    closePops(); showProps(); paint();
  };

  /* ручка: смужку тягають, куди зручно, і місце запам'ятовується */
  let off = null;
  $("grip").addEventListener("mousedown", (e) => {
    const r = $("props").getBoundingClientRect();
    off = { x: e.clientX - r.left, y: e.clientY - r.top };
    closePops();
    e.preventDefault(); e.stopPropagation();
  });
  window.addEventListener("mousemove", (e) => {
    if (!off) return;
    const el = $("props");
    const x = Math.max(4, Math.min(window.innerWidth - el.offsetWidth - 4, e.clientX - off.x));
    const y = Math.max(4, Math.min(window.innerHeight - el.offsetHeight - 4, e.clientY - off.y));
    el.style.left = x + "px"; el.style.top = y + "px";
    el.dataset.free = "1";
  });
  window.addEventListener("mouseup", () => {
    if (!off) return;
    off = null;
    const el = $("props");
    try { localStorage.setItem(LSP, JSON.stringify({ x: el.style.left, y: el.style.top })); }
    catch (err) { /* приватне вікно */ }
  });

  /* натиснули будь-де поза смужкою — шторки закриваються */
  window.addEventListener("mousedown", () => closePops());

  try {
    const v = JSON.parse(localStorage.getItem(LSP) || "null");
    if (v && v.x) {
      const el = $("props");
      el.style.left = v.x; el.style.top = v.y; el.dataset.free = "1";
    }
  } catch (e) { /* байдуже */ }
}

function setProp(name, value) {
  STYLE[name] = value;
  if (sel >= 0) draws[sel][name] = value;
  markProps();
  paint();
}

function markProps() {
  const d = sel >= 0 ? draws[sel] : STYLE;
  const col = d.color || STYLE.color;
  const txt = d.textColor || STYLE.textColor || col;
  const wid = d.width || STYLE.width;
  const dsh = d.dash || 0;

  $("barStroke").style.background = col;
  $("barText").style.background = txt;
  $("wLabel").textContent = wid + "px";
  document.querySelector("#icoW").setAttribute("stroke-width", wid);
  $("icoD").innerHTML = dsh === 0
    ? '<path d="M3 12h18"/>'
    : (dsh > 4 ? '<path d="M3 12h5M11 12h5M19 12h2"/>'
               : '<path d="M3 12h1.5M8 12h1.5M13 12h1.5M18 12h1.5"/>');

  $("popStroke").querySelectorAll("[data-c]").forEach((b) =>
    b.classList.toggle("on", b.dataset.c === col));
  $("popText").querySelectorAll("[data-c]").forEach((b) =>
    b.classList.toggle("on", b.dataset.c === txt));
  $("wRows").querySelectorAll("[data-w]").forEach((b) =>
    b.classList.toggle("on", Number(b.dataset.w) === wid));
  $("popDash").querySelectorAll("[data-d]").forEach((b) =>
    b.classList.toggle("on", Number(b.dataset.d) === dsh));

  const a = Math.round((d.alpha == null ? 1 : d.alpha) * 100);
  const ta = Math.round((d.textAlpha == null ? 1 : d.textAlpha) * 100);
  const set = (pop, n) => {
    const rng = pop.querySelector("input[type=range]"), val = pop.querySelector(".val");
    if (rng) { rng.value = n; val.value = n + "%"; }
  };
  set($("popStroke"), a);
  set($("popText"), ta);
}

function placeProps() {
  const el = $("props");
  if (el.hidden || el.dataset.free) return;
  const r = chartEl.getBoundingClientRect();
  el.style.left = Math.round(r.left + 16) + "px";
  el.style.top = Math.round(r.bottom - el.offsetHeight - 44) + "px";
}

function showProps() {
  const el = $("props");
  const was = el.hidden;
  el.hidden = sel < 0;
  if (el.hidden) { closePops(); return; }
  markProps();
  if (was) placeProps();
}

function editText() {
  if (sel < 0) return;
  const d = draws[sel];
  const s = prompt("Напис на фігурі", d.s || "");
  if (s === null) return;
  d.s = s.trim();
  paint();
}

/* ── інструменти ── */

function setTool(name) {
  tool = name;
  pend = null; armed = false; moved = false; downAt = null; lastAt = null;
  document.querySelectorAll("#tools button[data-tool]").forEach((b) => {
    b.classList.toggle("on", b.dataset.tool === name);
  });
  if (name !== "cursor") { sel = -1; showProps(); }
  cv.classList.toggle("live", name !== "cursor");
  /* Стиль у рядку сильніший за клас, а ми ним керуємо під час наведення.
     Тож перемикаючи інструмент, ставимо його прямо, інакше полотно
     назавжди лишиться прозорим для натискань. */
  cv.style.pointerEvents = name === "cursor" ? "none" : "auto";
  cv.style.cursor = name === "cursor" ? "default" : "crosshair";
  paint();
}

/* Фігуру можна поставити двома способами, і обидва звичні: затиснути
   кнопку й протягнути, або клацнути раз (перша точка), повести мишею —
   лінія тягнеться за курсором — і клацнути вдруге. */
function finish() {
  if (pend) {
    draws.push(pend);
    sel = draws.length - 1;
  }
  pend = null; armed = false; moved = false; downAt = null; lastAt = null;
  setTool("cursor");
  showProps();
  paint();
}

function onDown(e) {
  const r = cv.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;

  if (picking) { e.preventDefault(); pickBar(x); return; }
  if (armed) {                         /* другий клік — кінець фігури */
    aim(x, y, e.shiftKey);
    finish();
    return;
  }

  if (tool === "cursor") {
    /* тягнемо кінець виділеної фігури або всю її */
    const hnd = handleAt(x, y);
    if (hnd) { grab = { kind: hnd.k, i: sel }; e.preventDefault(); return; }
    const i = hitAt(x, y);
    sel = i;
    showProps();
    paint();
    if (i >= 0) {
      grab = { kind: "move", i: i, from: toPoint(x, y), snap: JSON.parse(JSON.stringify(draws[i])) };
      e.preventDefault();
    }
    return;
  }

  const pt = toPoint(x, y);
  if (!pt) return;

  if (tool === "hline") {
    draws.push(Object.assign({ t: "hline", p: pt.p }, STYLE));
    sel = draws.length - 1;
    setTool("cursor"); showProps(); paint(); return;
  }
  if (tool === "text") {
    const s = prompt("Напис");
    if (s) {
      draws.push(Object.assign({ t: "text", a: pt, s: s }, STYLE, { dash: 0 }));
      sel = draws.length - 1;
    }
    setTool("cursor"); showProps(); paint(); return;
  }
  pend = Object.assign({ t: tool, a: pt, b: pt }, STYLE);
  moved = false;
  downAt = { x: x, y: y };
}

/* Shift вирівнює фігуру: лінію — по горизонталі, вертикалі або рівно
   під 45°, прямокутник — у квадрат. Рахуємо в пікселях, бо рівність тут
   саме та, яку видно оком, а не рівність у цінах і хвилинах. */
const TAN22 = 0.4142;

function snap(x, y) {
  const a = toXY(pend.a);
  if (!a) return { x: x, y: y };
  const dx = x - a.x, dy = y - a.y;
  const ax = Math.abs(dx), ay = Math.abs(dy);
  const sx = dx < 0 ? -1 : 1, sy = dy < 0 ? -1 : 1;
  if (pend.t === "rect" || pend.t === "fib") {
    const s = Math.max(ax, ay);
    return { x: a.x + sx * s, y: a.y + sy * s };
  }
  if (ay <= ax * TAN22) return { x: x, y: a.y };
  if (ax <= ay * TAN22) return { x: a.x, y: y };
  const s = (ax + ay) / 2;
  return { x: a.x + sx * s, y: a.y + sy * s };
}

function aim(x, y, shift) {
  if (!pend) return;
  if (downAt && !armed &&
      Math.abs(x - downAt.x) + Math.abs(y - downAt.y) > 4) moved = true;
  const at = shift && pend.t !== "hline" && pend.t !== "text" ? snap(x, y) : { x: x, y: y };
  const pt = toPoint(at.x, at.y);
  if (pt) { pend.b = pt; paint(); }
}

function onMove(e) {
  const r = cv.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;

  if (picking) { pickX = x; paint(); return; }
  if (grab) return dragShape(x, y, e.shiftKey);

  if (pend) { lastAt = { x: x, y: y }; aim(x, y, e.shiftKey); return; }

  /* У режимі курсора полотно пропускає натискання до графіка — інакше
     не буде ні прокрутки, ні перехрестя. Вмикаємо його рівно тоді, коли
     курсор над фігурою: тільки там нам і потрібні натискання. */
  if (tool !== "cursor") return;
  const inside = x >= 0 && y >= 0 && x <= cv.clientWidth && y <= cv.clientHeight;
  const was = hover;
  hover = inside ? hitAt(x, y) : -1;
  const onHandle = inside && handleAt(x, y);
  cv.style.pointerEvents = (hover >= 0 || onHandle) ? "auto" : "none";
  cv.style.cursor = onHandle ? "crosshair" : (hover >= 0 ? "move" : "default");
  showTip(hover >= 0 && !onHandle ? { x: x, y: y, i: hover } : null);
  if (was !== hover) paint();
}

function dragShape(x, y, shift) {
  const d = draws[grab.i];
  if (!d) { grab = null; return; }
  if (grab.kind === "p") {
    const pr = series.coordinateToPrice(y);
    if (pr != null) d.p = pr;
  } else if (grab.kind === "a" || grab.kind === "b") {
    let at = { x: x, y: y };
    if (shift && d.a && d.b) {
      const base = grab.kind === "a" ? d.b : d.a;
      const bxy = toXY(base);
      if (bxy) {
        const dx = x - bxy.x, dy = y - bxy.y;
        const ax = Math.abs(dx), ay = Math.abs(dy);
        const sx = dx < 0 ? -1 : 1, sy = dy < 0 ? -1 : 1;
        if (d.t === "rect" || d.t === "fib") {
          const s = Math.max(ax, ay);
          at = { x: bxy.x + sx * s, y: bxy.y + sy * s };
        } else if (ay <= ax * TAN22) at = { x: x, y: bxy.y };
        else if (ax <= ay * TAN22) at = { x: bxy.x, y: y };
        else { const s = (ax + ay) / 2; at = { x: bxy.x + sx * s, y: bxy.y + sy * s }; }
      }
    }
    const pt = toPoint(at.x, at.y);
    if (pt) d[grab.kind] = pt;
  } else if (grab.kind === "move") {
    const now = toPoint(x, y);
    if (!now || !grab.from) return;
    const dt = now.t - grab.from.t, dp = now.p - grab.from.p;
    const s0 = grab.snap;
    if (s0.p != null) d.p = s0.p + dp;
    if (s0.a) d.a = { t: s0.a.t + dt, p: s0.a.p + dp };
    if (s0.b) d.b = { t: s0.b.t + dt, p: s0.b.p + dp };
  }
  paint();
}

function onUp() {
  if (grab) { grab = null; return; }
  if (!pend || armed) return;
  /* Протягнули — фігура готова. Просто клацнули — лишаємо її за курсором
     до другого кліку. */
  if (moved) finish();
  else { armed = true; hint("Клацніть другий раз, щоб поставити фігуру", 2200); }
}

function showTip(at) {
  const el = $("tip");
  if (!at) { el.hidden = true; return; }
  const d = draws[at.i];
  el.textContent = d && d.s ? "Змінити напис" : "Додати напис";
  el.style.left = at.x + "px";
  el.style.top = at.y + "px";
  el.hidden = false;
}

/* ─────────────────────────── інтерфейс ───────────────────────────── */

function buildTfs() {
  const box = $("tfs");
  const nice = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                 "1h": "1h", "4h": "4h", "1d": "D" };
  box.innerHTML = META.tfs.map((t) =>
    '<button data-tf="' + t + '"' + (t === S.tf ? ' class="on"' : "") + ">" +
    (nice[t] || t) + "</button>").join("");
  $("rwTf").textContent = nice[S.tf] || S.tf;
  buildRwPops();
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (b) setTf(b.dataset.tf);
  };
}

/* Перехід на інший таймфрейм — і з верхнього ряду, і зі смужки перемотки. */
function setTf(tf) {
  if (!tf || tf === S.tf) return;
  /* Мить історії беремо до зміни таймфрейму: кінець показаної свічки і є
     тим часом, на якому людина стоїть. */
  const at = (run && cut && ALL[cut - 1])
    ? ALL[cut - 1].time + (TFSEC[S.tf] || 0) : 0;
  S.tf = tf; save(); buildTfs();
  run ? startRun(iso(run.from), false, at) : showLatest();
}

function buildSources() {
  const sel = $("srcSel");
  const mine = META.symbols.find((s) => s.symbol === S.symbol);
  const have = mine ? mine.sources : META.sources.map((s) => s.source);
  sel.innerHTML = have.map((code) => {
    const t = (META.sources.find((s) => s.source === code) || {}).title || code;
    return '<option value="' + code + '"' + (code === S.source ? " selected" : "") + ">" + t + "</option>";
  }).join("");
  sel.onchange = () => {
    const at = (run && cut && ALL[cut - 1])
      ? ALL[cut - 1].time + (TFSEC[S.tf] || 0) : 0;
    S.source = sel.value; save();
    run ? startRun(iso(run.from), false, at) : showLatest();
  };
}

/* У списку — самі скорочення: EURUSD і так зрозуміліше за «Євро/Долар»,
   а місця праворуч мало. */
function buildWatch() {
  const box = $("wl");
  box.innerHTML = WL.map((code) =>
    '<div class="it' + (code === S.symbol ? " on" : "") + '" data-s="' + code + '">' +
    '<span class="c">' + code + "</span>" +
    '<button class="rm" data-rm="' + code + '" title="Прибрати зі списку">' +
    '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>').join("");
  box.onclick = (e) => {
    const rm = e.target.closest("[data-rm]");
    if (rm) { dropWatch(rm.dataset.rm); return; }
    const it = e.target.closest(".it");
    if (it) pickSymbol(it.dataset.s);
  };
}

function addWatch(code) {
  if (WL.indexOf(code) < 0) { WL.push(code); saveWL(); buildWatch(); }
  $("symModal").hidden = true;
}

function dropWatch(code) {
  /* той, що зараз на графіку, лишається: інакше список став би порожнім */
  if (code === S.symbol) { hint("Цей інструмент зараз на графіку"); return; }
  WL = WL.filter((c) => c !== code);
  saveWL(); buildWatch();
}

function pickSymbol(code) {
  const m = META.symbols.find((s) => s.symbol === code);
  if (!m) return;
  S.symbol = code; S.title = m.title; S.digits = m.digits;
  if (m.sources.indexOf(S.source) < 0) S.source = m.sources[0] || "";
  save();
  if (WL.indexOf(code) < 0) { WL.push(code); saveWL(); }
  $("symName").textContent = code;
  $("symIco").textContent = m.title.slice(0, 1);
  $("symModal").hidden = true;
  draws = []; pend = null;
  buildSources(); buildWatch();
  run ? startRun(iso(run.from)) : showLatest();
}

function buildSymModal() {
  const box = $("symList");
  const q = ($("symQ").value || "").trim().toUpperCase();
  const hit = META.symbols.filter((s) =>
    (symMode !== "add" || WL.indexOf(s.symbol) < 0) &&
    (!q || s.symbol.indexOf(q) >= 0 || s.title.toUpperCase().indexOf(q) >= 0));
  const groups = {};
  hit.forEach((s) => { (groups[s.group] = groups[s.group] || []).push(s); });
  box.innerHTML = Object.keys(groups).map((g) =>
    '<div class="grp">' + g + "</div>" +
    groups[g].map((s) =>
      '<div class="it" data-s="' + s.symbol + '">' +
      '<span class="c">' + s.symbol + '</span><span class="t">' + s.title + "</span></div>").join("")
  ).join("") || '<div class="grp">' +
    (symMode === "add" ? "Усе вже в списку" : "Нічого не знайшли") + "</div>";
}

function clock() {
  const d = new Date();
  $("clock").textContent = d.toISOString().slice(11, 19) + " UTC";
}

/* ──────────────────────────── запуск ─────────────────────────────── */

function wire() {
  /* інструмент */
  const openSym = (mode) => {
    symMode = mode;
    $("symQ").placeholder = mode === "add" ? "Додати до списку" : "Пошук інструмента";
    $("symModal").hidden = false;
    $("symQ").value = ""; buildSymModal(); $("symQ").focus();
  };
  $("symBtn").onclick = () => openSym("go");
  $("wlAdd").onclick = () => openSym("add");
  $("symQ").oninput = buildSymModal;
  $("symList").onclick = (e) => {
    const it = e.target.closest(".it");
    if (!it) return;
    if (symMode === "add") addWatch(it.dataset.s); else pickSymbol(it.dataset.s);
  };

  /* перемотка */
  $("rwStart").onclick = () => (picking ? stopPick() : startPick());
  $("rwFwd").onclick = async () => { if (await ensureRun()) { pause(); step(); } };
  $("rwBack").onclick = async () => { if (await ensureRun()) { pause(); stepBack(); } };
  $("rwPlay").onclick = async () => {
    if (run) return timer ? pause() : play();
    if (await ensureRun()) play();
  };
  $("rwStop").onclick = () => { stopRun(); showLatest(); };
  buildRwPops();
  $("rwSpeed").onclick = (e) => { e.stopPropagation(); rwPop("rwPopSpeed", $("rwSpeed")); };
  $("rwTf").onclick = (e) => { e.stopPropagation(); rwPop("rwPopTf", $("rwTf")); };
  $("rwPopSpeed").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    speed = Number(b.dataset.ms);
    $("rwSpeed").textContent = (SPEEDS.find((x) => x[0] === speed) || [0, ""])[1];
    if (timer) { pause(); play(); }     /* на ходу — підхоплюємо одразу */
    closeRwPops(); buildRwPops();
  };
  $("rwPopTf").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    closeRwPops();
    setTf(b.dataset.tf);
  };
  /* Натиснули будь-де повз шторку — вона закривається. Саму кнопку сюди
     не рахуємо: інакше натискання спершу закрило б шторку тут, а потім
     клік відкрив би її знову, і закрити кнопкою стало б неможливо. */
  window.addEventListener("mousedown", (e) => {
    if (!e.target.closest(".rwpop, .rw-t")) closeRwPops();
  });

  /* ── смужку тягають за ручку, і місце за нею лишається ───────────── */
  let rwOff = null;
  $("rwGrip").addEventListener("mousedown", (e) => {
    const r = $("rwBar").getBoundingClientRect();
    rwOff = { x: e.clientX - r.left, y: e.clientY - r.top };
    e.preventDefault(); e.stopPropagation();
  });
  window.addEventListener("mousemove", (e) => {
    if (!rwOff) return;
    putBar(e.clientX - rwOff.x, e.clientY - rwOff.y);
  });
  window.addEventListener("mouseup", () => {
    if (!rwOff) return;
    rwOff = null;
    const el = $("rwBar");
    try { localStorage.setItem(LSB, JSON.stringify({ x: el.style.left, y: el.style.top })); }
    catch (err) { /* приватне вікно — просто не запам'ятаємо */ }
  });
  /* Вікно могли зменшити між заходами, і збережене місце опинилось би за
     краєм екрана — разом зі смужкою. Тому щоразу вертаємо її в межі. */
  window.addEventListener("resize", () => {
    const el = $("rwBar");
    if (el.dataset.free === "1") putBar(parseFloat(el.style.left), parseFloat(el.style.top));
  });
  try {
    const v = JSON.parse(localStorage.getItem(LSB) || "null");
    if (v && v.x) putBar(parseFloat(v.x), parseFloat(v.y));
  } catch (e) { /* байдуже */ }

  /* малювання */
  $("tools").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.tool) return setTool(b.dataset.tool);
    if (b.dataset.act === "undo") { draws.pop(); sel = -1; hover = -1; showProps(); paint(); }
    if (b.dataset.act === "clear") { draws = []; sel = -1; hover = -1; showProps(); paint(); }
  };
  cv.addEventListener("mousedown", onDown);
  /* Полотно пропускає натискання до графіка скрізь, крім місць над
     фігурами, тож «клац по порожньому» до нього просто не доходить.
     Ловимо його на графіку: клацнули повз — знімаємо виділення. */
  chartEl.addEventListener("mousedown", (e) => {
    if (tool !== "cursor" || sel < 0) return;
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (hitAt(x, y) >= 0 || handleAt(x, y)) return;
    sel = -1; hover = -1;
    showProps(); paint();
  }, true);
  cv.addEventListener("dblclick", () => { if (sel >= 0) editText(); });
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  buildProps();

  /* угоди */
  $("btnBuy").onclick = () => askOrder("buy");
  $("btnSell").onclick = () => askOrder("sell");
  $("ordCancel").onclick = () => { $("ordModal").hidden = true; };
  $("ordGo").onclick = () => {
    $("ordModal").hidden = true;
    openPos($("ordModal").dataset.side,
            Number($("ordLot").value) || 1,
            Number($("ordSl").value) || 0,
            Number($("ordTp").value) || 0);
  };
  $("pos").onclick = (e) => {
    if (!e.target.closest("[data-close]")) return;
    const p = prices();
    if (p) closePos(openDeal.side === "buy" ? p.bid : p.ask, "вручну");
  };

  /* клавіші: стрілки — крок, пробіл — пуск/пауза */
  window.addEventListener("keydown", (e) => {
    if (/input|select|textarea/i.test((e.target.tagName || ""))) return;
    /* кнопки вже вміють завести прогін самі — не дублюємо це тут */
    if (e.key === "ArrowRight") { e.preventDefault(); $("rwFwd").click(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); $("rwBack").click(); }
    if (e.key === " ") { e.preventDefault(); $("rwPlay").click(); }
  });

  /* Escape кидає недомальоване: інакше фігура висіла б за курсором,
     поки її кудись не приткнеш. */
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && picking) { stopPick(); return; }
    if (e.key === "Escape" && (pend || armed || sel >= 0)) {
      sel = -1; showProps(); setTool("cursor"); paint();
    }
    if ((e.key === "Delete" || e.key === "Backspace") && sel >= 0 &&
        !/input|select|textarea/i.test(e.target.tagName || "")) {
      e.preventDefault();
      draws.splice(sel, 1); sel = -1; hover = -1; showProps(); paint();
    }
    if (e.key === "Shift" && pend && lastAt) aim(lastAt.x, lastAt.y, true);
  });
  /* Відпустили Shift, не ворухнувши мишею — вирівнювання треба зняти */
  window.addEventListener("keyup", (e) => {
    if (e.key === "Shift" && pend && lastAt) aim(lastAt.x, lastAt.y, false);
  });

  document.querySelectorAll(".modal").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m) m.hidden = true; });
  });
}

function askOrder(side) {
  if (!openDeal) {
    const m = $("ordModal");
    m.dataset.side = side;
    m.hidden = false;
    $("ordTitle").textContent = side === "buy" ? "Купівля" : "Продаж";
    const p = prices();
    $("ordNote").textContent = p
      ? "Ціна входу " + fmt(side === "buy" ? p.ask : p.bid) + ". Стоп і тейк рахуються від неї."
      : "";
  } else {
    hint("Спершу закрийте відкриту позицію", 3000);
  }
}

async function boot() {
  load();
  try {
    const r = await fetch("/api/candles/symbols");
    if (r.status === 401) { location.href = "/login"; return; }
    META = await r.json();
  } catch (e) {
    hint("Сервер не відповів", 0);
    return;
  }
  if (!META.symbols.some((s) => s.symbol === S.symbol)) {
    S.symbol = (META.symbols[0] || {}).symbol || "EURUSD";
  }
  const m = META.symbols.find((s) => s.symbol === S.symbol);
  if (m) {
    S.title = m.title; S.digits = m.digits;
    if (m.sources.indexOf(S.source) < 0) S.source = m.sources[0] || "";
    $("symName").textContent = m.symbol;
    $("symIco").textContent = m.title.slice(0, 1);
  }
  loadWL();
  makeChart();
  buildTfs(); buildSources(); buildWatch(); drawDeals(); wire();
  clock(); setInterval(clock, 1000);
  showLatest();
}



boot();

})();
