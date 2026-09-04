/* ============================================================
   Розділ «Новини» — економічний календар на тиждень.

   Живе окремим файлом і сам додає себе в VIEWS, щоб не заважати
   правкам в app.js. Дані бере з /api/calendar: у мережу ходить
   сервер, бо фід блокує за частими запитами.
   ============================================================ */
(function(){

const IMPACT = {High:"h", Medium:"m", Low:"l", Holiday:"l"};
function NAME(){ return {h:T.nwImpactHigh, m:T.nwImpactMed, l:T.nwImpactLow}; }

let events = null;       // null — ще не завантажено
let warning = null;

/* Фільтри переживають перезавантаження: між розділами вони й так жили в
   пам'яті, а от після F5 скидались — і людина щоразу заново тикала свій
   день і «червоні». Тримаємо їх у localStorage, як режим журналу й тему. */
const FKEY = "tj_news_filters";
function readFilters(){
  try{
    const v = JSON.parse(localStorage.getItem(FKEY) || "{}");
    return (v && typeof v === "object") ? v : {};
  }catch(e){ return {}; }
}
function pick(v){ return typeof v === "string" && v ? v : "all"; }

const saved = readFilters();
let day = pick(saved.day);        // "all" — увесь тиждень
let impact = pick(saved.impact);
let cur = pick(saved.cur);

function keep(){
  try{ localStorage.setItem(FKEY, JSON.stringify({day, impact, cur})); }catch(e){}
}

const dkey = d => d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0")
                + "-" + String(d.getDate()).padStart(2,"0");

async function load(){
  try{
    const res = await fetch("/api/calendar");
    if(!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    warning = data.warning || null;
    events = (data.events || [])
      .map(e => ({...e, _d: new Date(e.date), _i: IMPACT[e.impact] || "l"}))
      .filter(e => !isNaN(e._d))
      .sort((a,b) => a._d - b._d);
    events.forEach((e, i) => { e._id = i; });   /* номер для відкриття картки */
  }catch(err){
    warning = T.nwFetchError + err.message;
    events = [];
  }
  if (S.view === "news") render();
}

/* ---- обробники живуть тут, а не в розмітці ---- */
window.__news = {
  open(id){ openEvent(id); },
  day(v){ day = v; keep(); render(); },
  imp(v){ impact = v; keep(); render(); },
  cur(v){ cur = v; keep(); render(); },
};

function vNews(){
  if (events === null){
    load();
    return '<div class="nw-empty">'+T.nwLoading+'</div>';
  }
  if (!events.length){
    return '<div class="nw-empty">'+T.nwNoEvents+'<br>'
         + (warning ? esc(warning) : T.nwRetryHint) + '</div>';
  }

  const days = [...new Set(events.map(e => dkey(e._d)))].sort();
  const today = dkey(new Date());
  if (day !== "all" && !days.includes(day)){
    day = days.includes(today) ? today : "all";
    keep();
  }

  const inScope = day === "all" ? events : events.filter(e => dkey(e._d) === day);
  const cnt = i => inScope.filter(e => e._i === i).length;

  let h = "";

  if (warning)
    h += '<div class="nw-warn"><b>'+T.nwAttention+'</b> ' + esc(warning) + '</div>';

  /* ---- дні тижня ---- */
  h += '<div class="nw-days">'
     + '<button class="nw-week' + (day==="all" ? " on" : "") + '" onclick="__news.day(\'all\')">'
     + '<span class="wd">'+T.nwWeekAll1+'</span><span class="dt">'+T.nwWeekAll2+'</span></button>';
  for (const d of days){
    const dd = new Date(d + "T00:00");
    const of = events.filter(e => dkey(e._d) === d);
    const dots = ["h","m"].filter(i => of.some(e => e._i === i))
                  .map(i => '<i class="'+i+'"></i>').join("")
                  || (of.length ? '<i class="l"></i>' : "");
    h += '<button class="nw-day' + (d===day?" on":"") + (d===today?" today":"") + '"'
       + ' onclick="__news.day(\''+d+'\')">'
       + '<span class="wd">'+T.wdSun[dd.getDay()]+'</span>'
       + '<span class="dt">'+dd.getDate()+'</span>'
       + '<span class="dots">'+dots+'</span></button>';
  }
  h += '</div>';

  /* ---- фільтри сегментами ---- */
  h += '<div class="nw-filters"><div class="nw-grp"><span class="lab">'+T.nwImportance+'</span>'
     + chip("all", T.nwAll, inScope.length, impact, "imp", "all")
     + ["h","m","l"].map(i => chip(i, NAME()[i], cnt(i), impact, "imp", i)).join("")
     + '</div>';

  const curs = [...new Set(events.map(e => e.country))].filter(c => c && c !== "All").sort();
  /* валюти на новому тижні можуть бути інші: інакше список мовчки порожній */
  if (cur !== "all" && !curs.includes(cur)){ cur = "all"; keep(); }
  h += '<div class="nw-grp"><span class="lab">'+T.nwCurrency+'</span>'
     + chip("all", T.nwAll, inScope.length, cur, "cur", "all")
     + curs.map(c => chip(c, c, inScope.filter(e => e.country===c).length, cur, "cur", c)).join("")
     + '</div></div>';

  /* ---- список ---- */
  const items = inScope.filter(e => (impact==="all" || e._i===impact)
                                 && (cur==="all"    || e.country===cur));
  h += '<div class="nw-list">' + rows(items) + '</div>';
  return h;
}

function chip(id, label, n, active, kind, val){
  const dot = (kind==="imp" && id!=="all") ? '<i class="'+id+'"></i>' : "";
  return '<button class="nw-chip'+(active===val?" on":"")+(n?"":" off")+'"'
       + ' onclick="__news.'+kind+'(\''+val+'\')">'
       + dot + label + '<span class="n">'+n+'</span></button>';
}

function rows(items){
  if (!items.length) return '<div class="nw-empty">'+T.nwNoFiltered+'</div>';
  const now = new Date();
  const next = items.find(e => e._d > now);

  const one = e => {
    const t = String(e._d.getHours()).padStart(2,"0") + ":"
            + String(e._d.getMinutes()).padStart(2,"0");
    return '<div class="nw-ev '+e._i+(e._d < now ? " past" : "")+'"'
      + ' role="button" tabindex="0" onclick="__news.open('+e._id+')"'
      + ' onkeydown="if(event.key===&quot;Enter&quot;||event.key===&quot; &quot;)'
      + '{event.preventDefault();__news.open('+e._id+')}">'
      + '<div class="tm">'+t+'</div>'
      + '<div class="cur">'+esc(e.country||"—")+'</div>'
      + '<div class="ttl">'+esc(e.title)
        + '<small>'+(e.impact==="Holiday" ? T.nwHoliday : NAME()[e._i].toLowerCase())+'</small></div>'
      + '<div class="num">'
        + (e===next ? '<div class="badge">'+T.nwSoon+'</div>' : "")
        + '<div><span>'+T.nwForecast+'</span>'+(esc(e.forecast)||"—")+'</div>'
        + '<div><span>'+T.nwPrevious+'</span>'+(esc(e.previous)||"—")+'</div>'
      + '</div></div>';
  };

  if (day !== "all") return items.map(one).join("");

  /* Увесь тиждень: заголовок перед кожним днем, інакше півтори сотні
     рядків поспіль читаються як каша. */
  let out = "", last = null;
  for (const e of items){
    const k = dkey(e._d);
    if (k !== last){
      last = k;
      out += '<div class="nw-dayhead"><b>' + T.wdSun[e._d.getDay()] + ", "
           + e._d.getDate() + " " + T.monthsGen[e._d.getMonth()] + '</b>'
           + '<span>' + items.filter(x => dkey(x._d)===k).length + '</span>'
           + '<div class="rule"></div></div>';
    }
    out += one(e);
  }
  return out;
}

/* ---------- картка події: подробиці й попередні результати ----------

   Список показує тільки прогноз і попереднє значення — більше в рядок
   не вміщається. Клік по картці відкриває вікно, де видно, коли подія
   виходить у твоєму часі, скільки лишилось, і як цей показник виходив
   раніше: прогноз проти результату.

   Історію тримає сервер (calendar_feed.event_history): фід віддає лише
   поточний тиждень, тому архів накопичується сам, тиждень за тижнем. */

const histCache = {};          /* щоб не питати сервер двічі за одне й те саме */

function num(v){
  /* «205K», «-1.2%», «1,234» → число. Не вийшло — NaN, і різницю не пишемо. */
  const s = String(v == null ? "" : v).replace(/\s|,/g, "");
  const m = s.match(/^(-?\d+(?:\.\d+)?)([KMBTkmbt]?)%?$/);
  if (!m) return NaN;
  const mul = {k:1e3, m:1e6, b:1e9, t:1e12}[m[2].toLowerCase()] || 1;
  return parseFloat(m[1]) * mul;
}

function leftText(d){
  const ms = d - new Date();
  if (ms <= 0) return "";
  const min = Math.round(ms / 60000);
  if (min < 60) return T.nwLeftIn + " " + min + " " + T.nwMin;
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 24) return T.nwLeftIn + " " + h + " " + T.nwHour + (m ? " " + m + " " + T.nwMin : "");
  return T.nwLeftIn + " " + Math.round(h / 24) + " " + T.nwDay;
}

function when(d){
  return T.wdSun[d.getDay()] + ", " + d.getDate() + " " + T.monthsGen[d.getMonth()]
       + " · " + String(d.getHours()).padStart(2,"0") + ":"
       + String(d.getMinutes()).padStart(2,"0");
}

/* Одиниці, в яких записане число: «205K» → множник 1000 і хвостик «K»,
   «0.3%» → хвостик «%». Різницю показуємо в них же, інакше замість
   «+2K» вийшло б «+2000», а замість «-0.5%» — «-0.5». */
function unit(v){
  const m = String(v == null ? "" : v).trim()
              .match(/^-?\d+(?:\.\d+)?([KMBT])?(%)?$/i);
  if (!m) return {mul: 1, tail: ""};
  const s = (m[1] || "").toUpperCase();
  return {mul: {K:1e3, M:1e6, B:1e9, T:1e12}[s] || 1, tail: s + (m[2] || "")};
}

function numsRow(e){
  const f = num(e.forecast), p = num(e.previous);
  let diff = "";
  if (!isNaN(f) && !isNaN(p)){
    const u = unit(e.forecast);
    const d = Math.round((f - p) / u.mul * 100) / 100;
    const cls = d > 0 ? "up" : (d < 0 ? "down" : "");
    diff = '<div><span>'+T.nwDiff+'</span><b class="'+cls+'">'
         + (d > 0 ? "+" : "") + d + u.tail + '</b></div>';
  }
  return '<div class="nv-nums">'
    + '<div><span>'+T.nwForecast+'</span><b>'+(esc(e.forecast) || "—")+'</b></div>'
    + '<div><span>'+T.nwPrevious+'</span><b>'+(esc(e.previous) || "—")+'</b></div>'
    + diff + '</div>';
}

function histTable(rows){
  if (!rows.length) return '<div class="nv-none">'+T.nwHistEmpty+'</div>';
  const cell = r => {
    const d = new Date(r.date);
    const f = num(r.forecast), a = num(r.actual);
    let cls = "";
    if (!isNaN(f) && !isNaN(a)) cls = a > f ? "up" : (a < f ? "down" : "");
    const day = isNaN(d) ? esc(r.date.slice(0,10))
      : String(d.getDate()).padStart(2,"0") + "." + String(d.getMonth()+1).padStart(2,"0");
    const per = r.period ? '<i>'+esc(r.period)+'</i>' : "";
    return '<tr><td class="dt">'+day+per+'</td>'
      + '<td>'+(esc(r.forecast) || "—")+'</td>'
      + '<td class="fact '+cls+'">'+(esc(r.actual) || "—")+'</td></tr>';
  };
  return '<table class="nv-tab"><thead><tr>'
    + '<th>'+T.nwHistDate+'</th><th>'+T.nwForecast+'</th><th>'+T.nwHistFact+'</th>'
    + '</tr></thead><tbody>' + rows.map(cell).join("") + '</tbody></table>';
}

/* Звідки взялись числа. Свій архів тонкий — фід віддає лише поточний
   тиждень; глибшу історію бере чужий календар, і про це чесно сказано. */
function note(hist, src){
  if (hist === null) return "";
  if (src === "tv" && hist.length) return T.nwHistSrc;
  return T.nwHistNote;
}

/* Один рядок статистики під таблицею: як часто цей показник виходив вище
   прогнозу. Саме заради такого й дивляться минулі виходи — щоб бачити, у
   який бік показник зазвичай хибить. */
function tally(rows){
  let up = 0, n = 0;
  for (const r of rows){
    const f = num(r.forecast), a = num(r.actual);
    if (isNaN(f) || isNaN(a)) continue;
    n++;
    if (a > f) up++;
  }
  if (n < 4) return "";
  return '<p class="nv-tally">' + T.nwAbove.replace("{n}", up).replace("{all}", n) + '</p>';
}

function detail(e, hist, src){
  const d = e._d, left = leftText(d);
  const imp = e.impact === "Holiday" ? T.nwHoliday : NAME()[e._i];
  return '<div class="m-body nv">'
    + '<div class="nv-top">'
      + '<span class="nv-cur">'+esc(e.country || "—")+'</span>'
      + '<span class="nv-imp '+e._i+'"><i></i>'+esc(imp)+'</span>'
      + '<span class="nv-when">'+when(d)+'</span>'
      + (left ? '<span class="nv-left">'+left+'</span>'
              : '<span class="nv-left off">'+T.nwPassed+'</span>')
    + '</div>'
    + numsRow(e)
    + '<h3 class="nv-h">'+T.nwHistory+'</h3>'
    + (hist === null ? '<div class="nv-none">'+T.nwLoading+'</div>' : histTable(hist))
    + (hist && hist.length ? tally(hist) : "")
    + '<p class="nv-note">'+note(hist, src)+'</p>'
    + '</div>';
}

function frame(e, hist, src){
  return '<div class="m-head"><h2>'+esc(e.title)+'</h2>'
    + '<button class="x" onclick="closeModal()" aria-label="'+esc(T.mrClose)+'">×</button></div>'
    + detail(e, hist, src)
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">'+esc(T.mrClose)+'</button></div>';
}

async function openEvent(id){
  const e = events && events[id];
  if (!e) return;
  const key = (e.country || "") + "|" + e.title;
  const had = histCache[key];
  openModal(frame(e, had ? had.rows : null, had && had.src));
  if (had) return;
  let rows = [], src = "";
  try{
    const res = await fetch("/api/calendar/event?country=" + encodeURIComponent(e.country || "")
                          + "&title=" + encodeURIComponent(e.title || ""));
    if (res.ok){
      const got = await res.json();
      rows = got.history || [];
      src = got.source || "";
    }
  }catch(err){ rows = []; }
  histCache[key] = {rows: rows, src: src};
  /* вікно могли вже закрити або відкрити інше — тоді нічого не чіпаємо */
  const box = document.getElementById("modalBox");
  const head = box && box.querySelector(".m-head h2");
  if (head && head.textContent === e.title) box.innerHTML = frame(e, rows, src);
}

VIEWS.news = vNews;      /* VIEWS оголошено в app.js, ключ можна додати ззовні */

})();
