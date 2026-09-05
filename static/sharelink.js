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

/* Календар днів для знімка тижня чи місяця.

   Раніше тиждень і місяць віддавали лише підсумкові цифри та список
   «по днях» рядками — по ньому не видно ані як лягли дні, ані як
   набиралась кожна позиція. Тепер віддаємо сітку: у кожній клітинці
   день із результатом, а всередині — самі угоди зі скрінами. Хто
   отримав посилання, клацає день і бачить, з чого той склався. */
function dayCells(list, from, to){
  const byDay = groupBy(list, dayKey);          /* це Map */
  const out = [];
  const step = new Date(from + "T00:00"), last = new Date(to + "T00:00");
  while (step <= last){
    const dk = step.getFullYear() + "-" + String(step.getMonth() + 1).padStart(2, "0")
             + "-" + String(step.getDate()).padStart(2, "0");
    const day = sortAsc(byDay.get(dk) || []);
    const st = day.length ? calc(day) : null;
    out.push({
      date: dk,
      n: day.length,
      net: st ? st.net : null,
      wins: st ? st.wins : 0, losses: st ? st.losses : 0, be: st ? st.be : 0,
      trades: day.map(tradeDetail),
    });
    step.setDate(step.getDate() + 1);
  }
  return out;
}

/* розріз: що дало найбільше і найменше */
function sliceBlock(title, list, key){
  /* groupBy у app.js повертає Map, а не звичайний об'єкт: читаємо його
     як Map, інакше розріз завжди виходив порожнім */
  const g = groupBy(list, t => fieldVal(t, key) || "—");
  const items = [...g.keys()]
    .map(name => ({ name, value: calc(g.get(name)).net, n: g.get(name).length }))
    .filter(x => x.n >= 2)
    .sort((a,b) => b.value - a.value)
    .slice(0, 6)
    .map(x => ({ name: x.name + "  ·  " + x.n, value: x.value }));
  return items.length ? { title, items } : null;
}

/* ---------- торгова стратегія ----------
   Правила людини, а не її результати. Беремо те, що вона сама записала в
   розділі «Моя ТС», і нічого не рахуємо: тут нема чого рахувати. */
function tsSnapshot(){
  const ts = (window.__ts && typeof __ts.data === "function") ? __ts.data() : null;
  if (!ts) return null;

  const str = v => String(v == null ? "" : v).trim();
  const shots = list => (list || []).filter(Boolean).map(f => ({file: f}));
  const has = v => !!(v && v.length);

  const tfs = (ts.tfs || [])
    .filter(r => str(r.tf) || str(r.what))
    .map(r => ({tf: str(r.tf), role: str(r.role), what: str(r.what),
                shots: shots([r.shot])}));

  const models = (ts.models || [])
    .filter(m => str(m.name) || str(m.note))
    .map(m => ({name: str(m.name), note: str(m.note),
                shots: shots((m.shots || []).concat(m.shot ? [m.shot] : []))}));

  const windows = (ts.windows || [])
    .filter(w => str(w.name) || str(w.time))
    .map(w => ({name: str(w.name), time: str(w.time), note: str(w.note)}));

  const manage = (ts.manage || [])
    .filter(m => str(m.k) || str(m.v))
    .map(m => ({k: str(m.k), v: str(m.v), shots: shots(m.shots)}));

  const extra = (ts.extra || [])
    .filter(m => str(m.k) || str(m.v))
    .map(m => ({k: str(m.k), v: str(m.v), shots: shots(m.shots)}));

  const cases = (ts.riskCases || [])
    .filter(c => str(c.k) || str(c.v))
    .map(c => ({k: str(c.k), v: str(c.v)}));

  const no = ts.no || {};
  const line = arr => (arr || []).map(str).filter(Boolean);

  const risk = ts.risk || {};
  const rk = [
    {k: T.tsShRr, v: str(risk.rr)}, {k: T.tsShRiskPer, v: str(risk.per)},
    {k: T.tsShDay, v: str(risk.day)}, {k: T.tsShWeek, v: str(risk.week)},
    {k: T.tsShMax, v: str(ts.maxtrades)},
  ].filter(x => x.v);

  const data = {
    kind: T.slKindTs, kindFull: T.slOgTs,
    title: T.tsShTitle,
    total: null,
    kpis: rk,
    ts: {
      assets: line(ts.assets),
      windows: windows,
      days: str(ts.days), news: str(ts.news),
      tfs: tfs,
      models: models,
      bias: str(ts.bias),
      stop: {v: str((ts.stop || {}).v), shots: shots([(ts.stop || {}).shot])},
      target: {v: str((ts.target || {}).v), shots: shots([(ts.target || {}).shot])},
      riskCases: cases,
      manage: manage,
      no: {market: line(no.market), time: line(no.time), self: line(no.self)},
      mind: str(ts.mind),
      check: line(ts.check),
      extra: extra,
    },
    blocks: [],
  };

  /* порожньою стратегією ділитись нема чого */
  const t = data.ts;
  const any = has(t.assets) || has(t.tfs) || has(t.models) || has(t.manage)
    || has(t.check) || has(t.extra) || t.bias || t.mind || t.stop.v || t.target.v
    || has(t.no.market) || has(t.no.time) || has(t.no.self) || rk.length;
  return any ? data : null;
}

/* ---------- розбір дня ----------
   Знімок дня показує цифри й угоди. А розбір — це те, як людина дивилась
   на графік зранку: куди дивилась, які рівні відмітила, що планувала — і
   що з цього вийшло ввечері. Саме цим і цікаво ділитись: не результатом,
   а мисленням. Дані беремо з розділу «Аналіз дня» (day.js тримає їх у
   базі), а не з угод. */
function reviewSnapshot(dk, pick){
  const n = (window.__dv && typeof __dv.note === "function") ? __dv.note(dk) : null;
  if (!n || !(n.assets || []).length) return null;
  /* pick — які активи лишити. null означає «всі». */
  const keep = (pick && pick.length)
    ? n.assets.filter((a, i) => pick.indexOf(i) >= 0)
    : n.assets;
  if (!keep.length) return null;

  const norm = x => String(x || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  const day = sortAsc(S.all.filter(t => dayKey(t) === dk));
  /* цифри зверху — по тих активах, якими ділимось, а не по всьому дню */
  const names = keep.map(a => norm(a.nm)).filter(Boolean);
  const mineAll = names.length
    ? day.filter(t => names.indexOf(norm(t.pair)) >= 0) : day;
  const d = new Date(dk + "T00:00");

  const assets = keep.map(a => {
    const mine = a.nm ? day.filter(t => norm(t.pair) === norm(a.nm)) : [];
    const st = mine.length ? calc(mine) : null;
    return {
      nm: a.nm || "",
      side: a.side || "",
      why: a.why || "",
      shots: (a.shots || []).filter(x => x.file).map(x => ({tf: x.tf || "", file: x.file})),
      levels: (a.levels || []).filter(l => l.p || l.t || l.n || l.did)
        .map(l => ({p: l.p || "", t: l.t || "", n: l.n || "", did: l.did || "", cls: l.dcls || ""})),
      plans: (a.plans || []).map((pl, i) => ({k: i ? "Б" : "A", tx: (pl || {}).tx || ""}))
        .filter(pl => pl.tx),
      eve: {text: ((a.eve || {}).text) || "",
            shots: (((a.eve || {}).shots) || []).filter(x => x.file)
              .map(x => ({tf: x.tf || "", file: x.file}))},
      marks: {match: (a.marks || {}).match || "", hold: (a.marks || {}).hold || ""},
      net: st ? st.net : null,
      trades: mine.map(tradeDetail),
    };
  });

  return {
    kind: T.slKindReview, kindFull: T.slOgReview,
    /* коли ділишся одним активом — його ім'я в заголовку: так із превью
       одразу видно, про що знімок */
    title: (keep.length === 1 && keep[0].nm ? keep[0].nm + " · " : "")
         + d.getDate() + " " + T.monthsGen[d.getMonth()] + " " + d.getFullYear(),
    total: mineAll.length ? calc(mineAll).net : null,
    kpis: mineAll.length ? statsOf(mineAll) : [],
    review: {
      closed: !!n.closed,
      skip: n.skip || "",
      lesson: (n.fact || {}).lesson || "",
      assets: assets,
    },
    blocks: [],
  };
}

function daySnapshot(dk){
  const list = sortAsc(S.all.filter(t => dayKey(t) === dk));
  const d = new Date(dk + "T00:00");
  return {
    kind: T.slKindDay, kindFull: T.slOgDay,
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
  return {
    kind: T.slKindWeek, kindFull: T.slOgWeek,
    title: mon.getDate() + " " + T.monthsGen[mon.getMonth()] + " — "
         + sun.getDate() + " " + T.monthsGen[sun.getMonth()],
    total: calc(list).net,
    kpis: statsOf(list),
    /* сітку днів показуємо замість списку «по днях»: те саме, але видно
       розклад тижня й можна зайти в конкретний день */
    calendar: {span: "week", from: from, to: to, days: dayCells(list, from, to)},
    blocks: [
      sliceBlock(T.railSetups, list, "setup"),
      sliceBlock(T.railInstruments, list, "pair"),
    ].filter(Boolean),
  };
}

function monthSnapshot(mk){
  const list = S.all.filter(t => monKey(t) === mk);
  const [y, m] = mk.split("-");
  const last = new Date(+y, +m, 0).getDate();
  const from = mk + "-01", to = mk + "-" + String(last).padStart(2, "0");
  return {
    kind: T.slKindMonth, kindFull: T.slOgMonth,
    title: T.months[+m - 1] + " " + y,
    total: calc(list).net,
    kpis: statsOf(list),
    calendar: {span: "month", from: from, to: to, days: dayCells(list, from, to)},
    blocks: [
      sliceBlock(T.railSetups, list, "setup"),
      sliceBlock(T.railInstruments, list, "pair"),
      sliceBlock(T.railSessions, list, "session"),
    ].filter(Boolean),
  };
}

function yearSnapshot(y){
  const list = S.all.filter(t => (t.date||"").slice(0,4) === String(y));
  const months = groupBy(list, monKey);
  const byMonth = [...months.keys()].sort()
    .map(mk => ({ name: T.months[+mk.slice(5,7) - 1], value: calc(months.get(mk)).net }));
  return {
    kind: T.slKindYear, kindFull: T.slOgYear,
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
    kind: T.slKindTrade, kindFull: T.slOgTrade,
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
  /* У розборі дня активів може бути кілька, і ділитись усіма потрібно не
     завжди. Тримаємо вибір тут і перезбираємо знімок, коли він міняється. */
  let pick = null;
  const build = () => kind === "trade"  ? tradeSnapshot(arg)
             : kind === "ts"     ? tsSnapshot()
             : kind === "review" ? reviewSnapshot(arg, pick)
             : kind === "day"    ? daySnapshot(arg)
             : kind === "week"  ? weekSnapshot(arg)
             : kind === "month" ? monthSnapshot(arg)
             :                    yearSnapshot(arg);
  let data = build();
  if (!data) return;

  /* назви активів для перемикачів — беремо до того, як звузили вибір */
  const allAssets = kind === "review"
    ? ((((window.__dv && __dv.note && __dv.note(arg)) || {}).assets) || [])
        .map((a, i) => ({i: i, nm: a.nm || T.slAssetNoName}))
    : [];

  openModal(
    '<div class="m-head"><b>' + T.slShareTitle + '</b><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + T.mrClose + '</button></div>'
    + '<div class="m-body sh-body">'
    + '<p class="sh-note">' + T.slNote
    + (kind === "trade" || kind === "day" ? " " + T.slNoteImg : "") + '</p>'
    + '<div class="sh-what" id="shWhat"><b>' + esc(data.title) + '</b><span>'
    +   esc(data.kind) + '</span></div>'
    + (allAssets.length > 1
        ? '<div class="sh-lab">' + T.slAssetsLabel + '</div>'
          + '<div class="sh-assets" id="shAssets">'
          + '<button class="sh-chip on" data-a="all">' + esc(T.slAssetsAll) + '</button>'
          + allAssets.map(a => '<button class="sh-chip" data-a="' + a.i + '">'
              + esc(a.nm) + '</button>').join("")
          + '</div>'
        : "")
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

  document.querySelectorAll(".sh-ttl .sh-chip").forEach(b => b.onclick = () => {
    lastTtl = b.dataset.t;
    try{ localStorage.setItem("share_ttl", lastTtl); }catch(e){}
    document.querySelectorAll(".sh-ttl .sh-chip").forEach(x => x.classList.toggle("on", x === b));
  });

  /* вибір активів: «усі» вимикає решту, і навпаки */
  const box = document.getElementById("shAssets");
  if (box) box.querySelectorAll(".sh-chip").forEach(b => b.onclick = () => {
    const all = box.querySelector('[data-a="all"]');
    if (b === all){
      pick = null;
      box.querySelectorAll(".sh-chip").forEach(x => x.classList.toggle("on", x === all));
    } else {
      b.classList.toggle("on");
      all.classList.remove("on");
      pick = [...box.querySelectorAll('.sh-chip.on[data-a]')]
        .map(x => Number(x.dataset.a)).filter(n => !isNaN(n));
      if (!pick.length){ pick = null; all.classList.add("on"); }
    }
    const fresh = build();
    if (fresh){
      data = fresh;
      const what = document.getElementById("shWhat");
      if (what) what.innerHTML = '<b>' + esc(data.title) + '</b><span>'
        + esc(data.kind) + '</span>';
    }
    /* вибір змінився — стара адреса вже не про це */
    const out = document.getElementById("shOut");
    if (out){ out.hidden = true; out.innerHTML = ""; }
    const go = document.getElementById("shGo");
    if (go){ go.disabled = false; go.textContent = T.slCreateBtn; }
  });

  document.getElementById("shGo").onclick = async function(){
    this.disabled = true; this.textContent = T.slCreating;
    try{
      /* Для тижня й місяця малюємо календар — він піде в превью посилання.
         Не вийшло намалювати чи покласти — не біда: посилання створиться
         й без картинки, просто в месенджері буде без неї. */
      if ((data.calendar || data.ts) && window.OgCal){
        try{
          const png = data.ts ? OgCal.system(data) : OgCal.period(data);
          const up = await fetch("/api/share/shot", {
            method:"POST", headers:{"Content-Type":"application/json"},
            body: JSON.stringify({data: png})
          });
          if (up.ok) data.og = (await up.json()).file;
        }catch(e){}
      }
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
  /* підпис у своєму span — у вузькій шапці картки його ховають стилі */
  b.innerHTML = icon() + " <span>" + label + "</span>";
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

/* ---- кнопка «поділитись» біля угоди ----
   Два місця, і обидва на очах.

   У картці кнопка стоїть у шапці, поруч із результатом. Раніше вона була
   внизу, за деталями входу й скрінами: щоб її побачити, доводилось
   прокрутити всю угоду — і люди її просто не знаходили. Шапка не
   прокручується, тож звідти вона вже нікуди не подінеться.

   Друге місце — сам рядок у панелі дня: значок без підпису, щоб
   поділитись угодою, не відкриваючи її.

   id угоди в картці беремо з кнопки «Видалити» — більше його взяти
   нізвідки; у рядку він лежить у data-id. */
function tradeIdIn(box){
  const del = box && box.querySelector(".danger[onclick*='delTrade']");
  const m = del && del.getAttribute("onclick").match(/delTrade\('([^']+)'\)/);
  return m ? m[1] : null;
}

function mountTradeCard(){
  /* картка: кнопка в шапці, перед хрестиком */
  document.querySelectorAll(".m-head.thead").forEach(head => {
    if (head.querySelector(".sh-trade")) return;
    const id = tradeIdIn(head.parentNode);
    if (!id) return;
    const b = mkBtn(T.slShareTrade, "trade", id, "sh-trade sh-top");
    const x = head.querySelector(".x");
    x ? head.insertBefore(b, x) : head.appendChild(b);
  });

  /* рядок у панелі дня: значок перед мітками */
  document.querySelectorAll(".dtrade[data-id]").forEach(row => {
    if (row.querySelector(".sh-trade")) return;
    const b = mkBtn(T.slShareTrade, "trade", row.dataset.id, "sh-trade sh-row");
    b.title = T.slShareTrade;
    /* мітка напрямку лежить усередині назви інструмента, тому шукаємо
       мітку саме серед прямих дітей рядка — інакше insertBefore впаде */
    const badge = [...row.children].find(el => el.classList.contains("badge"));
    badge ? row.insertBefore(b, badge) : row.appendChild(b);
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
