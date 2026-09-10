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

/* Імʼя рахунку до одного вигляду — так само, як це робить сервер
   (`norm_name` в accounts_store.py). Будь-який пробільний символ зводимо
   до звичайного пробілу, повтори схлопуємо, краї обрізаємо: нерозривний
   пробіл із буфера обміну чи зайвий пробіл у кінці на око не видно, а
   картка через нього лишалась зовсім без угод. */
function normName(s){ return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }
function key(s){ return normName(s).toLowerCase(); }

/* Вільне імʼя: якщо таке вже носить інший рахунок, дописуємо номер.
   Повторює `free_name` на сервері — сервер лишається головним, а тут це
   потрібно, щоб сказати людині про перейменування до збереження, а не
   поставити її перед фактом після. */
function stemOf(name){
  const i = name.lastIndexOf(" ");
  if (i <= 0) return name;
  const tail = name.slice(i + 1);
  return (tail.length <= 3 && tail === String(parseInt(tail, 10))) ? name.slice(0, i) : name;
}
function freeName(name, selfId){
  const base = normName(name);
  if (!base) return base;
  const taken = new Set((ACCS || [])
    .filter(a => a.id !== selfId).map(a => key(a.name)));
  if (!taken.has(base.toLowerCase())) return base;
  const stem = stemOf(base);
  for (let n = 2; n < 1000; n++){
    const cand = stem + " " + n;
    if (!taken.has(cand.toLowerCase())) return cand;
  }
  return base;
}

function tradesOf(acc){
  const nm = key(acc.name);
  if (!nm) return [];
  return sortAsc(S.trades.filter(t => key(t.account) === nm));
}

/* Скільки людина вже назбирала на цьому рахунку — і як воно йшло.
   Все у відсотках від депозиту, як і решта журналу; гроші зверху.

   Відсотки складаються не додаванням, а множенням: +2% і ще +2% — це
   +4.04%, а не +4%. Решта журналу рахує простою сумою, і це доречно там,
   де йдеться про якість торгівлі. Але тут ідеться про гроші на рахунку, і
   людина звіряє їх із кабінетом фірми, де баланс рахують саме множенням.
   На довгій дистанції проста сума розходиться з кабінетом на відсотки. */
function stat(acc){
  const named = tradesOf(acc);
  /* Угоди, записані до дати відкриття рахунку, до нього не належать:
     це попередній рахунок під тією ж назвою — той самий челендж, узятий
     удруге. Скільки їх відсіклось, картка скаже вголос. */
  const from = acc.opened_at || "";
  const all = from ? named.filter(t => (t.date || "").slice(0, 10) >= from) : named;
  const before = named.length - all.length;
  const list = realTrades(all);
  const c = calc(all);
  let f = 1, peakF = 1, dd = 0;
  const curve = [];
  const byDay = new Map();
  let curDay = null, dayF = 1;
  for (const t of list){
    const d = (t.date || "").slice(0, 10);
    /* Угоди йдуть за датою, тож день починається на першій своїй угоді.
       Денний результат — теж множенням, від балансу на ранок: денний
       ліміт фірми рахують від нього, а не від стартового депозиту. */
    if (d !== curDay){ curDay = d; dayF = f; }
    f = Math.max(0, f * (1 + netR(t) / 100));
    peakF = Math.max(peakF, f);
    dd = Math.min(dd, (f / peakF - 1) * 100);
    curve.push((f - 1) * 100);
    if (d) byDay.set(d, dayF > 0 ? (f / dayF - 1) * 100 : 0);
  }
  let worstDay = null, worstDayVal = 0;
  byDay.forEach((v, d) => { if (v < worstDayVal){ worstDayVal = v; worstDay = d; } });
  const grown = (f - 1) * 100;        /* підсумок за угодами журналу, % */
  const start = acc.start_balance;
  const has = start != null && !isNaN(start) && start > 0;
  /* Баланс, переписаний з кабінету фірми, головніший за нашу арифметику:
     журнал знає лише ті угоди, що в ньому записані, а рахунок могли почати
     до журналу. Але сама по собі та цифра застигає: людина переписала
     баланс, записала ще десять угод — і картка показувала б те саме число.
     Тому від вписаного балансу далі йдемо угодами, записаними після нього.

     Межа — не дата, а `balance_n`: скільки угод цього рахунку вже лежало
     в журналі, коли баланс вписали. Дата тут занадто груба міра — угоди
     того самого дня випадали з підрахунку зовсім, і людина, яка завела
     рахунок і тут-таки записала дві угоди, бачила колишнє число. */
  const cur = acc.current_balance;
  const manual = cur != null && !isNaN(cur);
  let since = 1;
  if (manual){
    for (const t of named.slice(Math.max(0, acc.balance_n || 0))){
      since *= 1 + netR(t) / 100;
    }
  }
  const balance = manual ? cur * since : (has ? start * f : null);
  const net = (manual && has) ? (balance / start - 1) * 100 : grown;
  return {
    n: c.n, skips: c.skips, wr: c.wr, avgRR: c.avgRR,
    net: net,                         /* підсумок у % від депозиту */
    journalNet: grown,                /* стільки набігло за угодами журналу */
    manual: manual,
    /* Розбіжність показуємо лише коли вона помітна: копійка різниці —
       це округлення, а не привід малювати ще один рядок. */
    drift: (manual && has && Math.abs(grown - net) > 0.01),
    maxDD: -dd,                       /* просадка від піку, у % (додатне) */
    worstDay, worstDayVal,
    curve, list, all, before,
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

/* Крива капіталу маленьким розчерком. Двох точок уже досить: на новому
   рахунку саме перші угоди й цікаві, а порожнє місце замість графіка
   читалось як зламана картка. */
function spark(curve){
  if (!curve || curve.length < 2) return "";
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
      /* Звідки взявся баланс: цифра з кабінету на таку-то дату, а далі
         вже наша арифметика по записаних угодах. Без цього рядка вписаний
         руками баланс не відрізнити від порахованого. */
      + (s.manual && a.balance_at
          ? '<div class="ac-drift">' + esc(d.balAt.replace("%s", human(a.balance_at)))
            + "</div>" : "")
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

  /* Угоди старші за дату відкриття в рахунок не пішли. Мовчати про це
     не можна: людина бачить їх у журналі під цією ж назвою і мала б
     право вважати, що картка їх загубила. */
  const cut = s.before
    ? '<p class="ac-note">' + esc(d.beforeOpen.replace("%n", s.before)) + "</p>"
    : "";

  const dead = a.status === "failed";
  const foot = '<div class="ac-foot">'
    + (dead ? '<button class="ac-link" onclick="__acc.why(' + a.id + ')">'
        + esc(openId === a.id ? d.hideWhy : d.showWhy) + "</button>" : "")
    + '<span class="sp"></span>'
    + '<button class="ac-link" onclick="__acc.edit(' + a.id + ')">' + esc(d.edit) + "</button></div>";

  /* Тип, фірма й дата — одним сірим рядком під назвою. Раніше тип стояв
     одразу за назвою, і в картці вужчій за 380 пікселів назва
     переносилась, а тип приклеювався до її хвоста: «100k ЧЕЛЕНДЖ». */
  const under = (kind ? '<i class="ac-kind">' + esc(kind) + "</i>" : "")
    + (sub ? (kind ? " · " : "") + esc(sub) : "");
  return '<div class="shell"><div class="core ac-card ' + st + '">'
    + '<div class="ac-top"><div class="ac-name"><b>' + esc(a.name) + "</b>"
    +   (under ? '<div class="ac-sub">' + under + "</div>" : "") + "</div>"
    + '<span class="ac-st ' + st + '">' + esc(d.status[a.status] || "") + "</span></div>"
    + head + spark(s.curve) + bars + stats + cut
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
  let f = 1;
  for (const t of s.list){
    f *= 1 + netR(t) / 100;
    const at = (f - 1) * 100;
    if (at <= -a.dd_total_pct) return {date: (t.date || "").slice(0, 10), at: at};
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
function dateField(label, id, val){
  return '<div class="ac-f"><span>' + esc(label) + '</span>'
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
let editId = null;          /* який рахунок правимо: своє імʼя не рахуємо зайнятим */

/* Сервер не відмовляє через збіг назв — він дописує номер. Але дізнаватись
   про це вже після збереження людина не має: тут вона бачить майбутню
   назву ще до натискання «Зберегти». */
function paintTaken(){
  const box = document.getElementById("acTaken");
  if (!box) return;
  const inp = document.getElementById("acName");
  const nm = normName(inp ? inp.value : "");
  const free = freeName(nm, editId);
  const busy = !!nm && free !== nm;
  box.textContent = busy ? D().willRename.replace("%s", free) : "";
  box.hidden = !busy;
}

function syncName(){
  const inp = document.getElementById("acName");
  if (!inp) return;
  if (!nameTouched) inp.value = madeName();
  paintTaken();
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
  editId = a.id || null;
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
    +   picks("acName", unlisted().slice(0, 6).map(r => r.name), a.name)
    +   '<p class="ac-warn" id="acTaken" hidden></p></div>'
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
  paintTaken();
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

/* Скільки угод цього рахунку вже в журналі. Разом із балансом з кабінету
   це і є позначка «звідси рахуємо далі»: угоди після неї додаються до
   вписаного балансу, попередні вважаються врахованими в самій цифрі.
   Рахуємо за тією назвою, яку рахунок носить зараз, а не за новою: угоди
   перейменуються слідом, але зараз вони лежать під старою. */
function tradesNow(id, name){
  const was = (ACCS || []).find(a => a.id === id);
  return tradesOf({name: (was && was.name) || name}).length;
}

async function save(id){
  const d = D();
  const err = document.getElementById("acErr");
  const acc = {
    id: id || null, name: val("acName"), firm: val("acFirm"), kind: segVal("acKind"),
    currency: val("acCur") || "USD", start_balance: num("acStart"),
    current_balance: num("acNow"), balance_n: tradesNow(id || null, val("acName")),
    target_pct: num("acTarget"), dd_total_pct: num("acDdTotal"), dd_daily_pct: num("acDdDaily"),
    opened_at: val("acOpened"), status: segVal("acStatus"),
    closed_at: val("acClosed"), reason: val("acReason"), note: val("acNote"),
  };
  if (!acc.name){ show(err, d.errName); return; }
  let saved = null;
  try{
    saved = (await api("POST", "/api/accounts", {account: acc})).account;
  }catch(e){
    /* 409 — таку назву вже носить інший рахунок. Помилка не про мережу,
       і людині треба сказати саме це. */
    show(err, /409/.test(String((e && e.message) || "")) ? d.errTaken : d.errSave);
    return;
  }
  /* Назва рахунку — підказка у формі угоди. Знімаємо з неї приховування,
     якщо рахунок із таким іменем колись прибирали: інакше заведений
     наново рахунок мовчки не показувався б у ряду підказок. */
  if (window.Prefs && saved && saved.name) Prefs.add("account", saved.name);
  closeModal();
  ACCS = undefined;
  await load();
}

async function drop(id){
  const d = D();
  /* Угоди лишаються з тією ж назвою, і картка з такою назвою, заведена
     пізніше, підбере їх знову. Це навмисно, але сказати про це треба до
     видалення, а не після: число тут — вся різниця між «прибрав опис» і
     «здається, загубив історію». */
  const a = (ACCS || []).find(x => x.id === id);
  const n = a ? tradesOf(a).length : 0;
  const ask = n ? d.delAskN.replace("%n", n) : d.delAsk;
  if (!await Ask.yes(ask, {ok: d.delYes, cancel: d.cancel, danger: true})) return;
  try{ await api("POST", "/api/accounts/drop", {id: id}); }catch(e){ return; }
  /* Угоди лишились, і разом з ними лишилась би назва в підказках форми:
     історія підставляє її знову, а колись вписане «своє значення» взагалі
     живе в налаштуваннях окремо. Прибрали картку — прибираємо й підказку.
     Це те саме приховування, що й кошик на самій кнопці, тож людина може
     повернути її звідти. */
  if (window.Prefs && a && a.name) Prefs.hide("account", a.name);
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

/* Список рахунків потрібен не лише цьому розділу: форма угоди підказує
   ним поле «рахунок». Без цього щойно заведений рахунок доводилось
   вписувати в угоду руками — і саме там народжувалась друга назва того
   самого рахунку, після якої картка лишалась без угод.

   Помилку тут ковтаємо мовчки й ACCS не чіпаємо: це не запит розділу, а
   попереднє читання про запас. Якщо не доїхало — розділ прочитає сам. */
async function preload(){
  if (ACCS !== undefined) return;
  try{
    const got = (await api("GET", "/api/accounts")).accounts || [];
    if (ACCS === undefined) ACCS = got;
  }catch(e){}
}

/* Рахунки, які людина вже вписувала в угоди, але картки не завела.
   Потрібні одному місцю — підказкам під полем «Назва» у формі рахунку:
   там людина саме заводить картку, і збігтись із написанням в угодах їй
   важливо, бо звʼязок іде по імені. Окремим рядом унизу розділу вони
   стояли й раніше, але повну назву рахунку в угоді пишуть рідко, і ряд
   майже завжди висів там дарма. */
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
  /* Складати гроші можна лише в межах однієї валюти: перерахунку курсів у
     журналі немає, і вигадувати його тут не будемо. Тому рахуємо кожну
     валюту окремо й показуємо їх поруч — раніше на двох валютах не
     показувалось узагалі нічого, без жодного пояснення. */
  const sums = new Map();
  let mute = 0;
  for (const a of live){
    const bal = stat(a).balance;
    if (bal == null){ mute++; continue; }
    const cur = a.currency || "USD";
    sums.set(cur, (sums.get(cur) || 0) + bal);
  }
  const parts = [...sums.entries()].sort((x, y) => y[1] - x[1])
    .map(e => money(e[1], e[0]));
  return '<div class="ac-total"><span>' + esc(d.liveN.replace("%n", live.length)) + "</span>"
    + (parts.length ? "<b>" + esc(parts.join(" · ")) + "</b>" : "")
    /* Рахунки без стартового балансу в суму не входять — інакше вона
       вдавала б, що знає більше, ніж знає. */
    + (mute ? '<i class="ac-muted">' + esc(d.noBal.replace("%n", mute)) + "</i>" : "")
    + "</div>";
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
      + "</div></div></div>";
  }
  return '<div class="acw">' + head
    + '<div class="ac-grid">' + ACCS.map(card).join("") + "</div></div>";
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
      if (p.dataset.target === "acName"){ nameTouched = true; paintTaken(); }
      else syncName();
    }
    return;
  }

  if (S.view !== "accounts") return;
  const add = e.target.closest("#acAdd, #acAdd2");
  if (add){ __acc.add(); return; }
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
  if (id === "acName"){ nameTouched = !!e.target.value.trim(); paintTaken(); }
  else if (id === "acFirm" || id === "acStart") syncName();
});

/* Гачок для перевірок: збірку назви інакше не викликати ззовні. */
window.__accTest = {sync: syncName, made: madeName, firms: openFirms, status: paintStatus,
  stat: stat, total: total, free: freeName, norm: normName, spark: spark,
  accs(list){ ACCS = list; }};

window.__acc = {
  add(){
    if (window.Guest && Guest.block(D().title)) return;
    openForm(blank());
  },
  edit(id){
    const a = (ACCS || []).find(x => x.id === id);
    if (a) openForm(Object.assign({}, a));
  },
  why(id){ openId = openId === id ? null : id; render(); },
  /* Підпис вкладки для шапки «Огляду»: словник розділу лежить у цьому
     файлі, тож app.js питає його звідси. */
  navLabel(){ return D().navTitle; },
  /* Назви рахунків для підказок у формі угоди. Живі — першими: на
     закритому челенджі нових угод уже не буде. */
  names(){
    return (ACCS || []).slice()
      .sort((a, b) => (b.status === "active") - (a.status === "active"))
      .map(a => normName(a.name)).filter(Boolean);
  },
  preload: preload,
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
  delAskN: "Прибрати картку рахунку? Угод із цією назвою в журналі — %n, вони лишаться.",
  delYes: "Прибрати",
  liveN: "живих рахунків: %n",
  since: "з", fromStart: "старт", noStart: "Стартовий баланс не заданий — гроші рахувати нема з чого.",
  setStart: "задати",
  toTarget: "До цілі", ddTotal: "Просадка від старту", ddDaily: "Найгірший день",
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
  balAt: "з кабінету на %s, далі за угодами",
  beforeOpen: "Угод раніше за дату відкриття — %n. У рахунок вони не пішли.",
  noBal: "%n без балансу",
  willRename: "Така назва вже є. Збережемо як «%s».",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "перевищив денний ліміт",
  phNote: "що завгодно про цей рахунок",
  emptyLead: "Тут будуть твої рахунки: свій депозит і все, що взяв у проп-фірм.",
  emptyHint: "Заведи рахунок — і журнал перестане рахувати самими відсотками: покаже баланс у грошах, скільки лишилось до цілі й скільки до ліміту просадки.",
  errName: "Без назви рахунок не знайде своїх угод.", errTaken: "Рахунок з такою назвою вже є.",
  errSave: "Не вдалось зберегти. Спробуй ще раз.",
},
ru: {
  title: "Мои счета", navTitle: "Счета", navTip: "Свой депозит и счета проп-фирм: баланс, цель, лимиты",
  loading: "Минутку…", add: "Новый счёт", close: "Закрыть", cancel: "Отмена",
  save: "Сохранить", edit: "Править", del: "Удалить",
  delAsk: "Убрать карточку счёта? Сделки останутся в журнале.",
  delAskN: "Убрать карточку счёта? Сделок с этим названием в журнале — %n, они останутся.",
  delYes: "Убрать",
  liveN: "живых счетов: %n",
  since: "с", fromStart: "старт", noStart: "Стартовый баланс не задан — деньги считать не из чего.",
  setStart: "задать",
  toTarget: "До цели", ddTotal: "Просадка от старта", ddDaily: "Худший день",
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
  balAt: "из кабинета на %s, дальше по сделкам",
  beforeOpen: "Сделок раньше даты открытия — %n. В счёт они не пошли.",
  noBal: "%n без баланса",
  willRename: "Такое название уже есть. Сохраним как «%s».",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "превысил дневной лимит",
  phNote: "что угодно про этот счёт",
  emptyLead: "Здесь будут твои счета: свой депозит и всё, что взял у проп-фирм.",
  emptyHint: "Заведи счёт — и журнал перестанет считать одними процентами: покажет баланс в деньгах, сколько осталось до цели и сколько до лимита просадки.",
  errName: "Без названия счёт не найдёт своих сделок.", errTaken: "Счёт с таким названием уже есть.",
  errSave: "Не удалось сохранить. Попробуй ещё раз.",
},
en: {
  title: "My accounts", navTitle: "Accounts", navTip: "Your own deposit and prop firm accounts: balance, target, limits",
  loading: "One moment…", add: "New account", close: "Close", cancel: "Cancel",
  save: "Save", edit: "Edit", del: "Delete",
  delAsk: "Remove this account card? The trades stay in the journal.",
  delAskN: "Remove this account card? %n trades carry this name and will stay in the journal.",
  delYes: "Remove",
  liveN: "live accounts: %n",
  since: "since", fromStart: "start", noStart: "No starting balance yet — nothing to count money from.",
  setStart: "set it",
  toTarget: "To target", ddTotal: "Drawdown from start", ddDaily: "Worst day",
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
  balAt: "from the dashboard on %s, journal trades after that",
  beforeOpen: "Trades before the opening date: %n. They are not counted here.",
  noBal: "%n with no balance",
  willRename: "That name is taken. We will save it as “%s”.",
  phName: "FTMO 100k", phFirm: "FTMO", phReason: "went past the daily limit",
  phNote: "anything about this account",
  emptyLead: "Your accounts live here: your own deposit and everything you took from prop firms.",
  emptyHint: "Add an account and the journal stops counting in percent alone: it shows the balance in money, how far the target is and how much drawdown is left.",
  errName: "Without a name the account cannot find its trades.", errTaken: "An account with this name already exists.",
  errSave: "Could not save. Please try again.",
},
};


})();
