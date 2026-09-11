/* ============================================================
   Розділ «Новини» — економічний календар тижня.

   Зібраний таблицею, як у Forex Factory: дата злиплена на весь день,
   час пишеться один раз на групу, факт стоїть поруч із прогнозом і
   попереднім. Так зроблено навмисно — люди приходять сюди з Forex
   Factory, і що менше їм доводиться перевчатись, то краще. Звідти ж
   і фільтр: одна кнопка, а в ній три групи галочок — важливість,
   тип події, валюти.

   Живе окремим файлом і сам додає себе в VIEWS, щоб не заважати
   правкам в app.js. Дані бере з /api/calendar: у мережу ходить
   сервер, бо фід блокує за частими запитами.
   ============================================================ */
(function(){

/* Банківський вихідний — не «жовта» новина: цифр у ньому немає, зате
   є те, чого в жодній новині немає — біржа не працює. Тому в нього
   свій, сірий рівень і своя галочка у фільтрі. */
const IMPACT = {High:"h", Medium:"m", Low:"l", Holiday:"x"};
const LEVELS = ["h","m","l","x"];
function NAME(){ return {h:T.nwImpactHigh, m:T.nwImpactMed, l:T.nwImpactLow,
                         x:T.nwImpactHoliday}; }
function ONE(){ return {h:T.nwOneHigh, m:T.nwOneMed, l:T.nwOneLow, x:T.nwOneHol}; }

/* ---------- тип події ----------

   Фід типу не віддає — тільки назву. Але саме за типом люди й
   відсіюють: «покажи інфляцію й центробанки, решта не цікавить».
   Тому тип вгадуємо за словами назви, і порядок перевірок тут має
   значення: «ECB President Lagarde Speaks» — це виступ, а не рішення
   по ставці, тому виступи стоять першими. */
const TYPES = ["growth","infl","jobs","cb","bonds","house","consum","biz","talk","misc"];
function TNAME(){
  return {growth:T.nwTypeGrowth, infl:T.nwTypeInfl, jobs:T.nwTypeJobs, cb:T.nwTypeCb,
          bonds:T.nwTypeBonds, house:T.nwTypeHouse, consum:T.nwTypeConsum,
          biz:T.nwTypeBiz, talk:T.nwTypeTalk, misc:T.nwTypeMisc};
}
const RULES = [
  ["talk",   /speaks|speech|testif|press conference|remarks|hearing/],
  /* «rate» саме по собі сюди не годиться: «Unemployment Rate» — це ринок
     праці, а не ставка. Тому ловимо ставку тільки повним словосполученням. */
  ["cb",     /interest rate|policy rate|cash rate|bank rate|refinancing rate|rate decision|rate statement|fomc|monetary policy|minutes|beige book|central bank|\bboe\b|\bboj\b|\bsnb\b|\brba\b|\brbnz\b|\becb\b|\bfed\b|money stock|money supply|bank lending|reserves|balance sheet|asset purchase/],
  ["bonds",  /bond|auction|yield|gilt|\bbtp\b|\bjgb\b/],
  ["house",  /hous|home |mortgage|building permit|building approvals|construction|\bhpi\b/],
  ["infl",   /cpi|ppi|inflation|price index|prices|deflator/],
  ["jobs",   /employ|unemploy|payroll|jobless|claims|labor|labour|job |earnings|wage/],
  ["consum", /consumer confidence|consumer sentiment|consumer climate|\buom\b|consumer credit|retail sales monitor|spending/],
  ["biz",    /pmi|zew|ifo|business|tankan|sentix|empire state|philly fed|richmond|sentiment|confidence|watchers/],
  ["growth", /gdp|production|retail sales|trade balance|current account|economic|output|orders|sales|inventories|leading indicator|index of services|shipments|machine/],
];
/* Значок важливості малюємо саме SVG, а не трьома <b> у флексі: у журналі
   повно своїх коротких класів і правил для вкладених тегів, і лесенка з
   <b> у панелі фільтра вишиковувалась не так, як у таблиці. У SVG висоти
   стовпчиків задані координатами й перебити їх стилями ззовні нічим. */
function sig(lv, label){
  const head = '<svg class="nw-sig ' + lv + '" width="14" height="13" viewBox="0 0 14 13"'
    + (label ? ' role="img" aria-label="' + esc(label) + '"' : ' aria-hidden="true"') + '>';
  if (lv === "x")
    return head + '<circle cx="7" cy="8" r="4.2" fill="none" stroke-width="1.5"/></svg>';
  return head
    + '<rect class="a" x="0"  y="8" width="3" height="5"  rx="1"/>'
    + '<rect class="b" x="5"  y="4" width="3" height="9"  rx="1"/>'
    + '<rect class="c" x="10" y="0" width="3" height="13" rx="1"/></svg>';
}

function kindOf(e){
  if ((e.impact || "") === "Holiday") return "misc";
  const t = String(e.title || "").toLowerCase();
  for (const [k, re] of RULES) if (re.test(t)) return k;
  return "misc";
}

let events = null;       // null — ще не завантажено
let warning = null;

/* Фільтр переживає перезавантаження: після F5 він скидався, і людина
   щоразу заново знімала галочки. Тримаємо його в localStorage, як
   режим журналу й тему.

   А от день — ні. Розділ відкривають, щоб подивитись, що сьогодні, і
   позавчорашній день у ньому просто спантеличує. Тому щоразу, як
   заходиш у «Новини», показуємо поточний день; вибраний вручну живе,
   доки з розділу не вийдеш. */
const FKEY = "tj_news_filters";
function readFilters(){
  try{
    const v = JSON.parse(localStorage.getItem(FKEY) || "{}");
    return (v && typeof v === "object") ? v : {};
  }catch(e){ return {}; }
}

const saved = readFilters();
/* Набір із збереженого: порожній або зіпсований — беремо всі. */
function pickSet(v, all){
  const ok = Array.isArray(v) ? v.filter(x => all.includes(x)) : [];
  return new Set(ok.length ? ok : all);
}
let imp = pickSet(saved.imp, LEVELS);
let types = pickSet(saved.types, TYPES);
/* Валюти — окремий випадок: їх список залежить від тижня, тому «усі»
   зберігаємо як null, а не як перелік. Інакше нова валюта наступного
   тижня мовчки виявилась би вимкненою. */
let curs = Array.isArray(saved.curs) && saved.curs.length ? new Set(saved.curs) : null;

let view = "day";                 // «day» або «week»
let day = "";                     // виставимо на поточний, коли знатимемо дні
let stick = false;                // людина сама вибрала день
let q = "";                       // пошук по назві; живе, доки розділ відкритий
let open = null;                  // розкрита подія
let draft = null;                 // тимчасовий стан відкритої панелі фільтра
let growing = false;              // шторку розкриваємо анімацією лише раз, на відкритті

/* Перехід між розділами йде через hash — на ньому й скидаємо вибір дня:
   наступного разу «Новини» знову відкриються на сьогоднішньому. */
addEventListener("hashchange", () => {
  stick = false; q = ""; open = null; view = "day"; draft = null;
});

function keep(){
  try{
    localStorage.setItem(FKEY, JSON.stringify({
      imp:[...imp], types:[...types], curs: curs ? [...curs] : null}));
  }catch(e){}
}

const dkey = d => d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0")
                + "-" + String(d.getDate()).padStart(2,"0");
const hhmm = d => String(d.getHours()).padStart(2,"0") + ":"
                + String(d.getMinutes()).padStart(2,"0");

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
    events.forEach((e, i) => { e._id = i; e._k = dkey(e._d); e._t = kindOf(e); });
  }catch(err){
    warning = T.nwFetchError + err.message;
    events = [];
  }
  if (S.view === "news") render();
}

/* ---- обробники живуть тут, а не в розмітці ---- */
window.__news = {
  open(id){ toggle(id); },
  view(v){ view = v; open = null; stick = true; draft = null; render(); },
  shift(n){ step(n); },
  /* перемальовуємо лише тіло таблиці — інакше поле втрачає фокус на кожній літері */
  q(v){ q = v; open = null; redraw(); },
  filter(){ draft ? closeFilter() : openFilter(); },
  chk(kind, val, on){ flip(kind, val, on); },
  pick(kind, on){ pickAll(kind, on); },
  apply(){ applyFilter(); },
  cancel(){ closeFilter(); },
  reset(){ imp = new Set(LEVELS); types = new Set(TYPES); curs = null;
           draft = null; open = null; keep(); render(); },
};

function days(){ return [...new Set(events.map(e => e._k))].sort(); }

function step(n){
  const list = days();
  const i = list.indexOf(day);
  view = "day"; stick = true; draft = null;
  day = list[Math.min(list.length - 1, Math.max(0, (i < 0 ? 0 : i) + n))];
  open = null;
  render();
}

function moneys(){
  return [...new Set(events.map(e => e.country))].filter(c => c && c !== "All").sort();
}
function curOn(c){ return !curs || curs.has(c); }
/* Чи звужений фільтр хоч десь: від цього залежить підсвітка кнопки. */
function narrowed(){
  return imp.size < LEVELS.length || types.size < TYPES.length
      || (curs && moneys().some(c => !curs.has(c)));
}

function scope(){ return view === "week" ? events : events.filter(e => e._k === day); }
function items(){
  const needle = q.trim().toLowerCase();
  return scope().filter(e => imp.has(e._i) && types.has(e._t) && curOn(e.country)
                          && (!needle || String(e.title||"").toLowerCase().includes(needle)));
}

/* Пояс, у якому людина дивиться календар: усі часи тут місцеві, і про це
   краще сказати прямо — інакше «15:30» у двох країнах читається по-різному. */
function zone(){
  const off = -new Date().getTimezoneOffset() / 60;
  const sign = off < 0 ? "−" : "+";
  const h = Math.floor(Math.abs(off)), m = Math.round((Math.abs(off) - h) * 60);
  return "UTC" + sign + h + (m ? ":" + String(m).padStart(2,"0") : "");
}

function vNews(){
  if (events === null){
    load();
    return '<div class="nw-empty">'+T.nwLoading+'</div>';
  }
  if (!events.length){
    return '<div class="nw-empty">'+T.nwNoEvents+'<br>'
         + (warning ? esc(warning) : T.nwRetryHint) + '</div>';
  }

  const list = days();
  const today = dkey(new Date());
  if (!stick || !list.includes(day)){
    /* На вихідних сьогоднішнього дня у стрічці немає — тоді показуємо
       найближчий, що попереду, а не весь тиждень одразу. */
    day = list.includes(today) ? today : (list.find(d => d > today) || list[0]);
  }

  let h = "";
  if (warning)
    h += '<div class="nw-warn"><b>'+T.nwAttention+'</b> ' + esc(warning) + '</div>';

  h += bar(list, today) + next() + table();
  return h;
}

/* ---------- панель: стрілки днів, день/тиждень, фільтр, пошук ---------- */
function bar(list, today){
  const i = list.indexOf(day);
  let label, sub;
  if (view === "week"){
    const a = new Date(list[0] + "T00:00"), b = new Date(list[list.length-1] + "T00:00");
    sub = T.nwViewWeek.toLowerCase();
    label = a.getDate() + " – " + b.getDate() + " " + T.monthsGen[b.getMonth()];
  } else {
    const d = new Date(day + "T00:00");
    sub = day === today ? T.nwToday : T.wdSun[d.getDay()];
    label = d.getDate() + " " + T.monthsGen[d.getMonth()];
  }
  return '<div class="nw-bar">'
    + '<div class="nw-nav">'
      + '<button class="nw-ico" onclick="__news.shift(-1)" aria-label="'+esc(T.nwPrevDay)+'"'
        + (i <= 0 && view === "day" ? " disabled" : "") + '>'
        + '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
        + '<path d="M14.5 5.5 8 12l6.5 6.5" stroke="currentColor" stroke-width="1.9"'
        + ' stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
      + '<div class="nw-when"><span>'+esc(sub)+'</span>'+esc(label)+'</div>'
      + '<button class="nw-ico" onclick="__news.shift(1)" aria-label="'+esc(T.nwNextDay)+'"'
        + (i >= list.length - 1 && view === "day" ? " disabled" : "") + '>'
        + '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
        + '<path d="M9.5 5.5 16 12l-6.5 6.5" stroke="currentColor" stroke-width="1.9"'
        + ' stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
    + '</div>'
    + '<div class="nw-seg" role="group" aria-label="'+esc(T.nwImportance)+'">'
      + '<button onclick="__news.view(\'day\')" aria-pressed="'+(view==="day")+'">'
        + esc(T.nwViewDay)+'</button>'
      + '<button onclick="__news.view(\'week\')" aria-pressed="'+(view==="week")+'">'
        + esc(T.nwViewWeek)+'</button>'
    + '</div>'
    + '<span class="nw-sp"></span>'
    + '<span class="nw-tz">'+zone()+'</span>'
    + '<label class="nw-search">'
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
      + '<circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8"/>'
      + '<path d="M20 20l-3.5-3.5" stroke="currentColor" stroke-width="1.8"'
      + ' stroke-linecap="round"/></svg>'
      + '<input type="search" value="'+esc(q)+'" placeholder="'+esc(T.nwSearchPh)+'"'
      + ' autocomplete="off" oninput="__news.q(this.value)"></label>'
    + '<div class="nw-fwrap">'
      + '<button class="nw-fbtn'+(narrowed() ? " on" : "")+'" onclick="__news.filter()"'
        + ' aria-expanded="false" id="nwFbtn">'
        + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
        + '<path d="M3 5.5h18M6.5 12h11M10 18.5h4" stroke="currentColor" stroke-width="1.9"'
        + ' stroke-linecap="round"/></svg>' + esc(T.nwFilter)
        + (narrowed() ? '<i class="dot"></i>' : "") + '</button>'
      + '<div id="nwFbox"></div>'
    + '</div>'
    + '</div>';
}

/* ---------- панель фільтра ----------

   Три групи галочок, як у Forex Factory: важливість, тип події, валюти.
   Зміни живуть у чернетці й лягають у фільтр лише по «Застосувати» —
   інакше кожна знята галочка перемальовувала б таблицю, а людина за раз
   знімає їх п'ять. */

function openFilter(){
  draft = {imp:new Set(imp), types:new Set(types),
           curs:new Set(curs ? [...curs] : moneys())};
  paint();
  document.addEventListener("keydown", onEsc);
  setTimeout(() => document.addEventListener("pointerdown", onOutside), 0);
  const box = document.getElementById("nwFbox");
  const first = box && box.querySelector("input");
  if (first) first.focus();
}

function closeFilter(){
  draft = null;
  paint();
  document.removeEventListener("keydown", onEsc);
  document.removeEventListener("pointerdown", onOutside);
  const btn = document.getElementById("nwFbtn");
  if (btn) btn.focus();
}

function onEsc(ev){ if (ev.key === "Escape") closeFilter(); }
function onOutside(ev){
  const wrap = document.querySelector(".nw-fwrap");
  if (wrap && !wrap.contains(ev.target)) closeFilter();
}

function flip(kind, val, on){
  if (!draft) return;
  if (on) draft[kind].add(val); else draft[kind].delete(val);
}

function pickAll(kind, on){
  if (!draft) return;
  const all = kind === "imp" ? LEVELS : kind === "types" ? TYPES : moneys();
  draft[kind] = new Set(on ? all : []);
  paint();
}

function applyFilter(){
  if (!draft) return;
  /* Порожня група — це порожня сторінка й ніякої користі: вважаємо,
     що людина хотіла «усі», і мовчки повертаємо всі галочки. */
  imp = draft.imp.size ? new Set(draft.imp) : new Set(LEVELS);
  types = draft.types.size ? new Set(draft.types) : new Set(TYPES);
  const all = moneys();
  const got = [...draft.curs].filter(c => all.includes(c));
  curs = (!got.length || got.length === all.length) ? null : new Set(got);
  draft = null;
  open = null;
  keep();
  document.removeEventListener("keydown", onEsc);
  document.removeEventListener("pointerdown", onOutside);
  render();
}

function paint(){
  const box = document.getElementById("nwFbox");
  const btn = document.getElementById("nwFbtn");
  if (!box) return;
  box.innerHTML = draft ? panel() : "";
  if (btn) btn.setAttribute("aria-expanded", String(!!draft));
}

function group(kind, lab, rows){
  return '<div class="grp"><p class="h">'+esc(lab)
    + ' <button class="lnk" onclick="__news.pick(\''+kind+'\',true)">'+esc(T.nwPickAll)+'</button>'
    + '<span class="sep">·</span>'
    + '<button class="lnk" onclick="__news.pick(\''+kind+'\',false)">'+esc(T.nwPickNone)+'</button>'
    + '</p>' + rows + '</div>';
}

function check(kind, val, label, extra){
  const id = "nwf-" + kind + "-" + val;
  return '<label class="chk" for="'+id+'"><input type="checkbox" id="'+id+'"'
    + (draft[kind].has(val) ? " checked" : "")
    + ' onchange="__news.chk(\''+kind+'\',\''+val+'\',this.checked)">'
    + (extra || "") + '<span>'+esc(label)+'</span></label>';
}

function panel(){
  const imps = LEVELS.map(lv => check("imp", lv, ONE()[lv], sig(lv))).join("");
  const tps = TYPES.map(k => check("types", k, TNAME()[k])).join("");
  const cur = moneys().map(c => check("curs", c, c)).join("");
  return '<div class="nw-panel" role="dialog" aria-label="'+esc(T.nwFilter)+'">'
    + '<div class="cols">'
      + '<div class="left">'
        + group("imp", T.nwImportance, '<div class="rows imps">'+imps+'</div>')
        + group("types", T.nwTypes, '<div class="rows two">'+tps+'</div>')
      + '</div>'
      + group("curs", T.nwCurrency, '<div class="rows">'+cur+'</div>')
    + '</div>'
    + '<div class="foot">'
      + '<button class="lnk warn" onclick="__news.reset()">'+esc(T.nwReset)+'</button>'
      + '<span class="nw-sp"></span>'
      + '<button class="nw-btn" onclick="__news.cancel()">'+esc(T.nwCancel)+'</button>'
      + '<button class="nw-btn nw-apply" onclick="__news.apply()">'+esc(T.nwApply)+'</button>'
    + '</div></div>';
}

/* ---------- смужка «далі»: найближча подія з числами ---------- */
function next(){
  const now = new Date();
  const e = events.find(x => x._d > now && x._i !== "x");
  if (!e) return "";
  const min = Math.round((e._d - now) / 60000);
  const left = min < 60 ? min + " " + T.nwMin
             : Math.floor(min/60) + " " + T.nwHour
               + (min % 60 ? " " + (min % 60) + " " + T.nwMin : "");
  return '<div class="nw-next"><span class="tag">'+T.nwNext+'</span>'
    + '<b>'+esc(e.title)+'</b>'
    + '<span class="tm">'+esc(e.country)+' · '+hhmm(e._d)+'</span>'
    + '<span class="nw-sp"></span>'
    + '<span class="tm">'+T.nwLeftIn+' '+left+'</span></div>';
}

/* ---------- таблиця ---------- */
function table(){
  return '<div class="nw-tablewrap m-swap"><table class="nw-tab">'
    + '<thead><tr>'
      + '<th>'+T.nwColDate+'</th><th>'+T.nwColTime+'</th><th>'+T.nwCurrency+'</th>'
      + '<th class="c">'+T.nwColImp+'</th><th>'+T.nwColEvent+'</th>'
      + '<th class="r">'+T.nwColFact+'</th><th class="r">'+T.nwForecast+'</th>'
      + '<th class="r">'+T.nwPrevious+'</th><th class="c">'+T.nwColHist+'</th>'
    + '</tr></thead><tbody>' + body() + '</tbody></table></div>';
}

function redraw(){
  const b = document.querySelector(".nw-tab tbody");
  if (!b) return;
  b.innerHTML = body();
  /* Далі таблицю перемальовує ще й історія, коли приїде з сервера. Якби
     прапорець жив довше, шторка програвалась би вдруге і блимала. */
  growing = false;
}

function body(){
  const list = items();
  if (!list.length)
    return '<tr><td colspan="9"><div class="nw-empty">'+T.nwNoFiltered+'</div></td></tr>';

  const now = new Date(), today = dkey(now);
  const byDay = {};
  for (const e of list) (byDay[e._k] = byDay[e._k] || []).push(e);

  let h = "", lineDone = false;
  for (const k of Object.keys(byDay).sort()){
    const rows = byDay[k];
    const needLine = !lineDone && k === today && rows.some(e => e._d > now);
    /* висота лівої клітинки дня: рядки, плюс розкрита подія, плюс смуга «зараз» */
    const span = rows.length + (rows.some(e => e._id === open) ? 1 : 0) + (needLine ? 1 : 0);
    let first = true, lastTime = null;
    for (const e of rows){
      if (!lineDone && k === today && e._d > now){
        lineDone = true;
        h += '<tr class="nw-line">' + (first ? dateCell(k, span, today) : "")
           + '<td colspan="8"><div class="ln"><span>'+T.nwNow+' '+hhmm(now)
           + '</span><i></i></div></td></tr>';
        first = false;
        lastTime = null;
      }
      h += row(e, first ? dateCell(k, span, today) : "", lastTime, now);
      lastTime = hhmm(e._d);
      first = false;
      if (e._id === open) h += detail(e);
    }
  }
  return h;
}

function dateCell(k, span, today){
  const d = new Date(k + "T00:00");
  /* Місяць тут короткий: «11 вересня» у колонці 96px ламалось на два
     рядки, і підпис знизу з'їжджав. Порядок як у Forex Factory —
     день тижня згори, дата під ним. */
  return '<td class="dt'+(k === today ? " now" : "")+'" rowspan="'+span+'">'
    + '<span class="wd">'+T.wdSun[d.getDay()]+'</span>'
    + '<b>'+d.getDate()+' '+T.monShort[d.getMonth()]+'</b>'
    + (k === today ? '<span class="tag">'+T.nwToday+'</span>' : "") + '</td>';
}

function row(e, dcell, lastTime, now){
  const t = hhmm(e._d), same = t === lastTime;
  const fc = factCls(e);
  const cls = ["nw-ev", e._i === "h" ? "hi" : "", e._d <= now ? "past" : "",
               e._id === open ? "on" : ""].filter(Boolean).join(" ");
  return '<tr class="'+cls+'" tabindex="0" role="button" aria-expanded="'+(e._id === open)+'"'
    + ' onclick="__news.open('+e._id+')"'
    + ' onkeydown="if(event.key===&quot;Enter&quot;||event.key===&quot; &quot;)'
    + '{event.preventDefault();__news.open('+e._id+')}">'
    + dcell
    + '<td class="tm">'+(same ? '<span class="rep">'+t+'</span>' : t)+'</td>'
    + '<td class="cur"><i>'+esc(e.country || "—")+'</i></td>'
    + '<td class="imp">' + sig(e._i, T.nwColImp + ": " + ONE()[e._i]) + '</td>'
    + '<td class="nm"><div class="ttl"><span class="t">'+esc(e.title)+'</span>'
      + (e._i === "x" ? '<span class="nw-pill">'+T.nwHoliday+'</span>' : "")+'</div></td>'
    + '<td class="num fact '+fc+'" data-l="'+esc(T.nwColFact)+'">'
      + (e.actual ? (fc ? '<span class="ar">'+(fc === "up" ? "▲" : "▼")+'</span>' : "")
                  + esc(e.actual) : "—") + '</td>'
    + '<td class="num" data-l="'+esc(T.nwForecast)+'">'+(esc(e.forecast) || "—")+'</td>'
    + '<td class="num" data-l="'+esc(T.nwPrevious)+'">'+(esc(e.previous) || "—")+'</td>'
    + '<td class="gr">'+(isNaN(num(e.forecast)) && isNaN(num(e.previous)) ? "" : chartIcon())
    + '</td></tr>';
}

function chartIcon(){
  return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    + '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2" stroke="currentColor" stroke-width="1.8"'
    + ' stroke-linecap="round"/></svg>';
}

/* ---------- числа ---------- */

function num(v){
  /* «205K», «-1.2%», «1,234» → число. Не вийшло — NaN, і різницю не пишемо. */
  const s = String(v == null ? "" : v).replace(/\s|,/g, "");
  const m = s.match(/^(-?\d+(?:\.\d+)?)([KMBTkmbt]?)%?$/);
  if (!m) return NaN;
  const mul = {k:1e3, m:1e6, b:1e9, t:1e12}[m[2].toLowerCase()] || 1;
  return parseFloat(m[1]) * mul;
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

/* Колір факту — це напрям відхилення від прогнозу, і тільки він. Чи це
   добре, календар не знає: зростання безробіття теж «вище прогнозу». */
function factCls(e){
  const a = num(e.actual), f = num(e.forecast);
  if (isNaN(a) || isNaN(f) || a === f) return "";
  return a > f ? "up" : "down";
}

/* ---------- розкрита подія ----------

   Рядок показує чотири числа — більше в нього не влізе. Клік розкриває
   під ним смугу, де видно відхилення від прогнозу, час виходу в твоєму
   поясі й те, як цей показник виходив раніше: прогноз проти результату.

   Історію тримає сервер (/api/calendar/event): фід віддає лише поточний
   тиждень, глибше бере календар TradingView. */

const histCache = {};          /* щоб не питати сервер двічі за одне й те саме */

function calm(){
  try{ return matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch(err){ return false; }
}

function toggle(id){
  /* Закриття: спершу даємо шторці згорнутись і лише потім прибираємо
     рядок із таблиці. Інакше подробиці зникали ривком. */
  if (open === id){
    const box = document.querySelector(".nw-det .slide");
    if (box && !calm()){
      box.classList.add("shut");
      setTimeout(() => { open = null; redraw(); }, 280);
      return;
    }
    open = null;
    redraw();
    return;
  }
  open = id;
  growing = !calm();
  redraw();
  const back = document.querySelector('.nw-ev[aria-expanded="true"]');
  if (back) back.focus();
  const e = events[id];
  const key = (e.country || "") + "|" + e.title;
  if (histCache[key]) return;
  fetchHist(e, key);
}

async function fetchHist(e, key){
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
  histCache[key] = {rows, src};
  /* поки ходили по історію, могли закрити рядок або відкрити інший */
  if (open === e._id && S.view === "news") redraw();
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
       + ", " + hhmm(d);
}

function detail(e){
  const key = (e.country || "") + "|" + e.title;
  const had = histCache[key];
  const a = num(e.actual), f = num(e.forecast), u = unit(e.forecast || e.previous);
  let diff = '<div><span>'+T.nwDeviation+'</span><b>—</b></div>';
  if (!isNaN(a) && !isNaN(f)){
    const d = Math.round((a - f) / u.mul * 100) / 100;
    diff = '<div><span>'+T.nwDeviation+'</span><b class="'+(d > 0 ? "up" : d < 0 ? "down" : "")
         + '">' + (d > 0 ? "+" : "") + d + u.tail + '</b></div>';
  }
  const left = leftText(e._d);
  return '<tr class="nw-det"><td colspan="8">'
    + '<div class="slide'+(growing ? " grow" : "")+'"><div class="clip"><div class="in">'
    + '<div class="nums">'
      + '<div class="r3">'
        + '<div><span>'+T.nwColFact+'</span><b class="'+factCls(e)+'">'
          + (esc(e.actual) || "—")+'</b></div>'
        + '<div><span>'+T.nwForecast+'</span><b>'+(esc(e.forecast) || "—")+'</b></div>'
        + '<div><span>'+T.nwPrevious+'</span><b>'+(esc(e.previous) || "—")+'</b></div>'
      + '</div>'
      + '<div class="r2">' + diff
        + '<div><span>'+T.nwTypes+'</span><b class="sm">'+TNAME()[e._t]+'</b></div></div>'
      + '<p class="meta"><em>'+esc(e.country || "—")+' · '+when(e._d)+'.</em> '
        + (left ? left : T.nwPassed) + '.</p>'
    + '</div>'
    + '<div class="hist"><p class="h">'+T.nwPrevOut+'</p>'
      + (had ? histTable(had.rows) : '<div class="nv-none">'+T.nwLoading+'</div>')
    + '</div></div></div></div></td></tr>';
}

function histTable(rows){
  if (!rows.length) return '<div class="nv-none">'+T.nwHistEmpty+'</div>';
  const cell = r => {
    const d = new Date(r.date);
    const f = num(r.forecast), a = num(r.actual);
    let cls = "";
    if (!isNaN(f) && !isNaN(a)) cls = a > f ? "up" : (a < f ? "down" : "");
    const dt = isNaN(d) ? esc(String(r.date).slice(0,10))
      : String(d.getDate()).padStart(2,"0") + "." + String(d.getMonth()+1).padStart(2,"0");
    const per = r.period ? '<i>'+esc(r.period)+'</i>' : "";
    return '<tr><td class="d">'+dt+per+'</td>'
      + '<td>'+(esc(r.forecast) || "—")+'</td>'
      + '<td class="fact '+cls+'">'+(esc(r.actual) || "—")+'</td></tr>';
  };
  return '<table class="nw-htab"><thead><tr>'
    + '<th>'+T.nwHistDate+'</th><th>'+T.nwForecast+'</th><th>'+T.nwHistFact+'</th>'
    + '</tr></thead><tbody>' + rows.map(cell).join("") + '</tbody></table>'
    + tally(rows);
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
  return '<p class="tally">' + T.nwAbove.replace("{n}", up).replace("{all}", n) + '</p>';
}

VIEWS.news = vNews;      /* VIEWS оголошено в app.js, ключ можна додати ззовні */

})();
