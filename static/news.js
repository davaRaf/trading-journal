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
  }catch(err){
    warning = T.nwFetchError + err.message;
    events = [];
  }
  if (S.view === "news") render();
}

/* ---- обробники живуть тут, а не в розмітці ---- */
window.__news = {
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
    return '<div class="nw-ev '+e._i+(e._d < now ? " past" : "")+'">'
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

VIEWS.news = vNews;      /* VIEWS оголошено в app.js, ключ можна додати ззовні */

})();
