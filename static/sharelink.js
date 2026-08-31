/* ============================================================
   Поділитися посиланням.

   Надсилаємо на сервер уже пораховані цифри — не самі угоди.
   За посиланням не можна витягнути журнал: там лише знімок.
   Живе окремим файлом, щоб не заважати правкам в app.js.
   (share.js поруч — це інше: картинка для каналу.)
   ============================================================ */
(function(){

const TTL = [
  { id:"1h",      name:"1 година" },
  { id:"24h",     name:"24 години" },
  { id:"7d",      name:"7 днів" },
  { id:"30d",     name:"30 днів" },
  { id:"forever", name:"без обмеження" },
];
const MONTHS_G = ["січня","лютого","березня","квітня","травня","червня",
                  "липня","серпня","вересня","жовтня","листопада","грудня"];
const WD_UA = ["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];

let lastTtl = "7d";
try{ lastTtl = localStorage.getItem("share_ttl") || "7d"; }catch(e){}

/* ---------- що саме показуємо ---------- */

function statsOf(list){
  const st = calc(list);
  return [
    { k:"Угод",         v:String(st.n) },
    { k:"Win rate",     v:fmtPct(st.wr) },
    { k:"Підсумок",     v:fmtR(st.net), cls: st.net>0 ? "pos" : st.net<0 ? "neg" : "" },
    { k:"Середній RR",  v: st.rr==null ? "—" : String(r1(st.rr)) },
    { k:"TP / SL / BE", v: st.wins+" / "+st.losses+" / "+st.be },
    { k:"BE− / BE+",    v: st.beM+" / "+st.beP },
  ];
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
    kind: "день",
    title: d.getDate() + " " + MONTHS_G[d.getMonth()] + " " + d.getFullYear(),
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      list.length ? { title:"Угоди", items: list.map(t => ({
        name: (t.date||"").slice(11,16) + "  ·  " + (t.pair||"") + "  ·  " + resLabel(t.result),
        value: netR(t),
      })) } : null,
      sliceBlock("Сесії", list, "session"),
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
    return { name: WD_UA[dt.getDay()] + ", " + dt.getDate() + " " + MONTHS_G[dt.getMonth()],
             value: calc(days[dd]).net };
  });
  return {
    kind: "тиждень",
    title: mon.getDate() + " " + MONTHS_G[mon.getMonth()] + " — "
         + sun.getDate() + " " + MONTHS_G[sun.getMonth()],
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      byDay.length ? { title:"По днях", items: byDay } : null,
      sliceBlock("Сетапи", list, "setup"),
      sliceBlock("Інструменти", list, "pair"),
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
    kind: "місяць",
    title: MONTHS[+m - 1] + " " + y,
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      sliceBlock("Сетапи", list, "setup"),
      sliceBlock("Інструменти", list, "pair"),
      sliceBlock("Сесії", list, "session"),
      byDay.length ? { title:"По днях", items: byDay } : null,
    ].filter(Boolean),
  };
}

function yearSnapshot(y){
  const list = S.all.filter(t => (t.date||"").slice(0,4) === String(y));
  const months = groupBy(list, monKey);
  const byMonth = Object.keys(months).sort()
    .map(mk => ({ name: MONTHS[+mk.slice(5,7) - 1], value: calc(months[mk]).net }));
  return {
    kind: "рік",
    title: String(y),
    total: calc(list).net,
    kpis: statsOf(list),
    blocks: [
      byMonth.length ? { title:"По місяцях", items: byMonth } : null,
      sliceBlock("Сетапи", list, "setup"),
      sliceBlock("Інструменти", list, "pair"),
    ].filter(Boolean),
  };
}

function tradeSnapshot(id){
  const t = S.all.find(x => x.id === id);
  if (!t) return null;
  const net = netR(t);
  const info = [
    ["Інструмент", t.pair], ["Дата", (t.date||"").replace("T", " ")],
    ["Напрямок", t.position], ["Біас", t.bias],
    ["Тип входу", dirType(t)], ["Модель", t.entry_model],
    ["Сетап", t.setup],
    ["Ризик", t.risk==null ? "" : t.risk + "%"],
    ["RR", t.rr==null ? "" : String(t.rr)],
  ].filter(([, v]) => v).map(([name, text]) => ({ name, text }));

  return {
    kind: "угода",
    title: t.pair + " · " + resLabel(t.result),
    total: net,
    kpis: [
      { k:"Результат", v:resLabel(t.result) },
      { k:"Підсумок",  v:fmtR(net), cls: net>0 ? "pos" : net<0 ? "neg" : "" },
      { k:"RR",        v: t.rr==null ? "—" : String(t.rr) },
      { k:"Ризик",     v: t.risk==null ? "—" : t.risk + "%" },
    ],
    blocks: [
      { title:"Деталі", items: info },
      (t.entry_details||"").trim()
        ? { title:"Вхід", items:[{ name:t.entry_details, text:"" }] } : null,
    ].filter(Boolean),
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
    '<div class="m-head"><b>Поділитися</b><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">Закрити</button></div>'
    + '<div class="m-body sh-body">'
    + '<p class="sh-note">Надсилаються лише пораховані цифри — самі угоди й скриншоти '
    + 'за посиланням недоступні.</p>'
    + '<div class="sh-what"><b>' + esc(data.title) + '</b><span>' + esc(data.kind) + '</span></div>'
    + '<div class="sh-lab">Скільки посилання діє</div>'
    + '<div class="sh-ttl">' + TTL.map(t =>
        '<button class="sh-chip' + (t.id===lastTtl ? " on" : "") + '" data-t="' + t.id + '">'
        + t.name + '</button>').join("") + '</div>'
    + '<div class="sh-out" id="shOut" hidden></div>'
    + '</div>'
    + '<div class="m-foot"><button class="btn go" id="shGo">Створити посилання</button>'
    + '<span class="sp"></span></div>'
  );

  document.querySelectorAll(".sh-chip").forEach(b => b.onclick = () => {
    lastTtl = b.dataset.t;
    try{ localStorage.setItem("share_ttl", lastTtl); }catch(e){}
    document.querySelectorAll(".sh-chip").forEach(x => x.classList.toggle("on", x === b));
  });

  document.getElementById("shGo").onclick = async function(){
    this.disabled = true; this.textContent = "Створюю…";
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
        + '<button class="btn" id="shCopy">Копіювати</button>'
        + '<a class="btn" href="' + esc(r.url) + '" target="_blank" rel="noopener">Відкрити</a>';
      document.getElementById("shUrl").select();
      document.getElementById("shCopy").onclick = async () => {
        try{ await navigator.clipboard.writeText(url); }
        catch(e){ document.getElementById("shUrl").select(); document.execCommand("copy"); }
        document.getElementById("shCopy").textContent = "Скопійовано ✓";
      };
      this.textContent = "Готово";
    }catch(err){
      this.disabled = false; this.textContent = "Створити посилання";
      alert("Не вдалося створити посилання: " + err.message);
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
  if (hasDay(d))     btns.push(mkBtn("День",    "day",   d));
  if (hasWeek(d))    btns.push(mkBtn("Тиждень", "week",  d));
  if (hasMonth(mk))  btns.push(mkBtn("Місяць",  "month", mk));
  if (hasYear(year)) btns.push(mkBtn("Рік",     "year",  year));
  if (!btns.length) return;

  const bar = document.createElement("div");
  bar.className = "sh-bar";
  bar.innerHTML = '<span class="sh-cap">Поділитися</span>';
  btns.forEach(b => bar.appendChild(b));

  const h = root.querySelector(".page > h1, .page .phead, .page > .head");
  (h ? h.parentNode : root).insertBefore(bar, h ? h.nextSibling : root.firstChild);
}

/* ---- кнопка в панелі дня ---- */
function mountDayPanel(){
  const panel = document.querySelector(".daypanel");
  if (!panel || panel.querySelector(".sh-day")) return;
  const d = curDay();
  if (!hasDay(d)) return;
  const b = mkBtn("Поділитися днем", "day", d, "sh-day");
  const add = panel.querySelector(".addday");
  add ? panel.insertBefore(b, add) : panel.appendChild(b);
}

/* ---- кнопка в картці угоди ---- */
function mountTradeCard(){
  document.querySelectorAll(".m-foot").forEach(foot => {
    if (foot.querySelector(".sh-trade")) return;
    // картку впізнаємо за кнопкою «Видалити» — у ній лежить id угоди
    const del = foot.querySelector(".danger[onclick*='delTrade']");
    if (!del) return;
    const m = del.getAttribute("onclick").match(/delTrade\('([^']+)'\)/);
    if (!m) return;
    const b = mkBtn("Поділитися", "trade", m[1], "sh-trade");
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
