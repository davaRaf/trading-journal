/* ============================================================
   «Мої рахунки»: свій депозит і рахунки проп-фірм.

   Журнал рахує все у відсотках від депозиту — розміру депозиту він не
   знав ніколи. Тут людина каже, скільки грошей було на старті, і ті самі
   відсотки нарешті перетворюються на гроші: баланс, скільки лишилось до
   цілі, скільки лишилось до ліміту просадки.

   Звʼязок з угодами — по імені рахунку (поле «рахунок» в угоді). Тому
   картку можна завести пізніше за угоди: вони підтягнуться самі.

   Тут нічого не зберігається, крім опису рахунку. Гроші рахуються з угод,
   які вже лежать у S.trades — другий раз тягнути їх з сервера нема сенсу.
   ============================================================ */
(function(){

let ACCS = undefined;     /* undefined — ще не питали, [] — порожньо */
let openId = null;        /* у якої картки розгорнутий розбір */

function D(){ return DICT[window.LANG] || DICT.uk; }

/* ---------------- гроші ---------------- */

const SIGNS = {USD: "$", EUR: "€", GBP: "£", UAH: "₴", PLN: "zł"};

/* Гроші пишемо цілими: копійки на рахунку в 100 тисяч — шум, а колонки
   від них стрибають. Пробіл між тисячами нерозривний. */
function money(v, cur){
  if (v == null || isNaN(v)) return "—";
  const sign = v < 0 ? "−" : "";
  const abs = Math.round(Math.abs(v)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "\u202F");
  const s = SIGNS[cur] || "";
  return s ? sign + s + abs : sign + abs + "\u202F" + (cur || "");
}
function moneySigned(v, cur){
  if (v == null || isNaN(v)) return "—";
  return (v > 0 ? "+" : "") + money(v, cur);
}
function clamp(v, a, b){ return Math.max(a, Math.min(b, v)); }

/* ---------------- угоди рахунку ---------------- */

function key(s){ return String(s == null ? "" : s).trim().toLowerCase(); }

function tradesOf(acc){
  const nm = key(acc.name);
  if (!nm) return [];
  return sortAsc(S.trades.filter(t => key(t.account) === nm));
}

/* Скільки людина вже назбирала на цьому рахунку — і як воно йшло.
   Все у відсотках від депозиту, як і решта журналу; гроші зверху. */
function stat(acc){
  const all = tradesOf(acc);
  const list = realTrades(all);
  const c = calc(all);
  let acc_ = 0, peak = 0, dd = 0;
  const curve = [];
  const byDay = new Map();
  for (const t of list){
    const r = netR(t);
    acc_ += r;
    peak = Math.max(peak, acc_);
    dd = Math.min(dd, acc_ - peak);
    curve.push(acc_);
    const d = (t.date || "").slice(0, 10);
    if (d) byDay.set(d, (byDay.get(d) || 0) + r);
  }
  let worstDay = null, worstDayVal = 0;
  byDay.forEach((v, d) => { if (v < worstDayVal){ worstDayVal = v; worstDay = d; } });
  const start = acc.start_balance;
  const has = start != null && !isNaN(start) && start > 0;
  /* Баланс, переписаний з кабінету фірми, головніший за нашу арифметику:
     журнал знає лише ті угоди, що в ньому записані, а рахунок могли почати
     до журналу. Коли він заданий — рахуємо все від нього, а свою цифру
     лишаємо поруч окремим рядком, щоб розбіжність було видно, а не сховано. */
  const cur = acc.current_balance;
  const manual = cur != null && !isNaN(cur);
  const balance = manual ? cur : (has ? start * (1 + c.net / 100) : null);
  const net = (manual && has) ? (cur / start - 1) * 100 : c.net;
  return {
    n: c.n, skips: c.skips, wr: c.wr, avgRR: c.avgRR,
    net: net,                         /* підсумок у % від депозиту */
    journalNet: c.net,                /* стільки набігло за угодами журналу */
    manual: manual,
    /* Розбіжність показуємо лише коли вона помітна: копійка різниці —
       це округлення, а не привід малювати ще один рядок. */
    drift: (manual && has && Math.abs(c.net - net) > 0.01),
    maxDD: -dd,                       /* просадка від піку, у % (додатне) */
    worstDay, worstDayVal,
    curve, list, all,
    hasMoney: has || manual,
    hasPct: has,
    start: has ? start : null,
    profit: has ? balance - start : null,
    balance: balance,
    /* Скільки з дозволеної просадки вже витрачено. Рахуємо від старту, а
       не від піку: фірми рахують саме так, і людина порівнює з їхньою
       цифрою в кабінеті. */
    lost: Math.max(0, -net),
  };
}

/* ---------------- дрібні шматки розмітки ---------------- */

function cls(v){ return v > 0 ? "up" : (v < 0 ? "down" : ""); }

/* Смужка «скільки з чого». Число завжди підписане текстом поруч:
   на саму лише довжину смужки покладатись не можна. */
function bullet(label, val, limit, tone){
  const on = limit != null && limit > 0;
  const part = on ? clamp(val / limit * 100, 0, 100) : 0;
  const hot = on && part >= 70;
  return '<div class="ac-bul' + (hot ? " hot" : "") + '">'
    + '<div class="ac-bul-h"><span>' + esc(label) + "</span>"
    +   "<b>" + (on ? fmtR1(val) + " / " + fmtR1(limit) : fmtR1(val)) + "</b></div>"
    + '<div class="ac-bul-t"><i class="' + esc(tone || "") + '" style="width:'
    +   (on ? part.toFixed(1) : 0) + '%"></i></div>'
    + "</div>";
}
/* Відсотки рахунку пишемо без знака «плюс»: це не результат угоди, а
   межа або витрачена частка. */
function fmtR1(v){ return v == null || isNaN(v) ? "—" : (Math.round(v * 100) / 100) + "%"; }

/* Крива капіталу маленьким розчерком. Менше чотирьох точок не малюємо:
   по двох-трьох угодах «тренду» немає, це просто дві риски. */
function spark(curve){
  if (!curve || curve.length < 4) return "";
  const w = 260, h = 40, pad = 2;
  const lo = Math.min(0, ...curve), hi = Math.max(0, ...curve);
  const span = (hi - lo) || 1;
  const x = i => pad + i * (w - pad * 2) / (curve.length - 1);
  const y = v => h - pad - (v - lo) / span * (h - pad * 2);
  const pts = curve.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ");
  const zero = y(0).toFixed(1);
  const last = curve[curve.length - 1];
  return '<svg class="ac-spark" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none"'
    + ' aria-hidden="true">'
    + '<line x1="0" y1="' + zero + '" x2="' + w + '" y2="' + zero + '" class="z"/>'
    + '<polyline points="' + pts + '" class="' + cls(last) + '"/></svg>';
}

const STATUS_CLS = {active: "act", passed: "pass", failed: "fail", closed: "shut"};

/* ---------------- картка рахунку ---------------- */

function card(a){
  const d = D(), s = stat(a);
  const st = STATUS_CLS[a.status] || "act";
  const kind = d.kinds[a.kind] || "";
  const sub = [a.firm, a.opened_at ? d.since + " " + human(a.opened_at) : ""]
    .filter(Boolean).join(" · ");

  /* Шапка балансу. Без стартового балансу гроші рахувати нема з чого —
     показуємо відсотки й прямо кажемо, чого бракує. */
  let head;
  if (s.hasMoney){
    head = '<div class="ac-bal"><div class="big ' + cls(s.net) + '">'
      +   esc(money(s.balance, a.currency)) + "</div>"
      + (s.hasPct
          ? '<div class="ac-delta ' + cls(s.net) + '">' + esc(fmtR(s.net))
            +   '<i>·</i>' + esc(moneySigned(s.profit, a.currency)) + "</div>"
            + '<div class="ac-from">' + esc(d.fromStart + " " + money(s.start, a.currency))
            + "</div>"
          : '<div class="ac-from">' + esc(d.noStartPct) + "</div>")
      /* Своя цифра поруч, коли вона розійшлась із кабінетом: журнал бачить
         тільки записані угоди, і різниця — це те, чого в ньому немає. */
      + (s.drift ? '<div class="ac-drift">' + esc(d.byJournal) + " "
            + esc(fmtR(s.journalNet)) + "</div>" : "")
      + "</div>";
  } else {
    head = '<div class="ac-bal"><div class="big ' + cls(s.net) + '">' + esc(fmtR(s.net)) + "</div>"
      + '<div class="ac-nomoney">' + esc(d.noStart)
      +   ' <button class="ac-link" onclick="__acc.edit(' + a.id + ')">' + esc(d.setStart) + "</button></div></div>";
  }

  const bars = (a.target_pct || a.dd_total_pct || a.dd_daily_pct)
    ? '<div class="ac-bars">'
      + (a.target_pct ? bullet(d.toTarget, Math.max(0, s.net), a.target_pct, "up") : "")
      + (a.dd_total_pct ? bullet(d.ddTotal, s.lost, a.dd_total_pct, "down") : "")
      + (a.dd_daily_pct ? bullet(d.ddDaily, Math.abs(s.worstDayVal), a.dd_daily_pct, "down") : "")
      + "</div>"
    : "";

  const cells = [
    [d.nTrades, s.n + (s.skips ? " +" + s.skips + d.skipTag : "")],
    [d.wr, s.wr == null ? "—" : Math.round(s.wr) + "%"],
    [d.avgRR, s.avgRR == null ? "—" : (Math.round(s.avgRR * 100) / 100)],
    [d.maxDD, s.n ? fmtR1(s.maxDD) : "—"],
  ];
  const stats = '<div class="ac-cells">' + cells.map(c =>
    '<div class="ac-cell"><div class="l">' + esc(c[0]) + '</div><div class="v">'
    + esc(String(c[1])) + "</div></div>").join("") + "</div>";

  const dead = a.status === "failed";
  const foot = '<div class="ac-foot">'
    + (dead ? '<button class="ac-link" onclick="__acc.why(' + a.id + ')">'
        + esc(openId === a.id ? d.hideWhy : d.showWhy) + "</button>" : "")
    + '<button class="ac-link" onclick="__acc.attach(' + a.id + ')">'
    +   esc(d.attach) + "</button>"
    + '<span class="sp"></span>'
    + '<button class="ac-link" onclick="__acc.edit(' + a.id + ')">' + esc(d.edit) + "</button></div>";

  /* Рахунок без жодної угоди — найчастіше не порожній рахунок, а журнал,
     який вели до появи рахунків. Кажемо про це прямо в картці. */
  const orphan = (!s.n && !s.skips && S.trades.length)
    ? '<p class="ac-orphan">' + esc(d.noTrades)
      + ' <button class="ac-link" onclick="__acc.attach(' + a.id + ')">'
      + esc(d.attach) + "</button></p>"
    : "";

  /* Тип, фірма й дата — одним сірим рядком під назвою. Раніше тип стояв
     одразу за назвою, і в картці вужчій за 380 пікселів назва
     переносилась, а тип приклеювався до її хвоста: «100k ЧЕЛЕНДЖ». */
  const under = (kind ? '<i class="ac-kind">' + esc(kind) + "</i>" : "")
    + (sub ? (kind ? " · " : "") + esc(sub) : "");
  return '<div class="shell"><div class="core ac-card ' + st + '">'
    + '<div class="ac-top"><div class="ac-name"><b>' + esc(a.name) + "</b>"
    +   (under ? '<div class="ac-sub">' + under + "</div>" : "") + "</div>"
    + '<span class="ac-st ' + st + '">' + esc(d.status[a.status] || "") + "</span></div>"
    + head + orphan + spark(s.curve) + bars + stats
    + (dead && openId === a.id ? why(a, s) : "")
    + foot + "</div></div>";
}

/* ---------------- чому рахунок злили ---------------- */
/*
   Найкорисніше в розділі. Людина памʼятає останню угоду, а не всі; тут
   видно, що саме зʼїло рахунок: три найгірші угоди, день, коли пробило
   ліміт, і чого в збиткових угодах було найбільше.
*/
function dayOfBreak(a, s){
  if (!a.dd_total_pct) return null;
  let acc_ = 0;
  for (const t of s.list){
    acc_ += netR(t);
    if (acc_ <= -a.dd_total_pct) return {date: (t.date || "").slice(0, 10), at: acc_};
  }
  return null;
}
function topField(list, field){
  const m = groupByField(list, field);
  let best = null, bestN = 0;
  m.forEach((arr, v) => { if (arr.length > bestN){ bestN = arr.length; best = v; } });
  return best ? {name: best, n: bestN} : null;
}

function why(a, s){
  const d = D();
  const losers = s.list.filter(t => netR(t) < 0)
    .sort((x, y) => netR(x) - netR(y)).slice(0, 3);
  const brk = dayOfBreak(a, s);
  const mist = topField(s.list.filter(t => netR(t) < 0), "mistakes");
  const emo = topField(s.list.filter(t => netR(t) < 0), "emotion");

  let rows = "";
  if (brk) rows += line(d.brokeAt, human(brk.date) + " · " + fmtR(brk.at));
  if (s.worstDay) rows += line(d.worstDay, human(s.worstDay) + " · " + fmtR(s.worstDayVal));
  if (mist) rows += line(d.topMistake, mist.name + " · " + mist.n + d.timesTag);
  if (emo) rows += line(d.topEmotion, emo.name + " · " + emo.n + d.timesTag);
  if (a.reason) rows += line(d.reason, a.reason);

  const worst = losers.length
    ? '<div class="ac-worst"><div class="l">' + esc(d.worstTrades) + "</div>"
      + losers.map(t => '<div class="ac-wrow"><span>' + esc(t.pair || "—") + "</span>"
        + '<i>' + esc(human((t.date || "").slice(0, 10))) + "</i>"
        + '<b class="down">' + esc(fmtR(netR(t))) + "</b></div>").join("") + "</div>"
    : "";

  return '<div class="ac-why">' + (rows ? '<div class="ac-wlist">' + rows + "</div>" : "")
    + worst + "</div>";
}
function line(l, v){
  return '<div class="ac-wline"><span>' + esc(l) + "</span><b>" + esc(String(v)) + "</b></div>";
}

function human(iso){
  if (!iso) return "";
  const p = String(iso).split("-");
  return p.length === 3 ? p[2] + "." + p[1] + "." + p[0] : iso;
}

/* ---------------- форма рахунку ---------------- */

/* Проп-фірми, які зустрічаються найчастіше. Це підказка, а не довідник:
   поле лишається звичайним текстовим, і своє можна вписати завжди. Список
   не сортуємо за «популярністю» — просто ходові назви, щоб не набирати
   руками й не плодити «ФТМО», «ftmo» і «FTMO» в одному журналі. */
const FIRMS = ["FTMO", "FundingPips", "FundedNext", "The5ers", "Topstep",
  "Apex Trader Funding", "MyFundedFX", "E8 Markets", "Alpha Capital Group",
  "Take Profit Trader", "Goat Funded Trader", "Funded Trading Plus"];

/* Ряд підказок під полем. Значення підставляється в поле, а не замінює
   його: людина може взяти підказку й дописати до неї своє — «FTMO 100k». */
function picks(target, vals, cur){
  if (!vals || !vals.length) return "";
  const now = String(cur == null ? "" : cur).trim().toLowerCase();
  return '<div class="ac-picks" role="group">' + vals.map(v =>
    '<button type="button" class="ac-pick' + (v.toLowerCase() === now ? " on" : "")
    + '" data-fill="' + esc(v) + '" data-target="' + esc(target) + '">'
    + esc(v) + "</button>").join("") + "</div>";
}
/* `note` — тиха приписка збоку від підпису. Замінює абзац під полем:
   те, що вміщається у два слова, не варте окремого рядка тексту. */
function field(label, id, val, ph, type, note){
  return '<label class="ac-f"><span>' + esc(label)
    + (note ? '<i>' + esc(note) + '</i>' : "") + "</span>"
    + '<input class="ac-in" id="' + id + '" type="' + (type || "text") + '"'
    + (type === "number" ? ' step="any" inputmode="decimal"' : "")
    + ' value="' + esc(val == null ? "" : val) + '"'
    + (ph ? ' placeholder="' + esc(ph) + '"' : "") + "></label>";
}

/* Перемикачі й підказки рахунків слухаються одним обробником нижче:
   inline-onclick з рядком усередині вимагає трьох рівнів лапок і
   ламається на першому ж імені з апострофом. */
function seg(id, val, opts){
  return '<div class="ac-seg" id="' + id + '" data-seg="' + esc(id) + '">' + opts.map(o =>
    '<button type="button" data-v="' + esc(o[0]) + '"' + (o[0] === val ? ' class="on"' : "")
    + ">" + esc(o[1]) + "</button>").join("") + "</div>";
}

/* Поле дати. Рідний <input type="date"> відкриває календар браузера — його
   не можна ні пофарбувати, ні підігнати під теми: у темному журналі він
   світиться білим вікном Chrome. У журналі свій календар (DatePicker в
   ui.js), тим самим користуються фільтри й «Аналіз дня» — беремо його.
   Саме значення лежить у прихованому полі в ISO, на кнопці — по-людськи. */
function dateField(label, id, val, clear){
  /* «будь-коли» стоїть у рядку підпису праворуч: календар уміє поставити
     дату, але не прибрати, а порожня дата тут — це «за весь час». */
  return '<div class="ac-f"><span>' + esc(label)
    + (clear ? '<button type="button" class="ac-clear" data-clear="' + id + '">'
        + esc(D().anyDate) + "</button>" : "") + "</span>"
    + '<button type="button" class="ac-in ac-date" id="' + id + '_btn"'
    +   ' data-date="' + id + '"' + (val ? ' data-set="1"' : '') + '>'
    +   '<span>' + esc(val ? human(val) : D().pickDate) + '</span>'
    +   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    +   '<rect x="3" y="5" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/>'
    +   '<path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
    +   '</svg></button>'
    + '<input type="hidden" id="' + id + '" value="' + esc(val || '') + '"></div>';
}

/* Назва рахунку збирається сама: фірма, тип і розмір — «FTMO Челендж 100k».
   Саме так рахунки називають у розмові, і саме це людина потім впише в поле
   «рахунок» в угоді. Щойно назву правлять руками, збірка замовкає: своє імʼя
   головніше за наше. Порожнє поле знову вмикає її. */
function sizeTag(v){
  const n = Math.abs(Number(v));
  if (!n || isNaN(n)) return "";
  if (n >= 1000000) return (Math.round(n / 100000) / 10) + "M";
  if (n >= 1000) return Math.round(n / 1000) + "k";
  return String(Math.round(n));
}
function madeName(){
  const d = D();
  const firm = val("acFirm");
  const kind = segVal("acKind") || "own";
  const size = sizeTag(num("acStart"));
  /* Свій депозит фірми не має — його називаємо словом, інакше з порожньої
     фірми лишився б самий розмір: просто «100k». */
  /* У словнику типи написані з малої: там вони підписи кнопок. У назві
     рахунку це вже імʼя — «FTMO Челендж 100k», а не «FTMO челендж 100k». */
  const cap = t => t ? t.charAt(0).toUpperCase() + t.slice(1) : "";
  const head = firm || (kind === "own" ? cap(d.kinds.own) : "");
  const tag = kind === "own" ? "" : cap(d.kinds[kind]);
  return [head, tag, size].filter(Boolean).join(" ").trim();
}
let nameTouched = false;
function syncName(){
  const inp = document.getElementById("acName");
  if (!inp || nameTouched) return;
  inp.value = madeName();
}

/* Поле з готовим списком. Дванадцять фірм рядком підказок займали пів
   форми, тож тепер вони ховаються у список, який виїжджає знизу по
   натисканню. Список — той самий Pick, що й у фільтрах журналу: своє
   оформлення, анімація, стрілки й Escape уже в ньому.

   Поле лишається текстовим: список тільки підставляє значення, своє
   можна вписати завжди — фірм на світі більше, ніж у будь-якому списку. */
function comboField(label, id, val, ph){
  return '<div class="ac-f ac-combo">'
    + '<span>' + esc(label) + '</span>'
    /* Стан «список відкритий» тримає обгортка, бо саме вона — якір
       списку: інакше клік по стрілці рахувався б кліком повз поле, і
       список закривався б, щоб тут-таки відкритись знову. */
    + '<span class="ac-combo-in" role="combobox" aria-expanded="false">'
    +   '<input class="ac-in" id="' + id + '" type="text" autocomplete="off"'
    +     ' value="' + esc(val == null ? "" : val) + '"'
    +     ' placeholder="' + esc(ph || "") + '"'
    +     ' data-combo="1">'
    +   '<button type="button" class="ac-combo-x" data-combo-open="' + id + '"'
    +     ' aria-label="' + esc(D().pickFirm) + '">'
    +     '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    +     '<path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
    + '</span></div>';
}

function openFirms(inp){
  const d = D();
  /* Порожній рядок першим: свій депозит фірми не має, і прибрати її має
     бути так само просто, як вибрати. */
  const list = [{v: "", label: d.noFirm}].concat(FIRMS.map(v => ({v: v, label: v})));
  const box = inp.closest(".ac-combo-in") || inp;
  Pick.open(box, list, inp.value.trim(), v => {
    inp.value = v;
    syncName();
    inp.focus();
  });
}

/* Не кожен стан має сенс для кожного типу.

   «Пройдений» буває тільки в челенджа: це його єдина мета. Свій депозит і
   фандед проходити нема куди — їх торгують.

   Фандед ще й не «закривають»: його або торгують, або зливають, а піти з
   нього своєю волею — це не те саме, що закрити власний рахунок у брокера.

   Зайві варіанти не показуємо зовсім: вимкнена кнопка все одно змушує
   гадати, чому вона вимкнена. */
function statusesFor(kind){
  if (kind === "funded") return ["active", "failed"];
  if (kind === "own") return ["active", "failed", "closed"];
  return ["active", "passed", "failed", "closed"];
}
function statusSeg(kind, cur){
  const d = D();
  const allowed = statusesFor(kind);
  const on = allowed.indexOf(cur) >= 0 ? cur : "active";
  return seg("acStatus", on, allowed.map(v => [v, d.status[v]]));
}
/* Перемкнули тип — перебираємо стани заново. Якщо вибраного стану більше
   немає (був «Пройден», стало «фандед»), рахунок повертається в активні,
   а блок причини ховається слідом. */
function paintStatus(){
  const box = document.getElementById("acStatus");
  if (!box) return;
  const kind = segVal("acKind") || "own";
  const cur = segVal("acStatus") || "active";
  const fresh = statusSeg(kind, cur);
  const wrap = document.createElement("div");
  wrap.innerHTML = fresh;
  box.innerHTML = wrap.firstChild.innerHTML;
  const dead = document.getElementById("acDead");
  if (dead) dead.hidden = (segVal("acStatus") || "active") === "active";
}

function form(a){
  const d = D();
  const dead = a.status && a.status !== "active";
  nameTouched = !!(a.name || "").trim();   /* у готового рахунку назва вже своя */
  return '<div class="m-body ac-form">'
    /* Спершу фірма й тип, потім розмір — у цьому порядку з них і збирається
       назва. Саме поле назви стоїть нижче: воно тут підсумок, а не перше
       питання. */
    + '<div class="ac-row2">'
    +   comboField(d.fFirm, "acFirm", a.firm, d.phFirm)
    +   '<div class="ac-f"><span>' + esc(d.fKind) + "</span>"
    +     seg("acKind", a.kind || "own",
            [["own", d.kinds.own], ["challenge", d.kinds.challenge], ["funded", d.kinds.funded]])
    +   "</div></div>"
    + '<div class="ac-row3 ac-money">' + field(d.fStart, "acStart", a.start_balance, "100000", "number")
    +   field(d.fNow, "acNow", a.current_balance, d.phNow, "number")
    +   field(d.fCur, "acCur", a.currency || "USD", "USD") + "</div>"
    /* Назва — звʼязок з угодами, тому підказуємо тим, що вже стоїть в угодах. */
    + '<div>' + field(d.fName, "acName", a.name, d.phName, "text", d.nName)
    +   picks("acName", unlisted().slice(0, 6).map(r => r.name), a.name) + '</div>'
    + '<div class="ac-row3">' + field(d.fTarget, "acTarget", a.target_pct, d.noLimit, "number")
    +   field(d.fDdTotal, "acDdTotal", a.dd_total_pct, d.noLimit, "number")
    +   field(d.fDdDaily, "acDdDaily", a.dd_daily_pct, d.noLimit, "number") + "</div>"
    /* Дата вужча за половину рядка, а станів буває чотири — і в рівних
       половинках четвертий зривався на свій рядок. */
    + '<div class="ac-row2 ac-row-st">' + dateField(d.fOpened, "acOpened", a.opened_at)
    +   '<div class="ac-f"><span>' + esc(d.fStatus) + "</span>"
    +   statusSeg(a.kind || "own", a.status || "active") + "</div></div>"
    /* Дата закриття й причина зʼявляються тільки тоді, коли рахунку вже
       нема: живому рахунку їх заповнювати нема чого. */
    + '<div class="ac-dead" id="acDead"' + (dead ? "" : " hidden") + ">"
    +   '<div class="ac-row2">' + dateField(d.fClosed, "acClosed", a.closed_at)
    +     field(d.fReason, "acReason", a.reason, d.phReason) + "</div></div>"
    + field(d.fNote, "acNote", a.note, d.phNote)
    + '<p class="ac-err" id="acErr" hidden></p>'
    + "</div>";
}

function openForm(a){
  const d = D();
  const isNew = !a.id;
  openModal('<div class="m-head"><h2>' + esc(isNew ? d.newTitle : d.editTitle) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(d.close) + '">×</button></div>'
    + form(a)
    + '<div class="m-foot">'
    + (isNew ? "" : '<button class="btn danger" onclick="__acc.drop(' + a.id + ')">'
        + esc(d.del) + "</button>")
    + '<span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(d.cancel) + "</button>"
    + '<button class="btn primary" onclick="__acc.save(' + (a.id || 0) + ')">'
    +   esc(d.save) + "</button></div>");
  const nm = document.getElementById("acName");
  if (nm && isNew) nm.focus();
}

function segVal(id){
  const on = document.querySelector("#" + id + " button.on");
  return on ? on.dataset.v : "";
}
function val(id){
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}
function num(id){
  const v = val(id).replace(",", ".");
  if (!v) return null;
  const f = parseFloat(v);
  return isNaN(f) ? null : f;
}
function show(el, text){
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
}

async function save(id){
  const d = D();
  const err = document.getElementById("acErr");
  const acc = {
    id: id || null, name: val("acName"), firm: val("acFirm"), kind: segVal("acKind"),
    currency: val("acCur") || "USD", start_balance: num("acStart"),
    current_balance: num("acNow"),
    target_pct: num("acTarget"), dd_total_pct: num("acDdTotal"), dd_daily_pct: num("acDdDaily"),
    opened_at: val("acOpened"), status: segVal("acStatus"),
    closed_at: val("acClosed"), reason: val("acReason"), note: val("acNote"),
  };
  if (!acc.name){ show(err, d.errName); return; }
  try{
    await api("POST", "/api/accounts", {account: acc});
  }catch(e){
    /* 409 — таку назву вже носить інший рахунок. Помилка не про мережу,
       і людині треба сказати саме це. */
    show(err, /409/.test(String((e && e.message) || "")) ? d.errTaken : d.errSave);
    return;
  }
  closeModal();
  ACCS = undefined;
  await load();
}

async function drop(id){
  const d = D();
  if (!await Ask.yes(d.delAsk, {ok: d.delYes, cancel: d.cancel, danger: true})) return;
  try{ await api("POST", "/api/accounts/drop", {id: id}); }catch(e){ return; }
  closeModal();
  ACCS = undefined;
  await load();
}

/* ---------------- сам розділ ---------------- */

async function load(){
  try{
    ACCS = (await api("GET", "/api/accounts")).accounts || [];
  }catch(e){ ACCS = []; }
  if (S.view === "accounts") render();
}

/* Рахунки, які людина вже вписувала в угоди, але картки не завела.
   Не показати їх було б дивно: у журналі вони є, а в розділі про
   рахунки — немає. */
function unlisted(){
  const known = new Set((ACCS || []).map(a => key(a.name)));
  const seen = new Map();
  for (const t of S.trades){
    const k = key(t.account);
    if (!k || known.has(k)) continue;
    if (!seen.has(k)) seen.set(k, {name: (t.account || "").trim(), n: 0});
    seen.get(k).n++;
  }
  return [...seen.values()].sort((a, b) => b.n - a.n);
}

function total(){
  const d = D();
  const live = (ACCS || []).filter(a => a.status === "active");
  if (!live.length) return "";
  /* Складати гроші можна лише в одній валюті: перерахунку курсів у
     журналі немає, і вигадувати його тут не будемо. */
  const curs = new Set(live.map(a => a.currency || "USD"));
  const withMoney = live.filter(a => a.start_balance > 0);
  let sum = null;
  if (curs.size === 1 && withMoney.length){
    sum = withMoney.reduce((s, a) => s + stat(a).balance, 0);
  }
  return '<div class="ac-total"><span>' + esc(d.liveN.replace("%n", live.length)) + "</span>"
    + (sum != null ? "<b>" + esc(money(sum, [...curs][0])) + "</b>" : "") + "</div>";
}

function hints(){
  const d = D();
  const rest = unlisted();
  if (!rest.length) return "";
  return '<div class="shell"><div class="core ac-rest"><div class="l">' + esc(d.unlisted) + "</div>"
    + '<div class="ac-chips">' + rest.map(r =>
        '<button class="ac-chip" data-name="' + esc(r.name) + '">'
        + esc(r.name) + "<i>" + r.n + "</i></button>").join("") + "</div>"
    + '<p class="ac-hint">' + esc(d.unlistedHint) + "</p></div></div>";
}

function vAccounts(){
  const d = D();
  if (ACCS === undefined){
    load();
    return '<div class="empty">' + esc(d.loading) + "</div>";
  }
  /* Шапка спільна з «Оглядом»: заголовок там і є перемикачем вкладок.
     Без app.js (такого не буває, але хай) лишиться просто назва. */
  const head = '<div class="ohead ac-head">'
    + (window.ovTabsHtml ? ovTabsHtml("accounts") : "<h1>" + esc(d.title) + "</h1>") + total()
    + '<button class="btn primary ac-new" id="acAdd">' + esc(d.add) + "</button></div>";

  if (!ACCS.length){
    return '<div class="acw">' + head
      + '<div class="shell"><div class="core ac-empty">'
      + "<p>" + esc(d.emptyLead) + '</p><p class="ac-hint">' + esc(d.emptyHint) + "</p>"
      + '<button class="btn primary" id="acAdd2">' + esc(d.add) + "</button>"
      + "</div></div>" + hints() + "</div>";
  }
  return '<div class="acw">' + head
    + '<div class="ac-grid">' + ACCS.map(card).join("") + "</div>" + hints() + "</div>";
}

/* ---------------- привʼязати вже записані угоди ---------------- */
/* Журнал вели й до того, як зʼявились рахунки: угоди лежать або зовсім
   без рахунку, або підписані як завгодно. Переносимо їх пачкою —
   міняється тільки поле «рахунок», самі угоди лишаються на місці. */

/* Під якими іменами лежать угоди зараз. Порожній рядок — окремим
   пунктом: «без рахунку» це теж відповідь, і саме він потрібен тим, хто
   поле ніколи не заповнював. */
function sources(acc){
  const mine = key(acc.name);
  const m = new Map();
  for (const t of S.trades){
    const v = (t.account || "").trim();
    if (key(v) === mine) continue;
    const k = v.toLowerCase();
    if (!m.has(k)) m.set(k, {value: v, n: 0});
    m.get(k).n++;
  }
  /* «Без рахунку» першим: з нього переносять найчастіше. Решта — за
     кількістю угод, бо великий рахунок шукають очима першим. */
  return [...m.values()].sort((a, b) =>
    (a.value === "" ? -1 : b.value === "" ? 1 : b.n - a.n));
}

/* Скільки угод потрапляє під вибір. Рахуємо тут, а не на сервері: угоди
   вже завантажені, і цифра має мінятись одразу, поки крутять дати. */
function hits(vals, from, to){
  const set = new Set(vals.map(v => v.toLowerCase()));
  let n = 0;
  for (const t of S.trades){
    if (!set.has((t.account || "").trim().toLowerCase())) continue;
    const day = (t.date || "").slice(0, 10);
    if (from && day < from) continue;
    if (to && day > to) continue;
    n++;
  }
  return n;
}

let atAcc = null;   /* до якого рахунку прикріплюємо — читає обробник */

function atPicked(){
  return [...document.querySelectorAll(".ac-srcb.on")].map(b => b.dataset.v);
}
function atVal(id){
  const el = document.getElementById(id);
  return el ? el.value : "";
}

/* Підпис під вибором і стан кнопки. Одна функція на всі зміни у вікні:
   що змінилось — байдуже, цифру однаково перераховуємо повністю. */
function atPaint(){
  const d = D(), box = document.getElementById("atFound");
  if (!box || !atAcc) return;
  const n = hits(atPicked(), atVal("atFrom"), atVal("atTo"));
  box.textContent = n
    ? d.attachFound.replace("%n", n + " " + (typeof ovWord === "function" ? ovWord(n) : ""))
    : d.attachNone;
  box.classList.toggle("none", !n);
  const go = document.getElementById("atGo");
  if (go){ go.disabled = !n; go.textContent = d.attach; }
}

function attachForm(acc){
  const d = D();
  atAcc = acc;
  const src = sources(acc);
  if (!src.length){
    Ask.yes(d.attachEmpty, {ok: d.close, cancel: ""});
    return;
  }
  /* «Без рахунку» вибрано одразу, якщо таке є: це той самий випадок,
     заради якого вікно й зроблене. */
  const first = src.find(x => x.value === "") || src[0];
  const chips = src.map(x =>
    '<button type="button" class="ac-srcb' + (x === first ? " on" : "") + '"'
    + ' data-v="' + esc(x.value) + '">'
    + esc(x.value || d.noAcc) + "<i>" + x.n + "</i></button>").join("");

  openModal('<div class="m-head"><h2>' + esc(d.attach) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(d.close) + '">×</button></div>'
    + '<div class="m-body ac-form ac-attach">'
    +   '<p class="ac-hint">' + esc(d.attachTo.replace("%s", acc.name)) + "</p>"
    +   '<div class="ac-f"><span>' + esc(d.attachFrom) + "</span>"
    +     '<div class="ac-src">' + chips + "</div></div>"
    +   '<div class="ac-row2">' + dateField(d.attachSince, "atFrom", "", 1)
    +     dateField(d.attachUntil, "atTo", "", 1) + "</div>"
    +   '<p class="ac-found" id="atFound"></p>'
    + "</div>"
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(d.cancel) + "</button>"
    + '<button class="btn primary" id="atGo" onclick="__acc.attachGo()">'
    +   esc(d.attach) + "</button></div>");
  atPaint();
}

async function attachGo(){
  const d = D(), acc = atAcc;
  if (!acc) return;
  const vals = atPicked(), from = atVal("atFrom"), to = atVal("atTo");
  const n = hits(vals, from, to);
  if (!n) return;
  /* Питаємо перед тим, як міняти: правка гуртова, і відкотити її можна
     лише таким самим перенесенням назад. */
  const ask = d.attachAsk.replace("%n", n + " " + (typeof ovWord === "function" ? ovWord(n) : ""))
    .replace("%s", acc.name);
  if (!await Ask.yes(ask, {ok: d.attach, cancel: d.cancel})) return;
  try{
    await api("POST", "/api/accounts/attach",
      {id: acc.id, values: vals, from: from, to: to});
  }catch(e){ return; }
  closeModal();
  atAcc = null;
  ACCS = undefined;
  /* Угоди перечитуємо: рахунок у них тепер інший, а з них рахується все. */
  try{ await reload(); }catch(e){}
  await load();
}

function blank(){ return {name: "", firm: "", kind: "own", currency: "USD", status: "active"}; }

/* Один обробник на весь розділ і на вікно форми: розмітка
   перемальовується цілком, і вішати слухачів на кожну кнопку заново
   довелось би після кожного кроку. */
document.addEventListener("click", e => {
  const seg = e.target.closest(".ac-seg button");
  if (seg){
    const box = seg.closest(".ac-seg");
    box.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === seg));
    if (box.dataset.seg === "acStatus"){
      const dead = document.getElementById("acDead");
      if (dead) dead.hidden = seg.dataset.v === "active";
    }
    if (box.dataset.seg === "acKind"){ syncName(); paintStatus(); }
    return;
  }
  /* Звідки брати угоди: кілька імен одночасно, тож не сегмент, а
     незалежні перемикачі. Після кожного — перерахунок цифри. */
  const src = e.target.closest(".ac-srcb");
  if (src){
    src.classList.toggle("on");
    atPaint();
    return;
  }

  /* Скинути дату: календар уміє поставити дату, але не прибрати. */
  const clr = e.target.closest(".ac-clear");
  if (clr){
    const hid = document.getElementById(clr.dataset.clear);
    const btn = document.getElementById(clr.dataset.clear + "_btn");
    if (hid) hid.value = "";
    if (btn){
      btn.removeAttribute("data-set");
      const lab = btn.querySelector("span");
      if (lab) lab.textContent = D().pickDate;
    }
    atPaint();
    return;
  }

  /* Підказка під полем: підставляємо значення й підсвічуємо саме її.
     Стоїть до перевірки на розділ — форма живе у вікні, а не на сторінці. */
  /* Поле фірми: список виїжджає знизу. Ловимо і саме поле, і стрілку
     праворуч — обидва відкривають те саме. */
  const cb = e.target.closest("[data-combo], [data-combo-open]");
  if (cb){
    const inp = cb.dataset.comboOpen
      ? document.getElementById(cb.dataset.comboOpen) : cb;
    if (inp) openFirms(inp);
    return;
  }

  /* Кнопка дати: свій календар журналу. Він малюється в body, тож вікно
     форми його не обрізає. */
  const db = e.target.closest(".ac-date");
  if (db){
    const hid = document.getElementById(db.dataset.date);
    DatePicker.open(db, {mode: "single", value: (hid && hid.value) || "",
      onPick: key => {
        if (hid) hid.value = key;
        const lab = db.querySelector("span");
        if (lab) lab.textContent = key ? human(key) : D().pickDate;
        if (key) db.setAttribute("data-set", "1");
        else db.removeAttribute("data-set");
        /* У вікні привʼязки від дати залежить цифра під вибором. У формі
           рахунку цієї цифри немає, і виклик нічого не робить. */
        atPaint();
      }});
    return;
  }

  const p = e.target.closest(".ac-pick");
  if (p){
    const inp = document.getElementById(p.dataset.target);
    if (inp){
      inp.value = p.dataset.fill;
      inp.focus();
      p.parentNode.querySelectorAll(".ac-pick")
        .forEach(b => b.classList.toggle("on", b === p));
      if (p.dataset.target === "acName") nameTouched = true;
      else syncName();
    }
    return;
  }

  if (S.view !== "accounts") return;
  const add = e.target.closest("#acAdd, #acAdd2");
  if (add){ __acc.add(); return; }
  const chip = e.target.closest(".ac-chip");
  if (chip){ __acc.addNamed(chip.dataset.name || ""); return; }
});

/* Набрав руками — підсвітка підказки має відповідати тому, що в полі,
   інакше вибраною лишається кнопка, якої в полі вже немає. */
document.addEventListener("input", e => {
  const inp = e.target;
  if (!inp.classList || !inp.classList.contains("ac-in")) return;
  /* Шукаємо підказки саме цього поля за data-target, а не по сусідах:
     інакше правка «Нотатки» перемальовувала б підказки «Назви» —
     вони лежать в одному вікні. */
  const mine = document.querySelectorAll('.ac-pick[data-target="' + inp.id + '"]');
  if (!mine.length) return;
  const now = inp.value.trim().toLowerCase();
  mine.forEach(b => b.classList.toggle("on", b.dataset.fill.toLowerCase() === now));
});

/* Назва живе своїм життям, щойно її торкнулись руками. Порожнє поле
   означає «збери сам» — так її можна повернути, стерши. */
document.addEventListener("input", e => {
  const id = e.target && e.target.id;
  /* Почав друкувати — значить пише своє: список тут уже заважає, бо
     затуляє поле й показує не те, що набирають. */
  if (window.Pick && Pick.isOpen && Pick.isOpen()) Pick.close();
  if (id === "acName") nameTouched = !!e.target.value.trim();
  else if (id === "acFirm" || id === "acStart") syncName();
});

/* Гачок для перевірок: збірку назви інакше не викликати ззовні. */
window.__accTest = {sync: syncName, made: madeName, firms: openFirms,
  status: paintStatus, hits: hits, sources: sources};

window.__acc = {
  add(){
    if (window.Guest && Guest.block(D().title)) return;
    openForm(blank());
  },
  addNamed(name){
    if (window.Guest && Guest.block(D().title)) return;
    const a = blank();
    a.name = name;
    openForm(a);
  },
  edit(id){
    const a = (ACCS || []).find(x => x.id === id);
    if (a) openForm(Object.assign({}, a));
  },
  why(id){ openId = openId === id ? null : id; render(); },
  attach(id){
    if (window.Guest && Guest.block(D().attach)) return;
    const a = (ACCS || []).find(x => x.id === id);
    if (a) attachForm(a);
  },
  attachGo: attachGo,
  /* Підпис вкладки для шапки «Огляду»: словник розділу лежить у цьому
     файлі, тож app.js питає його звідси. */
  navLabel(){ return D().navTitle; },
  save: save,
  drop: drop,
  reload(){ ACCS = undefined; },
};

VIEWS.accounts = vAccounts;
/* У бектесті рахунків немає: у прогоні на історії нема ні грошей, ні
   ліміту просадки — там нема чого зливати. */
if (typeof BT_HIDDEN !== "undefined") BT_HIDDEN.accounts = 1;
/* Перевірка на typeof навмисна: BT_HIDDEN оголошений через const у app.js,
   тож на window його немає, і звичайне звернення до нього до виїзду
   бектесту впало б з ReferenceError — разом з усім розділом. */

/* Окремого пункту в бічній панелі більше немає: рахунки — вкладка
   «Огляду». Підпис вкладки бере ovTabsHtml() з __acc.navLabel(), а мову
   він перечитує сам — applyLang наприкінці перемальовує весь екран. */

/* ============================================================
   Словник розділу. Лежить тут, а не в i18n.js: розділ ще ворушиться,
   і так його правки не чіпають спільний файл.
   ============================================================ */
const DICT = {
uk: {
  title: "Мої рахунки", navTitle: "Рахунки", navTip: "Свій депозит і рахунки проп-фірм: баланс, ціль, ліміти",
  loading: "Хвилинку…", add: "Новий рахунок", close: "Закрити", cancel: "Скасувати",
  save: "Зберегти", edit: "Правити", del: "Видалити",
  delAsk: "Прибрати картку рахунку? Угоди лишаться в журналі.",
  delYes: "Прибрати",
  liveN: "живих рахунків: %n",
  since: "з", fromStart: "старт", noStart: "Стартовий баланс не заданий — гроші рахувати нема з чого.",
  setStart: "задати",
  toTarget: "До цілі", ddTotal: "Загальна просадка", ddDaily: "Найгірший день",
  nTrades: "Угод", wr: "Вінрейт", avgRR: "Середній RR", maxDD: "Просадка від піку",
  skipTag: " скіп",
  showWhy: "Чому злили", hideWhy: "Згорнути",
  brokeAt: "Ліміт пробито", worstDay: "Найгірший день", topMistake: "Найчастіша помилка",
  topEmotion: "Найчастіша емоція", reason: "Причина", worstTrades: "Найгірші угоди",
  timesTag: " раз",
  status: {active: "Активний", passed: "Пройдений", failed: "Злитий", closed: "Закритий"},
  kinds: {own: "свій депозит", challenge: "челендж", funded: "фандед"},
  newTitle: "Новий рахунок", editTitle: "Рахунок",
  fName: "Назва", fFirm: "Фірма", fKind: "Тип", fStart: "Стартовий баланс", fCur: "Валюта",
  fTarget: "Ціль, %", fDdTotal: "Ліміт просадки, %", fDdDaily: "Денний ліміт, %",
  fOpened: "Відкритий", fStatus: "Стан", fClosed: "Закритий", fReason: "Причина",
  fNote: "Нотатка",
  fNow: "Баланс зараз", phNow: "з кабінету", pickDate: "обрати дату",
  pickFirm: "Обрати фірму", noFirm: "без фірми",
  noLimit: "немає", nName: "як в угодах",
  noStartPct: "Стартовий баланс не заданий — відсотків не порахувати.",
  byJournal: "за угодами журналу:",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "перевищив денний ліміт",
  phNote: "що завгодно про цей рахунок",
  emptyLead: "Тут будуть твої рахунки: свій депозит і все, що взяв у проп-фірм.",
  emptyHint: "Заведи рахунок — і журнал перестане рахувати самими відсотками: покаже баланс у грошах, скільки лишилось до цілі й скільки до ліміту просадки.",
  unlisted: "Є в угодах, але картки немає",
  unlistedHint: "Ці назви вже стоять у твоїх угодах. Натисни — і заведемо картку з цією назвою.",
  errName: "Без назви рахунок не знайде своїх угод.", errTaken: "Рахунок з такою назвою вже є.",
  errSave: "Не вдалось зберегти. Спробуй ще раз.",
  /* перенесення вже записаних угод на рахунок */
  attach: "Прив'язати угоди",
  attachTo: "До рахунку «%s». Самі угоди лишаться на місці — зміниться тільки те, на якому вони рахунку.",
  attachFrom: "Звідки брати",
  noAcc: "без рахунку",
  attachSince: "З дати",
  attachUntil: "По дату",
  anyDate: "будь-коли",
  attachFound: "Потрапляє %n",
  attachNone: "Нічого не потрапляє",
  attachAsk: "Перенести %n на рахунок «%s»?",
  attachEmpty: "Усі угоди журналу вже стоять на цьому рахунку — переносити нема чого.",
  noTrades: "Жодної угоди на цьому рахунку. Якщо журнал вели раніше — угоди можна перенести сюди.",
},
ru: {
  title: "Мои счета", navTitle: "Счета", navTip: "Свой депозит и счета проп-фирм: баланс, цель, лимиты",
  loading: "Минутку…", add: "Новый счёт", close: "Закрыть", cancel: "Отмена",
  save: "Сохранить", edit: "Править", del: "Удалить",
  delAsk: "Убрать карточку счёта? Сделки останутся в журнале.",
  delYes: "Убрать",
  liveN: "живых счетов: %n",
  since: "с", fromStart: "старт", noStart: "Стартовый баланс не задан — деньги считать не из чего.",
  setStart: "задать",
  toTarget: "До цели", ddTotal: "Общая просадка", ddDaily: "Худший день",
  nTrades: "Сделок", wr: "Винрейт", avgRR: "Средний RR", maxDD: "Просадка от пика",
  skipTag: " скип",
  showWhy: "Почему слили", hideWhy: "Свернуть",
  brokeAt: "Лимит пробит", worstDay: "Худший день", topMistake: "Частая ошибка",
  topEmotion: "Частая эмоция", reason: "Причина", worstTrades: "Худшие сделки",
  timesTag: " раз",
  status: {active: "Активный", passed: "Пройден", failed: "Слит", closed: "Закрыт"},
  kinds: {own: "свой депозит", challenge: "челлендж", funded: "фандед"},
  newTitle: "Новый счёт", editTitle: "Счёт",
  fName: "Название", fFirm: "Фирма", fKind: "Тип", fStart: "Стартовый баланс", fCur: "Валюта",
  fTarget: "Цель, %", fDdTotal: "Лимит просадки, %", fDdDaily: "Дневной лимит, %",
  fOpened: "Открыт", fStatus: "Состояние", fClosed: "Закрыт", fReason: "Причина",
  fNote: "Заметка",
  fNow: "Баланс сейчас", phNow: "из кабинета", pickDate: "выбрать дату",
  pickFirm: "Выбрать фирму", noFirm: "без фирмы",
  noLimit: "нет", nName: "как в сделках",
  noStartPct: "Стартовый баланс не задан — процентов не посчитать.",
  byJournal: "по сделкам журнала:",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "превысил дневной лимит",
  phNote: "что угодно про этот счёт",
  emptyLead: "Здесь будут твои счета: свой депозит и всё, что взял у проп-фирм.",
  emptyHint: "Заведи счёт — и журнал перестанет считать одними процентами: покажет баланс в деньгах, сколько осталось до цели и сколько до лимита просадки.",
  unlisted: "Есть в сделках, но карточки нет",
  unlistedHint: "Эти названия уже стоят в твоих сделках. Нажми — и заведём карточку с этим названием.",
  errName: "Без названия счёт не найдёт своих сделок.", errTaken: "Счёт с таким названием уже есть.",
  errSave: "Не удалось сохранить. Попробуй ещё раз.",
  /* перенесення вже записаних угод на рахунок */
  attach: "Привязать сделки",
  attachTo: "К счёту «%s». Сами сделки останутся на месте — изменится только то, на каком они счёте.",
  attachFrom: "Откуда брать",
  noAcc: "без счёта",
  attachSince: "С даты",
  attachUntil: "По дату",
  anyDate: "любая",
  attachFound: "Попадает %n",
  attachNone: "Ничего не попадает",
  attachAsk: "Перенести %n на счёт «%s»?",
  attachEmpty: "Все сделки журнала уже стоят на этом счёте — переносить нечего.",
  noTrades: "Ни одной сделки на этом счёте. Если журнал вели раньше — сделки можно перенести сюда.",
},
en: {
  title: "My accounts", navTitle: "Accounts", navTip: "Your own deposit and prop firm accounts: balance, target, limits",
  loading: "One moment…", add: "New account", close: "Close", cancel: "Cancel",
  save: "Save", edit: "Edit", del: "Delete",
  delAsk: "Remove this account card? The trades stay in the journal.",
  delYes: "Remove",
  liveN: "live accounts: %n",
  since: "since", fromStart: "start", noStart: "No starting balance yet — nothing to count money from.",
  setStart: "set it",
  toTarget: "To target", ddTotal: "Total drawdown", ddDaily: "Worst day",
  nTrades: "Trades", wr: "Win rate", avgRR: "Average RR", maxDD: "Drawdown from peak",
  skipTag: " skip",
  showWhy: "Why it blew", hideWhy: "Collapse",
  brokeAt: "Limit breached", worstDay: "Worst day", topMistake: "Most common mistake",
  topEmotion: "Most common emotion", reason: "Reason", worstTrades: "Worst trades",
  timesTag: "x",
  status: {active: "Active", passed: "Passed", failed: "Blown", closed: "Closed"},
  kinds: {own: "own deposit", challenge: "challenge", funded: "funded"},
  newTitle: "New account", editTitle: "Account",
  fName: "Name", fFirm: "Firm", fKind: "Type", fStart: "Starting balance", fCur: "Currency",
  fTarget: "Target, %", fDdTotal: "Drawdown limit, %", fDdDaily: "Daily limit, %",
  fOpened: "Opened", fStatus: "Status", fClosed: "Closed", fReason: "Reason",
  fNote: "Note",
  fNow: "Balance now", phNow: "from the dashboard", pickDate: "pick a date",
  pickFirm: "Pick a firm", noFirm: "no firm",
  noLimit: "none", nName: "as in trades",
  noStartPct: "No starting balance — percentages cannot be counted.",
  byJournal: "by journal trades:",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "went past the daily limit",
  phNote: "anything about this account",
  emptyLead: "Your accounts live here: your own deposit and everything you took from prop firms.",
  emptyHint: "Add an account and the journal stops counting in percent alone: it shows the balance in money, how far the target is and how much drawdown is left.",
  unlisted: "In your trades, but no card yet",
  unlistedHint: "These names already appear in your trades. Tap one and we will create a card with that name.",
  errName: "Without a name the account cannot find its trades.", errTaken: "An account with this name already exists.",
  errSave: "Could not save. Please try again.",
  /* перенесення вже записаних угод на рахунок */
  attach: "Attach trades",
  attachTo: "To “%s”. The trades stay where they are — only the account on them changes.",
  attachFrom: "Take from",
  noAcc: "no account",
  attachSince: "From",
  attachUntil: "To",
  anyDate: "any",
  attachFound: "Matches %n",
  attachNone: "Nothing matches",
  attachAsk: "Move %n to “%s”?",
  attachEmpty: "Every trade in the journal already sits on this account — nothing to move.",
  noTrades: "No trades on this account yet. If you kept the journal earlier, the trades can be moved here.",
},
};


})();
