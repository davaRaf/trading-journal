/* ============================================================
   Поділитися посиланням.

   Надсилаємо на сервер уже пораховані цифри — не самі угоди.
   За посиланням не можна витягнути журнал: там лише знімок.
   Живе окремим файлом, щоб не заважати правкам в app.js.
   (share.js поруч — це інше: картинка для каналу.)
   ============================================================ */
(function(){

function TTL(){ return [
  { id:"1h",      name:T.slTtl1h },
  { id:"24h",     name:T.slTtl24h },
  { id:"7d",      name:T.slTtl7d },
  { id:"30d",     name:T.slTtl30d },
  { id:"forever", name:T.slTtlForever },
]; }

let lastTtl = "7d";
try{ lastTtl = localStorage.getItem("share_ttl") || "7d"; }catch(e){}

/* ---------- що саме показуємо ---------- */

function statsOf(list){
  const st = calc(list);
  return [
    { k:T.kCount,         v:String(st.n) },
    { k:T.slWinRate,     v:fmtPct(st.wr) },
    { k:T.slTotal,     v:fmtR(st.net), cls: st.net>0 ? "pos" : st.net<0 ? "neg" : "" },
    /* у calc() поле зветься avgRR — через st.rr тут завжди був прочерк */
    { k:T.kAvgRR,  v: st.avgRR==null ? "—" : String(r1(st.avgRR)) },
    { k:T.kResSplit, v: st.wins+" / "+st.losses+" / "+st.be },
    { k:T.kBeSplit,    v: st.beM+" / "+st.beP },
  ];
}

/* Угода цілком — щоб той, кому дали посилання, міг її розгорнути:
   як заходив, що записав, і самі скріни. Без цього зі знімка дня видно
   лише «US100 · TP», а найцікавіше лишається вдома. */
function tradeDetail(t){
  const info = [
    [T.fSession, t.session], [T.fPosition, t.position], [T.fBias, t.bias],
    [T.fmEntryTypeLabel, dirType(t)], [T.flModel, t.entry_model], [T.fSetup, t.setup],
    [T.fRisk, t.risk == null ? "" : t.risk + "%"], ["RR", t.rr == null ? "" : String(t.rr)],
    [T.fEmotion, t.emotion],
  ].filter(([, v]) => v).map(([k, v]) => ({k: k, v: String(v)}));

  const texts = [[T.slEntryBlock, t.entry_details], [T.tiNotes, t.notes],
                 [T.tiMistakes, t.mistakes]]
    .filter(([, v]) => (v || "").trim())
    .map(([k, v]) => ({k: k, v: v.trim()}));

  return {
    id: t.id,
    time: (t.date || "").slice(11, 16),
    pair: t.pair || "",
    result: resLabel(t.result),
    cls: t.result === "Win" ? "pos" : t.result === "Loss" ? "neg" : "be",
    net: netR(t),
    info: info,
    texts: texts,
    shots: (t.screenshots || []).filter(s => s.file)
      .map(s => ({tf: s.tf || "", file: s.file})),
  };
}

/* розріз: що дало найбільше і найменше */
function sliceBlock(title, list, key){
  const g = groupBy(list, t => fieldVal(t, key) || "—");
  const items = Object.keys(g)
    .map(name => ({ name, value: calc(g[name]).net, n: g[name].length }))
    .filter(x => x.n >= 2)
    .sort((a,b) => b.value - a.value)
    .slice(0, 6)
    .map(x => ({ name: x.name + "  ·  " + x.n, value: x.value }));
  return items.length ? { title, items } : null;
}

function daySnapshot(dk){
  const list = sortAsc(S.all.filter(t => dayKey(t) === dk));
  const d = new Date(dk + "T00:00");
  return {
    kind: T.slKindDay,
    title: d.getDate() + " " + T.monthsGen[d.getMonth()] + " " + d.getFullYear(),
    total: calc(list).net,
    kpis: statsOf(list),
    trades: list.map(tradeDetail),
    blocks: [
      sliceBlock(T.railSessions, list, "session"),
    ].filter(Boolean),
  };
}

function weekSnapshot(anchor){
  // тиждень рахуємо від понеділка, як у календарі
  const d = new Date(anchor + "T00:00");
  const shift = (d.getDay() + 6) % 7;
  const mon = new Date(d); mon.setDate(d.getDate() - shift);
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
  const k = x => x.getFullYear() + "-" + String(x.getMonth()+1).padStart(2,"0")
              + "-" + String(x.getDate()).padStart(2,"0");
  const from = k(mon), to = k(sun);
  const list = S.all.filter(t => { const dk = dayKey(t); return dk >= from && dk <= to; });
  const days = groupBy(list, dayKey);
  const byDay = Object.keys(days).sort().map(dd => {
    const dt = new Date(dd + "T00:00");
    return { name: T.wdSun[dt.getDay()] + ", " + dt.getDate() + " " + T.monthsGen[dt.getMonth()],
             value: calc(days[dd]).net };
  });
  return {
    kind: T.slKindWeek,
    title: mon.getDate() + " " + T.monthsGen[mon.getMonth()] + " — "
         + sun.getDate() + " " + T.monthsGen[sun.getMonth()],
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      byDay.length ? { title:T.slByDays, items: byDay } : null,
      sliceBlock(T.railSetups, list, "setup"),
      sliceBlock(T.railInstruments, list, "pair"),
    ].filter(Boolean),
  };
}

function monthSnapshot(mk){
  const list = S.all.filter(t => monKey(t) === mk);
  const [y, m] = mk.split("-");
  const days = groupBy(list, dayKey);
  const byDay = Object.keys(days).sort()
    .map(d => ({ name: d.slice(8) + "." + d.slice(5,7), value: calc(days[d]).net }));
  return {
    kind: T.slKindMonth,
    title: T.months[+m - 1] + " " + y,
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      sliceBlock(T.railSetups, list, "setup"),
      sliceBlock(T.railInstruments, list, "pair"),
      sliceBlock(T.railSessions, list, "session"),
      byDay.length ? { title:T.slByDays, items: byDay } : null,
    ].filter(Boolean),
  };
}

function yearSnapshot(y){
  const list = S.all.filter(t => (t.date||"").slice(0,4) === String(y));
  const months = groupBy(list, monKey);
  const byMonth = Object.keys(months).sort()
    .map(mk => ({ name: T.months[+mk.slice(5,7) - 1], value: calc(months[mk]).net }));
  return {
    kind: T.slKindYear,
    title: String(y),
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      byMonth.length ? { title:T.slByMonths, items: byMonth } : null,
      sliceBlock(T.railSetups, list, "setup"),
      sliceBlock(T.railInstruments, list, "pair"),
    ].filter(Boolean),
  };
}

function tradeSnapshot(id){
  const t = S.all.find(x => x.id === id);
  if (!t) return null;
  const net = netR(t);
  return {
    kind: T.slKindTrade,
    title: t.pair + " · " + resLabel(t.result),
    total: net,
    kpis: [
      { k:T.fResult, v:resLabel(t.result) },
      { k:T.slTotal,  v:fmtR(net), cls: net>0 ? "pos" : net<0 ? "neg" : "" },
      { k:"RR",        v: t.rr==null ? "—" : String(t.rr) },
      { k:T.fRisk,     v: t.risk==null ? "—" : t.risk + "%" },
    ],
    /* та сама розгортка, що й у знімку дня: скріни та все, що записано */
    trades: [tradeDetail(t)],
    blocks: [],
  };
}

/* ---------- вікно ---------- */

function open(kind, arg){
  const data = kind === "trade" ? tradeSnapshot(arg)
             : kind === "day"   ? daySnapshot(arg)
             : kind === "week"  ? weekSnapshot(arg)
             : kind === "month" ? monthSnapshot(arg)
             :                    yearSnapshot(arg);
  if (!data) return;

  openModal(
    '<div class="m-head"><b>' + T.slShareTitle + '</b><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + T.mrClose + '</button></div>'
    + '<div class="m-body sh-body">'
    + '<p class="sh-note">' + T.slNote
    + (kind === "trade" || kind === "day" ? " " + T.slNoteImg : "") + '</p>'
    + '<div class="sh-what"><b>' + esc(data.title) + '</b><span>' + esc(data.kind) + '</span></div>'
    + '<div class="sh-lab">' + T.slDurationLabel + '</div>'
    + '<div class="sh-ttl">' + TTL().map(t =>
        '<button class="sh-chip' + (t.id===lastTtl ? " on" : "") + '" data-t="' + t.id + '">'
        + t.name + '</button>').join("") + '</div>'
    + '<div class="sh-out" id="shOut" hidden></div>'
    + '</div>'
    + '<div class="m-foot"><button class="btn primary" id="shGo">' + T.slCreateBtn + '</button>'
    + (kind === "trade" || kind === "day"
        ? '<button class="btn" id="shImg">' + T.slImgBtn + '</button>' : "")
    + '<span class="sp"></span></div>'
  );

  const img = document.getElementById("shImg");
  if (img) img.onclick = () => __tradeImg.open(kind, arg);

  document.querySelectorAll(".sh-chip").forEach(b => b.onclick = () => {
    lastTtl = b.dataset.t;
    try{ localStorage.setItem("share_ttl", lastTtl); }catch(e){}
    document.querySelectorAll(".sh-chip").forEach(x => x.classList.toggle("on", x === b));
  });

  document.getElementById("shGo").onclick = async function(){
    this.disabled = true; this.textContent = T.slCreating;
    try{
      const res = await fetch("/api/share", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ data, ttl: lastTtl })
      });
      if(!res.ok) throw new Error("HTTP " + res.status);
      const r = await res.json();
      const url = location.origin + r.url;
      const out = document.getElementById("shOut");
      out.hidden = false;
      out.innerHTML = '<input class="sh-url" id="shUrl" readonly value="' + esc(url) + '">'
        + '<button class="btn" id="shCopy">' + T.slCopyBtn + '</button>'
        + '<a class="btn" href="' + esc(r.url) + '" target="_blank" rel="noopener">' + T.slOpenBtn + '</a>';
      document.getElementById("shUrl").select();
      document.getElementById("shCopy").onclick = async () => {
        try{ await navigator.clipboard.writeText(url); }
        catch(e){ document.getElementById("shUrl").select(); document.execCommand("copy"); }
        document.getElementById("shCopy").textContent = T.slCopiedCheck;
      };
      this.textContent = T.slDoneBtn;
    }catch(err){
      this.disabled = false; this.textContent = T.slCreateBtn;
      alert(T.slCreateError + err.message);
    }
  };
}

/* ---------- кнопки в інтерфейсі ---------- */
/* Ставимо їх після кожної перемальовки, щоб не чіпати render() в app.js. */

function icon(){
  return '<svg width="13" height="13" viewBox="0 0 24 24" fill="none">'
    + '<path d="M12 3v12M8 7l4-4 4 4" stroke="currentColor" stroke-width="1.8"'
    + ' stroke-linecap="round" stroke-linejoin="round"/>'
    + '<path d="M5 14v4a2 2 0 002 2h10a2 2 0 002-2v-4" stroke="currentColor"'
    + ' stroke-width="1.8" stroke-linecap="round"/></svg>';
}

function mkBtn(label, kind, arg, extra){
  const b = document.createElement("button");
  b.className = "btn sh-btn" + (extra ? " " + extra : "");
  b.type = "button";
  b.innerHTML = icon() + " " + label;
  b.onclick = e => { e.stopPropagation(); open(kind, arg); };
  return b;
}

/* поточний день і місяць беремо зі стану застосунку */
function curDay(){
  return S.selDay || (S.all.length ? dayKey(S.all[S.all.length-1]) : null);
}
function curMonth(){
  return S.jMonth || (S.all.length ? monKey(S.all[S.all.length-1]) : null);
}

/* Порожній період відправляти нема сенсу — кнопку тоді просто не показуємо. */
function weekRange(anchor){
  const d = new Date(anchor + "T00:00");
  const mon = new Date(d); mon.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
  const k = x => x.getFullYear() + "-" + String(x.getMonth()+1).padStart(2,"0")
              + "-" + String(x.getDate()).padStart(2,"0");
  return [k(mon), k(sun)];
}
function hasDay(dk){   return !!dk && S.all.some(t => dayKey(t) === dk); }
function hasWeek(dk){
  if (!dk) return false;
  const [from, to] = weekRange(dk);
  return S.all.some(t => { const k = dayKey(t); return k >= from && k <= to; });
}
function hasMonth(mk){ return !!mk && S.all.some(t => monKey(t) === mk); }
function hasYear(y){   return !!y  && S.all.some(t => monKey(t).slice(0,4) === y); }

/* ---- смуга кнопок над розділом ---- */
function mountBar(){
  const root = document.getElementById("main");
  if (!root || root.querySelector(".sh-bar")) return;
  if (S.view !== "dashboard" && S.view !== "journal") return;

  const d = curDay(), mk = curMonth();
  const year = mk ? mk.slice(0,4) : String(new Date().getFullYear());

  const btns = [];
  if (hasDay(d))     btns.push(mkBtn(T.slDay,    "day",   d));
  if (hasWeek(d))    btns.push(mkBtn(T.slWeek, "week",  d));
  if (hasMonth(mk))  btns.push(mkBtn(T.ovPeriodMonth,  "month", mk));
  if (hasYear(year)) btns.push(mkBtn(T.ovPeriodYear,     "year",  year));
  if (!btns.length) return;

  const bar = document.createElement("div");
  bar.className = "sh-bar";
  bar.innerHTML = '<span class="sh-cap">' + T.slShareCap + '</span>';
  btns.forEach(b => bar.appendChild(b));

  /* у журналі кнопки живуть у шапці розділу — поруч із «Картинка для каналу»,
     бо це та сама дія: віддати місяць чи рік назовні */
  const tools = root.querySelector(".jhead .tools");
  if (tools){
    bar.classList.add("sh-inline");
    tools.insertBefore(bar, tools.firstChild);
    return;
  }

  /* на огляді — праворуч, одразу за перемикачем періоду: місяць і рік
     віддаються назовні тим самим рухом, яким їх обирають */
  const ohead = root.querySelector(".ovw .ohead");
  if (ohead){
    bar.classList.add("sh-inline");
    ohead.appendChild(bar);
    return;
  }

  const h = root.querySelector(".page > h1, .page .phead, .page > .head");
  (h ? h.parentNode : root).insertBefore(bar, h ? h.nextSibling : root.firstChild);
}

/* ---- кнопка в панелі дня ---- */
function mountDayPanel(){
  const panel = document.querySelector(".daypanel");
  if (!panel || panel.querySelector(".sh-day")) return;
  const d = curDay();
  if (!hasDay(d)) return;
  const b = mkBtn(T.slShareDay, "day", d, "sh-day");
  const add = panel.querySelector(".addday");
  add ? panel.insertBefore(b, add) : panel.appendChild(b);
}

/* ---- кнопка біля угоди ----
   Угоду видно у двох місцях: карткою в бічній панелі й розгорнутим рядком
   у списку журналу. Кнопка потрібна в обох — інакше людина шукає її там,
   де відкрила угоду, і не знаходить. Ставимо поруч із «Видалити»: у ній
   лежить id угоди, більше його взяти нізвідки. */
function mountTradeCard(){
  document.querySelectorAll(".m-foot, .dact").forEach(foot => {
    if (foot.querySelector(".sh-trade")) return;
    const del = foot.querySelector(".danger[onclick*='delTrade']");
    if (!del) return;
    const m = del.getAttribute("onclick").match(/delTrade\('([^']+)'\)/);
    if (!m) return;
    const b = mkBtn(T.slShareTrade, "trade", m[1], "sh-trade");
    foot.insertBefore(b, del);
  });
}

function mount(){ mountBar(); mountDayPanel(); mountTradeCard(); }

window.Share = { open, mount };

/* Ловимо перемальовки.
   Розділ живе в #main — за ним стежить спостерігач.
   Картка угоди виїжджає панеллю, яку ui.js переиспользує: тіло сторінки
   при цьому не змінюється, тому спостерігач її не бачить. Тому чіпляємось
   прямо до відкриття панелі. */
/* Синхронно, без setTimeout: інакше сторінка встигає перемалюватися без
   смуги кнопок і зразу з нею — і на кожному кліку по календарю все стрибає. */
function schedule(){ mount(); }
const main = document.getElementById("main");
if (main) new MutationObserver(schedule).observe(main, { childList:true });

["Sheet", "Panel", "Drawer"].forEach(name => {
  const api = window[name];
  if (!api || typeof api.open !== "function" || api.__shareHooked) return;
  const orig = api.open;
  api.open = function(){ const r = orig.apply(this, arguments); schedule(); return r; };
  api.__shareHooked = true;
});

mount();

})();
