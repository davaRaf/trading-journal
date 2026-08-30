/* Trading Journal — вся логика на клиенте, данные через /api */
"use strict";

/* ---------------- состояние ---------------- */
const now = new Date();
const S = {
  trades: [],
  view: "dashboard",
  selDay: isoDay(now),          // выбранный день в Journal
  jMonth: isoMonth(now),        // месяц календаря Journal
  jMode: "cal",                 // cal | list
  mMonth: isoMonth(now),        // Monthly
  qYear: now.getFullYear(),     // Quarterly
  yYear: now.getFullYear(),     // Yearly
  dim: "setup",                 // Analytics
  filters: {},
  formShots: [],
  all: [], mRep:null,
};

const MONTHS = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const WDS = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];
const TF_LIST = ["1m","3m","5m","15m","30m","1H","4H","1D","1W"];
const TF_SLOTS = ["1m","3m","5m","15m","30m","1H","4H"];
const TF_ORDER = ["1W","1D","4H","1H","30m","15m","5m","3m","1m"];
const SESSIONS = ["LONDON","NY","FRANKFURT","PH","PM"];
/* активы для подсказок в форме. Старые инструменты (форекс, золото) остаются
   в статистике полностью, но новую сделку по ним не предлагаем. */
const PAIRS_ACTIVE = ["US100","GER40","ES500"];
const DIMS = [
  {k:"pair",label:"Pair"},{k:"session",label:"Session"},{k:"position",label:"Position"},
  {k:"entry_model",label:"Entry Model"},{k:"bias",label:"Bias"},{k:"setup",label:"Setup"},
  {k:"direction_type",label:"Cont / Rev"},{k:"result",label:"TP / SL / BE"},{k:"mistakes",label:"Mistakes"},
];

/* ---------------- утилиты ---------------- */
function $(s){ return document.querySelector(s); }
function pad(n){ return (n<10?"0":"")+n; }
function isoDay(d){ return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate()); }
function isoMonth(d){ return d.getFullYear()+"-"+pad(d.getMonth()+1); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function shotSrc(s){ return s.file?"/shots/"+esc(s.file):(s.data||""); }
function r1(v){ return Math.round(v*100)/100; }
function fmtR(v){ if(v==null||isNaN(v)) return "—"; const x=r1(v); return (x>0?"+":"")+x+"%"; }
function clsR(v){ return v>0.0001?"pos":v<-0.0001?"neg":"beclr"; }
function fmtPct(v){ return v==null?"—":(Math.round(v*10)/10)+"%"; }
function num(v){ const x=parseFloat(v); return isNaN(x)?null:x; }
/* в интерфейсе результат называется TP / SL / BE, внутри хранится Win / Loss / BE */
const RES_LABEL={Win:"TP",Loss:"SL","BE-":"BE\u2212","BE+":"BE+",BE:"BE"};
const BE_SET=["BE","BE-","BE+"];
function isBE(t){ return BE_SET.indexOf(t.result)>=0; }
/* сколько безубыток спас (BE-) или отнял (BE+) */
function beValue(t){
  const risk=(t.risk!=null&&!isNaN(t.risk))?t.risk:1;
  if(t.result==="BE-") return risk;                       // не дал потерять
  if(t.result==="BE+") return -(risk*(t.rr!=null?t.rr:0)); // не дал заработать
  return 0;
}
function resLabel(r){ return RES_LABEL[r]||r||""; }

/* Результат сделки в % от депозита — как «% Profit» в Notion.
   Стоп забирает ровно свой риск: рискнул 1.5% -> -1.5%.
   Тейк даёт риск x RR. Безубыток -> 0. Риск не указан -> считаем 1%. */
function netR(t){
  const risk = (t.risk!=null && !isNaN(t.risk)) ? t.risk : 1;
  if(t.result==="Win")  return risk * (t.rr!=null ? t.rr : 0);
  if(t.result==="Loss") return -risk;
  return 0;
}
function dayKey(t){ return (t.date||"").slice(0,10); }
function monKey(t){ return (t.date||"").slice(0,7); }

/* Continuation / Reversal — выводится из позиции и биаса.
   Вошёл по биасу → продолжение, против биаса → разворот.
   Если поле проставлено руками, оно и остаётся. */
function dirType(t){
  if((t.direction_type||"").trim()) return t.direction_type.trim();
  const p=(t.position||"").trim().toLowerCase(), b=(t.bias||"").trim().toLowerCase();
  if(!p || !b) return "";
  return p===b ? "Continuation" : "Reversal";
}
function fieldVal(t,k){ return k==="direction_type" ? dirType(t) : (t[k]||""); }

function calc(list){
  const n=list.length;
  let wins=0,losses=0,be=0,beM=0,beP=0,beSaved=0,beLost=0,net=0,gw=0,gl=0,rrS=0,rrN=0,riskS=0,riskN=0;
  for(const t of list){
    if(t.result==="Win")wins++; else if(t.result==="Loss")losses++; else {be++;
      if(t.result==="BE-")beM++; else if(t.result==="BE+")beP++;
      beSaved+=Math.max(0,beValue(t)); beLost+=Math.max(0,-beValue(t)); }
    const r=netR(t); net+=r; if(r>0)gw+=r; else if(r<0)gl-=r;
    if(t.rr!=null){rrS+=t.rr;rrN++;}
    if(t.risk!=null){riskS+=t.risk;riskN++;}
  }
  return {
    n,wins,losses,be,beM,beP,beSaved,beLost,net,
    wr: wins+losses ? wins/(wins+losses)*100 : null,
    avgRR: rrN? rrS/rrN : null,
    pf: gl>0 ? gw/gl : (gw>0?null:null),
    pfTxt: gl>0 ? String(r1(gw/gl)) : (gw>0?"∞":"—"),
    avgRisk: riskN? riskS/riskN : null,
  };
}

function sortAsc(list){ return list.slice().sort((a,b)=> (a.date||"")<(b.date||"")?-1:1); }
function sortDesc(list){ return list.slice().sort((a,b)=> (a.date||"")>(b.date||"")?-1:1); }

function groupBy(list, keyFn){
  const m=new Map();
  for(const t of list){
    const k=(keyFn(t)||"").toString().trim();
    if(!k) continue;
    if(!m.has(k)) m.set(k,[]);
    m.get(k).push(t);
  }
  return m;
}

/* ---------------- API ---------------- */
/* DEMO=true — сервера нет (например, публичное демо), данные лежат в браузере. */
let DEMO=false;
async function api(method,url,body){
  if(DEMO) return DemoStore.handle(method,url,body);
  const res=await fetch(url,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  if(!res.ok) throw new Error("API "+res.status);
  return res.json();
}
async function reload(){
  S.all = await api("GET","/api/trades");
  S.trades = S.all;          // в статистике участвуют все сделки
}


/* ---------------- KPI ---------------- */
function kpiHtml(st, opts){
  opts=opts||{};
  const cells=[
    ["Trades", st.n, ""],
    ["Win Rate", fmtPct(st.wr), ""],
    ["Итог, %", fmtR(st.net), clsR(st.net)],
    ["Средний RR", st.avgRR!=null?r1(st.avgRR):"—", ""],
    ["Profit Factor", st.pfTxt, ""],
    ["TP / SL / BE", st.wins+" / "+st.losses+" / "+st.be, "small"],
    ["BE\u2212 / BE+", st.beM+" / "+st.beP, "small"],
  ];
  if(!opts.compact) cells.push(["Avg Risk", st.avgRisk!=null?r1(st.avgRisk)+"%":"—",""]);
  return '<div class="kpis">'+cells.map(c=>
    '<div class="kpi"><div class="l">'+c[0]+'</div><div class="v '+c[2]+'">'+c[1]+'</div></div>').join("")+"</div>";
}

/* ---------------- график equity ---------------- */
function equitySVG(list){
  const arr=sortAsc(list);
  if(arr.length<2) return '<div class="empty">Недостаточно сделок для графика</div>';
  const eq=[]; let acc=0;
  for(const t of arr){ acc+=netR(t); eq.push(acc); }
  const W=900,H=200,padL=10,padR=10,padT=16,padB=10;
  const lo=Math.min(0,...eq), hi=Math.max(0.001,...eq);
  const x=i=>padL+i*(W-padL-padR)/(eq.length-1);
  const y=v=>padT+(hi-v)*(H-padT-padB)/(hi-lo||1);
  const line=eq.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
  const area="M"+x(0)+","+y(0)+" "+eq.map((v,i)=>"L"+x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ")+" L"+x(eq.length-1)+","+y(0)+" Z";
  const last=eq[eq.length-1];
  const hiI=eq.indexOf(Math.max(...eq)), loI=eq.indexOf(Math.min(...eq));
  /* подпись рисуем обычным блоком поверх: внутри растянутого SVG текст кривило */
  return '<div class="eqwrap">'+
    '<svg class="chart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
      '<line class="zero" x1="'+padL+'" x2="'+(W-padR)+'" y1="'+y(0)+'" y2="'+y(0)+'"/>'+
      '<path class="eqarea" d="'+area+'"/>'+
      '<path class="eqline" d="'+line+'"/>'+
      '<circle class="dot end" cx="'+x(eq.length-1)+'" cy="'+y(last)+'" r="4"/>'+
    "</svg>"+
    '<span class="eqval '+clsR(last)+'">'+fmtR(last)+"</span>"+
    '<span class="eqrange">макс '+fmtR(eq[hiI])+" · мин "+fmtR(eq[loI])+"</span>"+
  "</div>";
}

/* ---------------- список сделок ---------------- */
function tradeRow(t){
  const r=netR(t);
  const badge='<span class="badge '+(t.result==="Win"?"win":t.result==="Loss"?"loss":t.result==="BE+"?"beplus":"be")+'">'+resLabel(t.result)+"</span>";
  const pos=t.position?'<span class="badge '+(t.position==="Long"?"long":"short")+'">'+esc(t.position)+"</span>":"";
  const d=(t.date||"").replace("T"," ").slice(0,16);
  const dt=dirType(t);
  const dtb=dt?'<span class="badge '+(dt==="Reversal"?"rev":"cont")+'">'+(dt==="Reversal"?"REV":"CONT")+"</span>":"";
  const info=[t.setup,t.session,t.entry_model].filter(Boolean).map(esc).join(" · ");
  return '<div class="trow" onclick="openTrade(\''+t.id+'\')">'+
    '<span class="d">'+esc(d)+'</span><span class="p">'+esc(t.pair||"—")+" "+pos+"</span>"+
    '<span class="info">'+info+"</span>"+dtb+badge+
    '<span class="r '+clsR(r)+'">'+fmtR(r)+"</span></div>";
}
function tradesCard(list,title){
  const rows=list.length?list.map(tradeRow).join(""):'<div class="empty">Сделок нет</div>';
  return '<div class="card"><h3>'+esc(title)+'</h3><div class="tlist">'+rows+"</div></div>";
}

/* ---------------- календарь: тепловая карта месяца ---------------- */
function calHtml(ym, clickFn, selDay){
  const [Y,M]=ym.split("-").map(Number);
  const byDay=groupBy(S.trades, dayKey);
  const first=new Date(Y,M-1,1);
  const start=(first.getDay()+6)%7;
  const dim=new Date(Y,M,0).getDate();
  const today=isoDay(new Date());
  let h='<div class="cal">'+WDS.map(w=>'<div class="wd">'+w+"</div>").join("");
  for(let i=0;i<start;i++) h+='<div class="day off"></div>';
  for(let d=1;d<=dim;d++){
    const key=Y+"-"+pad(M)+"-"+pad(d);
    const list=byDay.get(key)||[];
    const net=list.reduce((a,t)=>a+netR(t),0);
    const tint=list.length?(net>0.0001?" up":net<-0.0001?" down":" flat"):"";
    const cls=tint+(key===selDay?" sel":"")+(key===today?" today":"");
    let body="";
    if(list.length){
      const marks=sortAsc(list).map(t=>{
        const rv=dirType(t)==="Reversal";
        if(t.result==="Win")  return '<i class="mk tp'+(rv?" rev":"")+'" title="Тейк'+(rv?" · разворот":"")+'">TP</i>';
        if(t.result==="Loss") return '<i class="mk sl'+(rv?" rev":"")+'" title="Стоп'+(rv?" · разворот":"")+'">SL</i>';
        if(t.result==="BE+")  return '<i class="mk beplus'+(rv?" rev":"")+'" title="Безубыток, потом дошло бы до цели">BE+</i>';
        return '<i class="mk be'+(rv?" rev":"")+'" title="Безубыток, потом пошло против">BE\u2212</i>';
      }).join("");
      body='<div class="marks">'+marks+'</div><div class="res '+clsR(net)+'">'+fmtR(net)+"</div>";
    }
    h+='<div class="day'+cls+'" onclick="'+clickFn+'(\''+key+'\')"><div class="n">'+d+"</div>"+body+"</div>";
  }
  return h+"</div>";
}

/* ---------------- фильтры ---------------- */
/* самые частые осмысленные значения поля — для быстрых подсказок */
function topVals(field,n){
  const cnt=new Map();
  for(const t of S.trades){
    const v=fieldVal(t,field).toString().trim();
    if(v.length<3) continue;                 // мусор вроде "-" пропускаем
    if(/^[-—\s.,()]+$/.test(v)) continue;
    cnt.set(v,(cnt.get(v)||0)+1);
  }
  return [...cnt.entries()].sort((a,b)=>b[1]-a[1]).slice(0,n||6).map(x=>x[0]);
}

function uniqueVals(field){
  const set=new Set();
  for(const t of S.trades){ const v=fieldVal(t,field).toString().trim(); if(v) set.add(v); }
  return [...set].sort();
}
function filterBar(){
  const selects=[["result","Result",["Win","Loss","BE-","BE+"]],["position","Position",["Long","Short"]],
    ["pair","Pair",uniqueVals("pair")],["session","Session",uniqueVals("session")],
    ["setup","Setup",uniqueVals("setup")],["entry_model","Model",uniqueVals("entry_model")],
    ["bias","Bias",uniqueVals("bias")],["direction_type","C/R",["Continuation","Reversal"]]];
  let h='<div class="filters">';
  for(const [f,label,vals] of selects){
    if(!vals.length) continue;
    h+='<select onchange="setFilter(\''+f+'\',this.value)"><option value="">'+label+"</option>"+
      vals.map(v=>'<option '+(S.filters[f]===v?"selected":"")+' value="'+esc(v)+'">'+esc(f==="result"?resLabel(v):v)+"</option>").join("")+"</select>";
  }
  h+='<input type="date" value="'+(S.filters.from||"")+'" onchange="setFilter(\'from\',this.value)" title="с даты">';
  h+='<input type="date" value="'+(S.filters.to||"")+'" onchange="setFilter(\'to\',this.value)" title="по дату">';
  if(Object.keys(S.filters).some(k=>S.filters[k])) h+='<button class="clear" onclick="clearFilters()">Сбросить ×</button>';
  return h+"</div>";
}
function setFilter(f,v){ if(v)S.filters[f]=v; else delete S.filters[f]; render(); }
function clearFilters(){ S.filters={}; render(); }
function applyFilters(list){
  return list.filter(t=>{
    for(const k of ["result","position","pair","session","setup","entry_model","bias","direction_type"])
      if(S.filters[k] && fieldVal(t,k).toString().trim()!==S.filters[k]) return false;
    if(S.filters.from && dayKey(t)<S.filters.from) return false;
    if(S.filters.to && dayKey(t)>S.filters.to) return false;
    return true;
  });
}

/* ================= VIEWS ================= */

function vDashboard(){
  if(!S.trades.length){
    return '<div class="vhead"><h1>Dashboard</h1></div>'+
      '<div class="card"><div class="in" style="text-align:center;padding:56px 20px">'+
      '<div style="font-size:38px;margin-bottom:10px">📓</div>'+
      '<div style="font-size:17px;font-weight:600;margin-bottom:6px">Журнал пуст</div>'+
      '<div class="hint" style="margin-bottom:18px">Добавь первую сделку — статистика соберётся сама.<br>Старые сделки можно загрузить через «Импорт» слева внизу.</div>'+
      '<button class="btn primary" onclick="openForm()">+ New Trade</button></div></div>';
  }
  const today=new Date();
  const mKey=isoMonth(today), yKey=String(today.getFullYear());
  const mT=S.trades.filter(t=>monKey(t)===mKey);
  const yT=S.trades.filter(t=>(t.date||"").slice(0,4)===yKey);
  const mSt=calc(mT), ySt=calc(yT);
  let h='<div class="vhead"><h1>Dashboard</h1><span class="sub">'+S.trades.length+' сделок всего</span></div>';

  /* --- текущий месяц --- */
  h+='<div class="seclab"><div class="t"><span class="tag">Текущий месяц</span>'+
     '<h2>'+MONTHS[today.getMonth()]+" "+yKey+'</h2></div>'+
     '<div class="big '+clsR(mSt.net)+'">'+(mT.length?fmtR(mSt.net):"—")+"</div></div>";
  if(mT.length){
    h+=kpiHtml(mSt);
    h+='<div class="split">'+
      '<div class="card"><h3>Equity месяца · %</h3><div class="in">'+equitySVG(mT)+"</div></div>"+
      tradesCard(sortDesc(mT).slice(0,5),"Последние сделки месяца")+"</div>";
  }else{
    h+='<div class="card"><div class="empty">В этом месяце сделок ещё нет.<br><br>'+
      '<button class="btn primary" onclick="openForm()">+ New Trade</button></div></div>';
  }

  /* --- весь год --- */
  h+='<div class="seclab year"><div class="t"><span class="tag">Весь год</span>'+
     '<h2>'+yKey+'</h2></div>'+
     '<div class="big '+clsR(ySt.net)+'">'+(yT.length?fmtR(ySt.net):"—")+"</div></div>";
  h+=kpiHtml(ySt);
  if(yT.length) h+='<div class="card"><h3>Equity года · %</h3><div class="in">'+equitySVG(yT)+"</div></div>";
  let mrows="";
  for(let m=1;m<=12;m++){
    const ml=yT.filter(t=>monKey(t)===yKey+"-"+pad(m));
    if(!ml.length) continue;
    const ms=calc(ml);
    mrows+='<tr class="click" onclick="S.jMonth=\''+yKey+"-"+pad(m)+'\';S.jMode=\'cal\';location.hash=\'journal\';render()">'+
      "<td>"+MONTHS[m-1]+"</td><td>"+ms.n+"</td><td>"+fmtPct(ms.wr)+'</td><td class="'+clsR(ms.net)+'">'+fmtR(ms.net)+"</td><td>"+(ms.avgRR!=null?r1(ms.avgRR):"—")+"</td></tr>";
  }
  if(mrows) h+='<div class="card"><h3>По месяцам</h3><table class="simple"><tr><th>Month</th><th>Trades</th><th>Win Rate</th><th>Итог, %</th><th>Ср. RR</th></tr>'+mrows+"</table></div>";
  return h;
}

/* ---------- Journal: живой журнал месяца ---------- */
function vJournal(){
  const [Y,M]=S.jMonth.split("-").map(Number);
  const label=MONTHS[M-1]+" "+Y;
  const monthTrades=S.trades.filter(t=>monKey(t)===S.jMonth);
  const st=calc(monthTrades);
  const modeBtns='<button class="pill '+(S.jMode==="cal"?"on":"")+'" onclick="S.jMode=\'cal\';render()">Месяц</button>'+
    '<button class="pill '+(S.jMode==="list"?"on":"")+'" onclick="S.jMode=\'list\';render()">Все сделки</button>';

  let h='<div class="vhead"><h1>Journal</h1>';
  if(S.jMode==="cal"){
    h+='<div class="right">'+
      '<button class="navbtn" onclick="shiftJMonth(-1)">‹</button><span class="perlabel">'+label+'</span><button class="navbtn" onclick="shiftJMonth(1)">›</button>'+
      '<button class="pill" onclick="goToday()">Сегодня</button>'+
      '<button class="pill share" data-ym="'+S.jMonth+'" onclick="openShare(this.dataset.ym)">Картинка для канала</button>'+
      modeBtns+"</div></div>";
  }else{
    h+='<div class="right">'+modeBtns+"</div></div>";
    const list=sortDesc(applyFilters(S.trades));
    return h+filterBar()+tradesCard(list,"Все сделки · "+list.length);
  }

  /* лента статистики месяца */
  h+=kpiHtml(st);

  /* выбранный день */
  if(S.selDay.slice(0,7)!==S.jMonth){
    const today=isoDay(new Date());
    S.selDay = today.slice(0,7)===S.jMonth ? today : S.jMonth+"-01";
  }
  const dayTrades=sortAsc(S.trades.filter(t=>dayKey(t)===S.selDay));
  const dst=calc(dayTrades);
  const mistakes=dayTrades.filter(t=>(t.mistakes||"").trim()).map(t=>esc(t.mistakes));
  const dsel=new Date(S.selDay+"T00:00");
  const dayLabel=dsel.getDate()+" "+MONTHS[dsel.getMonth()].toLowerCase()+", "+WDS[(dsel.getDay()+6)%7];

  let chips="";
  if(dayTrades.length){
    chips='<div class="chips">'+
      '<span class="chip"><b>'+dst.n+"</b> сд</span>"+
      '<span class="chip '+(dst.net>0?"pos":dst.net<0?"neg":"")+'">'+fmtR(dst.net)+"</span>"+
      (dst.wr!=null?'<span class="chip">WR <b>'+fmtPct(dst.wr)+"</b></span>":"")+
      (dst.avgRR!=null?'<span class="chip">ср. RR <b>'+r1(dst.avgRR)+"</b></span>":"")+
      "</div>";
  }
  const dayPanel =
    '<div class="card daypanel"><h3>'+dayLabel+"</h3>"+chips+
    (mistakes.length?'<div class="mistline">Ошибки: <span class="neg">'+mistakes.join(" · ")+"</span></div>":"")+
    (dayTrades.length
      ? '<div class="tlist">'+dayTrades.map(tradeRow).join("")+"</div>"
      : '<div class="empty">Сделок нет</div>')+
    '<button class="addday" onclick="openForm(null,\''+S.selDay+'\')">+ Сделка на этот день</button>'+
    "</div>";

  h+='<div class="jgrid">'+
    '<div class="card">'+calHtml(S.jMonth,"pickDay",S.selDay)+
      '<div class="callegend"><i class="mk tp">TP</i>тейк<i class="mk sl">SL</i>стоп<i class="mk be">BE</i>безубыток'+
      '<span class="lgend-rev"><i class="mk tp rev">TP</i>рамка — разворот против биаса</span></div>'+
    "</div>"+dayPanel+"</div>";

  /* месяц целиком: динамика и разрезы */
  if(monthTrades.length){
    h+='<div class="split">'+
      '<div class="card"><h3>Equity месяца · %</h3><div class="in">'+equitySVG(monthTrades)+"</div></div>"+
      '<div style="min-width:0">'+bestWorstHtml(monthTrades)+"</div></div>";
    h+=beReportHtml(monthTrades);
    h+=tradesCard(sortDesc(monthTrades),"Сделки месяца · "+monthTrades.length);
  }
  return h;
}
function shiftJMonth(d){ const [y,m]=S.jMonth.split("-").map(Number); const dt=new Date(y,m-1+d,1); S.jMonth=isoMonth(dt); render(); }
function pickDay(key){ S.selDay=key; if(key.slice(0,7)!==S.jMonth)S.jMonth=key.slice(0,7); render(); }
function goToday(){ const t=new Date(); S.selDay=isoDay(t); S.jMonth=isoMonth(t); render(); }


/* ---------- разбор безубытков: спасли или отняли ---------- */
function beReportHtml(list){
  const be=list.filter(isBE);
  if(!be.length) return "";
  const st=calc(list);
  const minus=be.filter(t=>t.result==="BE-"), plus=be.filter(t=>t.result==="BE+");
  const saved=st.beSaved, lost=st.beLost, delta=saved-lost;
  const share=Math.round(be.length/list.length*100);
  const verdict = delta>0.001
    ? "Безубыток в плюсе: спас больше, чем отнял. Держим как есть."
    : delta<-0.001
      ? "Безубыток в минусе: забрал больше, чем спас. Переносишь стоп рано."
      : "Безубыток вышел в ноль.";
  const bar=(a,b)=>{
    const m=Math.max(a,b,0.001);
    return '<div class="bebar"><span class="t" style="width:'+(a/m*100)+'%;background:var(--up)"></span></div>'+
           '<div class="bebar"><span class="t" style="width:'+(b/m*100)+'%;background:var(--down)"></span></div>';
  };
  return '<div class="card"><h3>Безубытки · спасли или отняли</h3><div class="in">'+
    '<div class="begrid">'+
      '<div class="becell"><div class="l">BE\u2212 · спасли от стопа</div>'+
        '<div class="v pos">+'+r1(saved)+'%</div><div class="s">'+minus.length+' сделок — цена пошла против, стоп бы забрал деньги</div></div>'+
      '<div class="becell"><div class="l">BE+ · отняли тейк</div>'+
        '<div class="v neg">\u2212'+r1(lost)+'%</div><div class="s">'+plus.length+' сделок — цена дошла бы до цели без тебя</div></div>'+
      '<div class="becell"><div class="l">Чистый эффект</div>'+
        '<div class="v '+clsR(delta)+'">'+fmtR(delta)+'</div><div class="s">'+verdict+'</div></div>'+
      '<div class="becell"><div class="l">Доля безубытков</div>'+
        '<div class="v beclr">'+share+'%</div><div class="s">'+be.length+' из '+list.length+' сделок</div></div>'+
    "</div>"+bar(saved,lost)+
    '<div class="behint">BE\u2212 — тапнуло в безубыток, дальше пошло против: безубыток сработал в твою пользу. '+
    'BE+ — тапнуло в безубыток, а дальше цена дошла до цели: сделка была бы прибыльной.</div>'+
    "</div></div>";
}

/* ---------- разрезы месяца ---------- */
function bestWorstHtml(list){
  const dims=[["setup","Setup"],["pair","Pair"],["entry_model","Entry Model"],["session","Session"],
              ["direction_type","Cont / Rev"],["bias","Bias"],["position","Position"]];
  let cells="";
  for(const [k,label] of dims){
    const groups=[...groupBy(list,t=>fieldVal(t,k)).entries()].map(([name,arr])=>({name,net:arr.reduce((a,t)=>a+netR(t),0),n:arr.length}));
    if(!groups.length) continue;
    groups.sort((a,b)=>b.net-a.net);
    const best=groups[0], worst=groups[groups.length-1];
    cells+='<div class="cell"><div class="t">'+label+"</div>"+
      '<div class="row"><span class="k">↑ '+esc(best.name)+' · '+best.n+'</span><span class="v '+clsR(best.net)+'">'+fmtR(best.net)+"</span></div>"+
      (groups.length>1?'<div class="row"><span class="k">↓ '+esc(worst.name)+' · '+worst.n+'</span><span class="v '+clsR(worst.net)+'">'+fmtR(worst.net)+"</span></div>":"")+
      "</div>";
  }
  const mist=[...groupBy(list,t=>t.mistakes).entries()].map(([name,arr])=>({name,net:arr.reduce((a,t)=>a+netR(t),0),n:arr.length})).sort((a,b)=>a.net-b.net).slice(0,4);
  if(mist.length){
    cells+='<div class="cell"><div class="t">Mistakes</div>'+
      mist.map(m=>'<div class="row"><span class="k">'+esc(m.name)+' · '+m.n+'</span><span class="v '+clsR(m.net)+'">'+fmtR(m.net)+"</span></div>").join("")+"</div>";
  }
  return cells?'<div class="card"><h3>Лучшее / худшее</h3><div class="bw">'+cells+"</div></div>":"";
}


/* переходы из разбора месяца в журнал */
function gotoMonthFromReport(ym){
  closeModal(); S.jMonth=ym; S.jMode="cal";
  if(S.selDay.slice(0,7)!==ym) S.selDay=ym+"-01";
  location.hash="journal"; render();
}
function gotoDayFromReport(day){
  closeModal(); S.jMonth=day.slice(0,7); S.selDay=day; S.jMode="cal";
  location.hash="journal"; render();
}

/* ---------- подробный разбор месяца (из Yearly) ---------- */
function dimTable(list,key,label){
  const rows=[...groupBy(list,t=>fieldVal(t,key)).entries()]
    .map(([name,arr])=>({name,st:calc(arr)}))
    .sort((a,b)=>b.st.net-a.st.net);
  if(!rows.length) return "";
  const body=rows.map((g,i)=>{
    const flag = rows.length>1 ? (i===0?' <span class="tick best">лучший</span>':(i===rows.length-1?' <span class="tick worst">худший</span>':"")) : "";
    return "<tr><td>"+esc(g.name)+flag+"</td><td>"+g.st.n+"</td><td>"+fmtPct(g.st.wr)+
      '</td><td class="'+clsR(g.st.net)+'">'+fmtR(g.st.net)+"</td></tr>";
  }).join("");
  return '<div class="rep-card"><h4>'+esc(label)+'</h4><table class="simple mini">'+
    "<tr><th>"+esc(label)+"</th><th>Сд.</th><th>WR</th><th>Итог</th></tr>"+body+"</table></div>";
}
function openMonthReport(ym){
  S.mRep=ym;
  const [Y,M]=ym.split("-").map(Number);
  const list=S.trades.filter(t=>monKey(t)===ym);
  const st=calc(list);
  const title=MONTHS[M-1]+" "+Y;
  let h='<div class="m-head"><h2>'+title+' <span class="'+clsR(st.net)+'" style="font-family:var(--mono)">'+fmtR(st.net)+"</span></h2>"+
    '<button class="x" onclick="closeModal()">×</button></div><div class="m-body rep">';
  if(!list.length){ h+='<div class="empty">В этом месяце сделок не было</div>'; }
  else{
    h+=kpiHtml(st);
    h+='<div class="card"><h3>Динамика месяца</h3><div class="in">'+equitySVG(list)+"</div></div>";

    /* дни */
    const byDay=[...groupBy(list,dayKey).entries()].sort((a,b)=>a[0]<b[0]?-1:1)
      .map(([d,arr])=>({d,st:calc(arr)}));
    const best=byDay.slice().sort((a,b)=>b.st.net-a.st.net);
    h+='<div class="rep-sec">Дни</div><div class="rep-grid">'+
      '<div class="rep-card scrolly"><h4>Все торговые дни ('+byDay.length+")</h4>"+
      '<table class="simple mini"><tr><th>День</th><th>Сд.</th><th>WR</th><th>Итог</th></tr>'+
      byDay.map(x=>{
        const dt=new Date(x.d+"T00:00");
        return '<tr class="click" data-day="'+x.d+'" onclick="gotoDayFromReport(this.dataset.day)">'+
          "<td>"+dt.getDate()+" "+MONTHS[dt.getMonth()].slice(0,3).toLowerCase()+", "+WDS[(dt.getDay()+6)%7]+"</td>"+
          "<td>"+x.st.n+"</td><td>"+fmtPct(x.st.wr)+'</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div>"+
      '<div class="rep-card"><h4>Крайние дни</h4><table class="simple mini c3">'+
      '<tr><th>День</th><th>Сд.</th><th>Итог</th></tr>'+
      best.slice(0,3).concat(best.slice(-3).reverse()).filter((v,i,a)=>a.indexOf(v)===i).map(x=>{
        const dt=new Date(x.d+"T00:00");
        return "<tr><td>"+dt.getDate()+" "+MONTHS[dt.getMonth()].slice(0,3).toLowerCase()+"</td><td>"+x.st.n+
          '</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div></div>";

    /* разрезы */
    h+='<div class="rep-sec">Разрезы</div><div class="rep-grid">'+
      dimTable(list,"setup","Сетап")+dimTable(list,"pair","Актив")+
      dimTable(list,"session","Сессия")+dimTable(list,"entry_model","Модель входа")+
      dimTable(list,"direction_type","Продолжение / Разворот")+dimTable(list,"position","Направление")+
      "</div>";

    /* ошибки */
    const mist=[...groupBy(list,t=>t.mistakes).entries()].map(([name,arr])=>({name,st:calc(arr)}))
      .sort((a,b)=>a.st.net-b.st.net);
    const withM=list.filter(t=>(t.mistakes||"").trim()), noM=list.filter(t=>!(t.mistakes||"").trim());
    h+='<div class="rep-sec">Ошибки</div>';
    if(mist.length){
      h+='<div class="rep-grid"><div class="rep-card"><h4>Что стоило денег</h4><table class="simple mini">'+
        "<tr><th>Ошибка</th><th>Сд.</th><th>Итог</th></tr>"+
        mist.map(m=>"<tr><td>"+esc(m.name)+"</td><td>"+m.st.n+'</td><td class="'+clsR(m.st.net)+'">'+fmtR(m.st.net)+"</td></tr>").join("")+
        "</table></div>"+
        '<div class="rep-card"><h4>С ошибкой против без</h4><table class="simple mini">'+
        "<tr><th></th><th>Сд.</th><th>WR</th><th>Итог</th></tr>"+
        '<tr><td>С пометкой</td><td>'+withM.length+"</td><td>"+fmtPct(calc(withM).wr)+'</td><td class="'+clsR(calc(withM).net)+'">'+fmtR(calc(withM).net)+"</td></tr>"+
        '<tr><td>Без пометки</td><td>'+noM.length+"</td><td>"+fmtPct(calc(noM).wr)+'</td><td class="'+clsR(calc(noM).net)+'">'+fmtR(calc(noM).net)+"</td></tr>"+
        "</table></div></div>";
    } else h+='<div class="hint" style="padding:4px 0 12px">За месяц ошибок не отмечено.</div>';

    /* риск */
    const offSize=list.filter(t=>(t.risk||1)!==1), onSize=list.filter(t=>(t.risk||1)===1);
    if(offSize.length){
      h+='<div class="rep-sec">Размер риска</div><div class="rep-grid"><div class="rep-card"><h4>Отклонение от 1%</h4>'+
        '<table class="simple mini"><tr><th></th><th>Сд.</th><th>WR</th><th>Итог</th></tr>'+
        '<tr><td>Риск 1%</td><td>'+onSize.length+"</td><td>"+fmtPct(calc(onSize).wr)+'</td><td class="'+clsR(calc(onSize).net)+'">'+fmtR(calc(onSize).net)+"</td></tr>"+
        '<tr><td>Другой риск</td><td>'+offSize.length+"</td><td>"+fmtPct(calc(offSize).wr)+'</td><td class="'+clsR(calc(offSize).net)+'">'+fmtR(calc(offSize).net)+"</td></tr>"+
        "</table></div></div>";
    }
    h+='<div class="rep-sec">Безубытки</div>'+beReportHtml(list);
    h+='<div class="rep-sec">Все сделки месяца</div><div class="card"><div class="tlist">'+
      sortAsc(list).map(tradeRow).join("")+"</div></div>";
  }
  h+='</div><div class="m-foot"><button class="btn primary" data-ym="'+ym+'" onclick="closeModal();openShare(this.dataset.ym)">Картинка для канала</button>'+
    '<button class="btn" data-ym="'+ym+'" onclick="gotoMonthFromReport(this.dataset.ym)">Открыть в журнале</button>'+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">Закрыть</button></div>';
  openModal(h);
}

/* ---------- Quarterly ---------- */
function vQuarterly(){
  const Y=S.qYear;
  let h='<div class="vhead"><h1>Quarterly</h1><div class="right">'+
    '<button class="navbtn" onclick="S.qYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.qYear++;render()">›</button></div></div>';
  h+='<div class="qgrid">';
  for(let q=0;q<4;q++){
    const months=[q*3+1,q*3+2,q*3+3];
    const keys=months.map(m=>Y+"-"+pad(m));
    const list=S.trades.filter(t=>keys.includes(monKey(t)));
    const st=calc(list);
    const perMonth=months.map(m=>{
      const ml=S.trades.filter(t=>monKey(t)===Y+"-"+pad(m));
      return {m,label:MONTHS[m-1].slice(0,3),net:ml.reduce((a,t)=>a+netR(t),0),n:ml.length};
    });
    const withTrades=perMonth.filter(x=>x.n);
    let bw="";
    if(withTrades.length>1){
      const b=withTrades.reduce((a,c)=>c.net>a.net?c:a), w=withTrades.reduce((a,c)=>c.net<a.net?c:a);
      bw='<div class="qr"><span>Best month</span><b class="'+clsR(b.net)+'">'+b.label+" "+fmtR(b.net)+"</b></div>"+
         '<div class="qr"><span>Worst month</span><b class="'+clsR(w.net)+'">'+w.label+" "+fmtR(w.net)+"</b></div>";
    }
    const maxAbs=Math.max(0.001,...perMonth.map(x=>Math.abs(x.net)));
    const bars=perMonth.map(x=>{
      const wPct=Math.abs(x.net)/maxAbs*100;
      const color=x.net>0?"var(--up)":x.net<0?"var(--down)":"var(--line)";
      return '<div class="mbar"><span>'+x.label+'</span><span class="track"><i style="left:0;width:'+Math.max(x.n?4:0,wPct)+'%;background:'+color+'"></i></span><span class="val">'+(x.n?fmtR(x.net):"—")+"</span></div>";
    }).join("");
    h+='<div class="qcard"><h4>Q'+(q+1)+" "+Y+'<span class="netr '+clsR(st.net)+'">'+(st.n?fmtR(st.net):"—")+"</span></h4>"+
      '<div class="rows">'+
      '<div class="qr"><span>Trades</span><b>'+st.n+"</b></div>"+
      '<div class="qr"><span>Win Rate</span><b>'+fmtPct(st.wr)+"</b></div>"+
      '<div class="qr"><span>Ср. RR</span><b>'+(st.avgRR!=null?r1(st.avgRR):"—")+"</b></div>"+
      '<div class="qr"><span>Profit Factor</span><b>'+st.pfTxt+"</b></div>"+bw+
      '<div style="margin-top:8px">'+bars+"</div></div></div>";
  }
  return h+"</div>";
}

/* ---------- Yearly ---------- */
function vYearly(){
  const Y=S.yYear;
  const list=S.trades.filter(t=>(t.date||"").slice(0,4)==String(Y));
  const st=calc(list);
  let h='<div class="vhead"><h1>Yearly</h1><div class="right">'+
    '<button class="navbtn" onclick="S.yYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.yYear++;render()">›</button></div></div>';
  h+=kpiHtml(st);
  if(list.length) h+='<div class="card"><h3>Equity года · %</h3><div class="in">'+equitySVG(list)+"</div></div>";
  h+=beReportHtml(list);
  /* месяцы */
  let mrows="";
  for(let m=1;m<=12;m++){
    const ml=list.filter(t=>monKey(t)===Y+"-"+pad(m));
    if(!ml.length) continue;
    const ms=calc(ml);
    mrows+='<tr class="click" onclick="openMonthReport(\''+Y+"-"+pad(m)+'\')">'+
      "<td>"+MONTHS[m-1]+' <span class="go">разбор →</span></td><td>'+ms.n+"</td><td>"+fmtPct(ms.wr)+'</td><td class="'+clsR(ms.net)+'">'+fmtR(ms.net)+"</td><td>"+(ms.avgRR!=null?r1(ms.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>Months · клик по месяцу открывает разбор</h3><table class="simple"><tr><th>Month</th><th>Trades</th><th>Win Rate</th><th>Итог, %</th><th>Ср. RR</th></tr>'+
    (mrows||'<tr><td colspan="5" class="empty">Нет данных</td></tr>')+"</table></div>";
  /* кварталы */
  let qrows="";
  for(let q=0;q<4;q++){
    const keys=[1,2,3].map(i=>Y+"-"+pad(q*3+i));
    const ql=list.filter(t=>keys.includes(monKey(t)));
    if(!ql.length) continue;
    const qs=calc(ql);
    qrows+="<tr><td>Q"+(q+1)+"</td><td>"+qs.n+"</td><td>"+fmtPct(qs.wr)+'</td><td class="'+clsR(qs.net)+'">'+fmtR(qs.net)+"</td><td>"+(qs.avgRR!=null?r1(qs.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>Quarters</h3><table class="simple"><tr><th>Quarter</th><th>Trades</th><th>Win Rate</th><th>Итог, %</th><th>Ср. RR</th></tr>'+
    (qrows||'<tr><td colspan="5" class="empty">Нет данных</td></tr>')+"</table></div>";
  return h;
}

/* ---------- Analytics ---------- */
function vAnalytics(){
  const list=applyFilters(S.trades);
  let h='<div class="vhead"><h1>Analytics</h1><span class="sub">'+list.length+" сделок в выборке</span></div>";
  h+=filterBar();
  h+='<div class="dims">'+DIMS.map(d=>'<button class="pill '+(S.dim===d.k?"on":"")+'" onclick="S.dim=\''+d.k+'\';render()">'+d.label+"</button>").join("")+"</div>";
  const groups=[...groupBy(list,t=>S.dim==="result"?resLabel(t.result):fieldVal(t,S.dim)).entries()].map(([name,arr])=>{
    const st=calc(arr); return {name,st};
  }).sort((a,b)=>b.st.net-a.st.net);
  const rows=groups.map(g=>{
    const wr=g.st.wr;
    return '<div class="arow"><span class="nm">'+esc(g.name)+'</span><span class="n">'+g.st.n+"</span>"+
      '<span class="wrbar"><span class="track"><i style="width:'+(wr||0)+'%"></i></span><b>'+fmtPct(wr)+"</b></span>"+
      '<span class="rr">'+(g.st.avgRR!=null?r1(g.st.avgRR):"—")+"</span>"+
      '<span class="netr '+clsR(g.st.net)+'">'+fmtR(g.st.net)+"</span></div>";
  }).join("");
  h+='<div class="card"><h3>'+esc(DIMS.find(d=>d.k===S.dim).label)+" Performance</h3>"+
    '<div class="ahead"><span>Название</span><span>Trades</span><span>Win Rate</span><span>Ср. RR</span><span>Итог, %</span></div>'+
    (rows||'<div class="empty">Нет данных — поле не заполнено ни в одной сделке</div>')+"</div>";
  return h;
}

/* ================= МОДАЛКИ ================= */
function openModal(html){ $("#modalBox").innerHTML=html; $("#modal").hidden=false; document.body.style.overflow="hidden"; }
function closeModal(){ $("#modal").hidden=true; document.body.style.overflow=""; S.formShots=[]; document.removeEventListener("paste", onPasteShot); }

/* ---------- тема ---------- */
function toggleTheme(){
  const dark = document.documentElement.getAttribute("data-theme")==="dark";
  if(dark) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme","dark");
  try{ dark?localStorage.removeItem("tj_theme"):localStorage.setItem("tj_theme","dark"); }catch(e){}
  markTheme();
}
function markTheme(){
  const b=$("#themeBtn"); if(!b) return;
  const dark = document.documentElement.getAttribute("data-theme")==="dark";
  b.innerHTML = (dark ? "☀" : "☾") + "<span>" + (dark ? "Светлая тема" : "Тёмная тема") + "</span>";
  b.title = dark ? "Переключить на светлую" : "Переключить на тёмную";
}

$("#modal") && null;

function openLightbox(src){ $("#lightboxImg").src=src; $("#lightbox").hidden=false; }
function closeLightbox(){ $("#lightbox").hidden=true; $("#lightboxImg").src=""; }

/* ---------- просмотр сделки ---------- */
function openTrade(id){
  const t=(S.all.length?S.all:S.trades).find(x=>x.id===id); if(!t) return;
  const r=netR(t);
  const fields=[["Pair",t.pair],["Date",(t.date||"").replace("T"," ")],["Session",t.session],["Position",t.position],
    ["Entry Model",t.entry_model],["Bias",t.bias],["Setup",t.setup],["Cont / Rev",dirType(t)],
    ["Result",resLabel(t.result)],["RR",t.rr!=null?t.rr:""],["Risk",t.risk!=null?t.risk+"%":""],["Итог",fmtR(r)]];
  let h='<div class="m-head"><h2>'+esc(t.pair||"Trade")+' <span class="'+clsR(r)+'" style="font-family:var(--mono)">'+fmtR(r)+"</span></h2>"+
    '<button class="x" onclick="closeModal()">×</button></div><div class="m-body">';
  h+='<div class="dgrid">'+fields.filter(f=>f[1]!==""&&f[1]!=null).map(f=>
    '<div class="f2"><div class="l">'+f[0]+'</div><div class="v">'+esc(f[1])+"</div></div>").join("")+"</div>";
  for(const [label,key] of [["Entry Details","entry_details"],["Notes","notes"],["Mistakes","mistakes"],["Comments","comments"]]){
    if((t[key]||"").trim()) h+='<div class="dtext"><div class="l">'+label+'</div><div class="v">'+esc(t[key])+"</div></div>";
  }
  const shots=(t.screenshots||[]).slice().sort((a,b)=>TF_ORDER.indexOf(a.tf)-TF_ORDER.indexOf(b.tf));
  if(shots.length){
    h+='<div class="dtext"><div class="l">Charts · '+shots.map(s=>esc(s.tf||"")).join(" | ")+"</div></div>";
    h+='<div class="charts">'+shots.map(s=>
      '<div class="chart-item"><div class="l">'+esc(s.tf||"chart")+'</div><img loading="lazy" src="'+shotSrc(s)+'" onclick="openLightbox(this.src)"></div>').join("")+"</div>";
  }
  h+='</div><div class="m-foot"><button class="btn" onclick="openForm(\''+t.id+'\')">Изменить</button>'+
    '<button class="btn danger" onclick="delTrade(\''+t.id+'\')">Удалить</button><span class="sp"></span>'+
    '<button class="btn" onclick="closeModal()">Закрыть</button></div>';
  openModal(h);
}
async function delTrade(id){
  if(!confirm("Удалить сделку? Статистика пересчитается.")) return;
  await api("DELETE","/api/trades/"+id);
  await reload(); closeModal(); render();
}

/* ---------- форма сделки ---------- */
function dl(id,vals){ return '<datalist id="'+id+'">'+vals.map(v=>'<option value="'+esc(v)+'">').join("")+"</datalist>"; }

function openForm(id, presetDay){
  const t=id?(S.all.length?S.all:S.trades).find(x=>x.id===id):null;
  S.formShots=(t&&t.screenshots?t.screenshots.map(s=>({tf:s.tf,file:s.file})):[]);
  const v=k=>esc(t?(t[k]!=null?t[k]:""):"");
  const nowT=pad(new Date().getHours())+":"+pad(new Date().getMinutes());
  const dt=t&&t.date?t.date:(presetDay||isoDay(new Date()))+"T"+nowT;
  S.activeTf=null; S.dirTouched=!!(t&&(t.direction_type||"").trim());

  /* переключатель из кнопок */
  const seg=(field,options,cur,cls)=>
    '<div class="seg '+(cls||"")+'" id="seg_'+field+'">'+options.map(o=>
      '<button type="button" class="'+(cur===o.v?("on "+(o.cls||"")):"")+'" data-v="'+o.v+
      '" data-cls="'+(o.cls||"")+'" onclick="segPick(\''+field+'\',this)">'+o.t+"</button>").join("")+
    '</div><input type="hidden" id="fld_'+field+'" value="'+esc(cur||"")+'">';

  /* подсказки + скрытое поле: своё значение открывается кнопкой «＋» */
  const pick=(field,vals,cur,ph,num)=>{
    cur=(cur||"").toString();
    const known=vals.some(x=>String(x)===cur);
    const chips=vals.map(x=>
      '<button type="button" data-f="'+field+'" data-v="'+esc(x)+'"'+
      (String(x)===cur?' class="on"':"")+' onclick="quickSet(this)">'+esc(x)+"</button>").join("");
    return '<div class="quick">'+chips+
      '<button type="button" class="more" onclick="showOwn(\''+field+'\')" title="Своё значение">＋</button></div>'+
      '<input class="qinput" id="fld_'+field+'"'+(num?' type="number" step="0.25" min="0"':"")+
      ' value="'+esc(cur)+'" placeholder="'+esc(ph||"")+'" autocomplete="off"'+
      (cur&&!known?"":" hidden")+' oninput="markQuick();calcOutcome()">';
  };

  const models=[...new Set(["cisd",...topVals("entry_model",4)])];
  const setups=topVals("setup",4);
  const mistakes=topVals("mistakes",5);

  let h='<div class="m-head"><h2>'+(t?"Изменить сделку":"Новая сделка")+
    '</h2><button class="x" onclick="closeModal()">×</button></div>';

  h+='<div class="m-body form">'+

  /* ---- сделка ---- */
  '<section class="fcard"><h4>Сделка</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>Инструмент <i>*</i></label>'+
        pick("pair",PAIRS_ACTIVE,t?t.pair:"","свой инструмент")+"</div>"+
      '<div class="f"><label>Дата и время <i>*</i></label>'+
        '<input id="fld_date" type="datetime-local" value="'+esc(dt)+'"></div>'+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>Сессия</label>'+
        pick("session",SESSIONS,t?t.session:"","своя сессия")+"</div>"+
      '<div class="f"><label>Направление сделки</label>'+
        seg("position",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.position:"","big")+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- контекст ---- */
  '<section class="fcard"><h4>Контекст</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>Биас дня</label>'+
        seg("bias",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.bias:"","big")+"</div>"+
      '<div class="f"><label>Тип входа <span class="autotag" id="dirTag">подставится сам</span></label>'+
        seg("direction_type",[{v:"Continuation",t:"Продолжение",cls:"cont"},
                              {v:"Reversal",t:"Разворот",cls:"rev"}],t?dirType(t):"","big")+"</div>"+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>Модель входа</label>'+
        pick("entry_model",models,t?t.entry_model:"","своя модель")+"</div>"+
      '<div class="f"><label>Сетап</label>'+
        pick("setup",setups,t?t.setup:"","свой сетап")+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- результат ---- */
  '<section class="fcard accent"><h4>Результат</h4><div class="fbody">'+
    '<div class="f"><label>Чем закончилась <i>*</i></label>'+
      seg("result",[{v:"Win",t:"TP",cls:"win"},{v:"Loss",t:"SL",cls:"loss"},
                    {v:"BE-",t:"BE\u2212",cls:"bek"},{v:"BE+",t:"BE+",cls:"bepk"}],t?t.result:"","big res")+"</div>"+
    '<div class="frow">'+
      '<div class="f"><label>RR — во сколько раз цель дальше стопа</label>'+
        '<input id="fld_rr" type="number" step="0.1" min="0" placeholder="2.5" oninput="calcOutcome()" value="'+(t&&t.rr!=null?t.rr:"")+'"></div>'+
      '<div class="f"><label>Риск, % от депозита</label>'+
        pick("risk",["0.5","1","1.5","2"],(t&&t.risk!=null?String(t.risk):"1"),"свой риск",true)+"</div>"+
    "</div>"+
    '<div class="outcome" id="outcome"></div>'+
  "</div></section>"+

  /* ---- скриншоты ---- */
  '<section class="fcard"><h4>Скриншоты по таймфреймам</h4><div class="fbody">'+
    '<div class="tfgrid" id="shotsEdit"></div>'+
    '<input id="shotFile" type="file" accept="image/*" multiple hidden>'+
  "</div></section>"+

  /* ---- заметки ---- */
  '<section class="fcard"><h4>Заметки</h4><div class="fbody">'+
    '<div class="f"><label>Как заходил</label><textarea id="fld_entry_details" placeholder="тест 4ч имб, 1м цисд, цель 15м фрактал">'+v("entry_details")+"</textarea></div>"+
    '<div class="f"><label>Мысли по сделке</label><textarea id="fld_notes" class="short">'+v("notes")+"</textarea></div>"+
    '<div class="f"><label>Ошибка, если была</label>'+
      '<div class="quick">'+mistakes.map(x=>
        '<button type="button" data-f="mistakes" data-v="'+esc(x)+'" onclick="quickSet(this)">'+esc(x)+"</button>").join("")+"</div>"+
      '<input id="fld_mistakes" value="'+v("mistakes")+'" placeholder="пусто, если ошибок нет" autocomplete="off" oninput="markQuick()"></div>'+
  "</div></section>"+

  "</div>";

  h+='<div class="m-foot">'+
    (t?'<button class="btn danger" onclick="delTrade(\''+t.id+'\')">Удалить</button>':"")+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">Отмена</button>'+
    '<button class="btn primary" onclick="saveTrade(\''+(t?t.id:"")+'\')">Сохранить</button></div>';

  openModal(h);
  renderShots();
  markQuick(); autoDirType(); calcOutcome();
  $("#shotFile").addEventListener("change", onShotFiles);
  document.addEventListener("paste", onPasteShot);
  if(!t) setTimeout(()=>{ const el=$("#fld_pair"); if(el) el.focus(); },60);
}

/* подстановка значения по клику на подсказку */
function quickSet(btn){
  const el=$("#fld_"+btn.dataset.f);
  if(!el) return;
  el.value = (el.value.trim()===btn.dataset.v) ? "" : btn.dataset.v;
  markQuick(); calcOutcome();
}
function showOwn(field){
  const el=$("#fld_"+field); if(!el) return;
  el.hidden=false; el.focus();
  document.querySelectorAll('.quick button[data-f="'+field+'"]').forEach(b=>b.classList.remove("on"));
  el.value=""; calcOutcome();
}
function markQuick(){
  document.querySelectorAll(".quick button").forEach(b=>{
    const el=$("#fld_"+b.dataset.f);
    b.classList.toggle("on", !!el && el.value.trim()===b.dataset.v);
  });
}

/* живой пересчёт: что сделка даст в процентах */
function calcOutcome(){
  const box=$("#outcome"); if(!box) return;
  const res=($("#fld_result")||{}).value||"";
  const rr=parseFloat(($("#fld_rr")||{}).value)||0;
  const risk=parseFloat(($("#fld_risk")||{}).value);
  const r=isNaN(risk)?1:risk;
  markQuick();
  if(!res){ box.className="outcome"; box.innerHTML='<span class="hint">Выбери результат — покажу, сколько это в процентах</span>'; return; }
  let val=0, txt="";
  if(res==="Win"){ val=r*rr; txt="Тейк при риске "+r1(r)+"% и RR "+r1(rr); }
  else if(res==="Loss"){ val=-r; txt="Стоп забирает риск целиком"; }
  else { val=0; txt = res==="BE+" ? "Безубыток, но цена дошла бы до цели" : "Безубыток, дальше пошло против"; }
  box.className="outcome "+(val>0.0001?"pos":val<-0.0001?"neg":"be");
  box.innerHTML='<span class="big">'+fmtR(val)+'</span><span class="txt">'+txt+"</span>";
}


/* Position + Bias -> Continuation / Reversal подставляется само */
function autoDirType(){
  if(S.dirTouched) return;                 /* выбрал руками — не перебиваем */
  const p=($("#fld_position")||{}).value||"", b=($("#fld_bias")||{}).value||"";
  const inp=$("#fld_direction_type"), seg=$("#seg_direction_type");
  if(!inp||!seg) return;
  const val = (p&&b) ? (p===b?"Continuation":"Reversal") : "";
  inp.value=val;
  seg.querySelectorAll("button").forEach(b2=>{
    const on = !!val && b2.dataset.v===val;
    b2.classList.toggle("on",on);
    if(b2.dataset.cls) b2.classList.toggle(b2.dataset.cls,on);
  });
  const tag=$("#dirTag");
  if(tag) tag.textContent = val ? "подставлено само" : "подставится сам";
}

/* вставка скрина из буфера обмена */
function onPasteShot(e){
  if($("#modal").hidden || !$("#shotsEdit")) return;
  const items=[...(e.clipboardData||{}).items||[]].filter(i=>i.type.startsWith("image/"));
  if(!items.length) return;
  e.preventDefault();
  items.forEach((it,idx)=>{
    const f=it.getAsFile();
    if(f) resizeImage(f).then(dataUrl=>{
      const tf = idx===0 && S.activeTf ? S.activeTf : firstEmptyTf();
      putShot(tf,dataUrl,"из буфера");
      if(idx===0) S.activeTf=null;
    });
  });
}

/* выбор варианта в переключателе */
function segPick(field,btn){
  const seg=btn.parentElement; const inp=$("#fld_"+field);
  const was=btn.classList.contains("on");
  seg.querySelectorAll("button").forEach(b=>b.classList.remove("on","win","loss","bek","bepk","lng","shr"));
  if(was){ inp.value=""; }
  else{
    btn.classList.add("on"); if(btn.dataset.cls)btn.classList.add(btn.dataset.cls);
    inp.value=btn.dataset.v;
  }
  if(field==="direction_type"){ S.dirTouched=true; const tag=$("#dirTag"); if(tag) tag.textContent="выбрано вручную"; }
  if(field==="position"||field==="bias") autoDirType();
  if(field==="result") calcOutcome();
}

/* слоты скриншотов по таймфреймам */
function renderShots(){
  const box=$("#shotsEdit"); if(!box) return;
  const used=new Set();
  const filledTile=(s,i,label)=>{
    const src=shotSrc(s);
    return '<div class="tfslot filled"><div class="tfl"><span>'+esc(label)+'</span>'+
      '<button type="button" class="rm" title="Убрать" onclick="removeShot('+i+')">×</button></div>'+
      '<img src="'+src+'" onclick="openLightbox(this.src)"></div>';
  };
  let h="";
  for(const tf of TF_SLOTS){
    const i=S.formShots.findIndex((s,idx)=>s.tf===tf && !used.has(idx));
    if(i>=0){ used.add(i); h+=filledTile(S.formShots[i],i,tf); }
    else{
      const on=S.activeTf===tf;
      h+='<div class="tfslot'+(on?" active":"")+'" data-tf="'+tf+'" onclick="armSlot(this.dataset.tf)">'+
        '<div class="tfl"><span>'+tf+'</span>'+
        '<button type="button" class="pick" title="Выбрать файл" data-tf="'+tf+
        '" onclick="event.stopPropagation();pickFor(this.dataset.tf)">файл</button></div>'+
        '<div class="drop">'+(on?'<span class="ready">Ctrl+V</span>':"+")+'</div></div>';
    }
  }
  S.formShots.forEach((s,i)=>{ if(!used.has(i)) h+=filledTile(s,i,s.tf||"?"); });
  h+='<div class="tfhint">Скопируй график в TradingView (<b>Ctrl+Alt+S</b>) → кликни нужный таймфрейм → <b>Ctrl+V</b>. Сохранять картинку на компьютер не нужно.</div>';
  box.innerHTML=h;
}
function removeShot(i){ S.formShots.splice(i,1); renderShots(); }

/* клик по слоту только выделяет его: диалог файла забирал фокус и Ctrl+V уходил мимо */
function armSlot(tf){ S.activeTf=(S.activeTf===tf?null:tf); renderShots(); }
function pickFor(tf){ S.activeTf=tf; renderShots(); $("#shotFile").click(); }
function putShot(tf,dataUrl,name){
  const i=S.formShots.findIndex(s=>s.tf===tf);
  if(i>=0) S.formShots[i]={tf,data:dataUrl,name};   // замена в занятом слоте
  else S.formShots.push({tf,data:dataUrl,name});
  renderShots();
}
function firstEmptyTf(){ return TF_SLOTS.find(tf=>!S.formShots.some(s=>s.tf===tf))||"15m"; }
function guessTf(name){
  const n=(name||"").toLowerCase();
  for(const tf of TF_ORDER){ if(n.includes(tf.toLowerCase()) && !S.formShots.some(s=>s.tf===tf)) return tf; }
  return null;
}
function onShotFiles(e){
  const files=[...e.target.files]; e.target.value="";
  files.forEach((f,idx)=>{
    resizeImage(f).then(dataUrl=>{
      let tf = idx===0 && S.activeTf ? S.activeTf : (guessTf(f.name)||firstEmptyTf());
      putShot(tf,dataUrl,f.name);
      if(idx===0) S.activeTf=null;
    });
  });
}
/* большие скрины ужимаем до 1600px по ширине, чтобы журнал не разбухал */
function resizeImage(file){
  return new Promise(res=>{
    const img=new Image();
    img.onload=()=>{
      const MAX=1600;
      if(img.width<=MAX && file.size<900*1024){ // маленькие не трогаем
        const fr=new FileReader(); fr.onload=()=>res(fr.result); fr.readAsDataURL(file); return;
      }
      const k=Math.min(1,MAX/img.width);
      const c=document.createElement("canvas");
      c.width=Math.round(img.width*k); c.height=Math.round(img.height*k);
      c.getContext("2d").drawImage(img,0,0,c.width,c.height);
      res(c.toDataURL("image/jpeg",0.88));
    };
    img.onerror=()=>{ const fr=new FileReader(); fr.onload=()=>res(fr.result); fr.readAsDataURL(file); };
    img.src=URL.createObjectURL(file);
  });
}
async function saveTrade(id){
  const g=k=>{ const el=$("#fld_"+k); return el?el.value.trim():""; };
  const t={
    pair:g("pair"), date:g("date"), session:g("session"), position:g("position"),
    entry_model:g("entry_model"), bias:g("bias"), setup:g("setup"),
    direction_type:g("direction_type"), result:g("result"),
    rr:g("rr"), risk:g("risk"),
    entry_details:g("entry_details"), notes:g("notes"), mistakes:g("mistakes"), comments:"",
    screenshots:S.formShots,
  };
  if(!t.pair){ alert("Укажи Pair"); return; }
  if(!t.date){ alert("Укажи дату"); return; }
  if(!t.result){ alert("Укажи Result — TP / SL / BE\u2212 / BE+"); return; }
  if(t.result==="Win" && !num(t.rr)){ alert("Для TP нужен RR — иначе результат посчитается как 0R"); return; }
  const btn=document.querySelector(".m-foot .primary"); if(btn){btn.disabled=true;btn.textContent="Сохраняю…";}
  try{
    if(id) await api("PUT","/api/trades/"+id,t);
    else   await api("POST","/api/trades",t);
    await reload(); closeModal(); render();
  }catch(err){ alert("Не сохранилось: "+err.message); if(btn){btn.disabled=false;btn.textContent="Сохранить";} }
}

/* ---------- импорт / экспорт ---------- */
const IMP={rows:[],headers:[],map:{}};
const IMP_FIELDS=[["pair","Pair"],["date","Date"],["session","Session"],["position","Position"],
  ["entry_model","Entry Model"],["bias","Bias"],["setup","Setup"],["direction_type","Cont/Rev"],
  ["result","Result"],["rr","RR"],["risk","Risk"],["entry_details","Entry Details"],["notes","Notes"],["mistakes","Mistakes"]];

function openImport(){
  let h='<div class="m-head"><h2>Импорт сделок</h2><button class="x" onclick="closeModal()">×</button></div>'+
  '<div class="m-body">'+
  '<p class="hint">Подходит файл <b>JSON</b> (массив сделок) или <b>CSV</b> (первая строка — заголовки). '+
  'После загрузки сопоставь колонки с полями журнала — совпадающие названия подставятся сами.</p>'+
  '<input id="impFile" type="file" accept=".json,.csv,.txt" style="margin:12px 0">'+
  '<div id="impMap"></div></div>'+
  '<div class="m-foot"><span class="sp"></span><button class="btn" onclick="closeModal()">Отмена</button>'+
  '<button class="btn primary" id="impGo" disabled onclick="doImport()">Импортировать</button></div>';
  openModal(h);
  $("#impFile").addEventListener("change", onImpFile);
}
function onImpFile(e){
  const f=e.target.files[0]; if(!f) return;
  const fr=new FileReader();
  fr.onload=()=>{
    const text=fr.result;
    try{
      if(f.name.toLowerCase().endsWith(".json") || text.trim().startsWith("[")){
        const arr=JSON.parse(text);
        IMP.rows=Array.isArray(arr)?arr:(arr.trades||[]);
        IMP.headers=[...new Set(IMP.rows.flatMap(r=>Object.keys(r)))];
      }else{
        const rows=parseCSV(text);
        IMP.headers=rows[0]||[];
        IMP.rows=rows.slice(1).filter(r=>r.some(c=>c&&c.trim())).map(r=>{
          const o={}; IMP.headers.forEach((hd,i)=>o[hd]=r[i]); return o;
        });
      }
    }catch(err){ $("#impMap").innerHTML='<p class="neg">Не смог разобрать файл: '+esc(err.message)+"</p>"; return; }
    buildMap();
  };
  fr.readAsText(f,"utf-8");
}
function guessHeader(field,headers){
  const aliases={pair:["pair","актив","symbol","ticker"],date:["date","дата","time"],session:["session","сессия"],
    position:["position","позиция","direction","напр"],entry_model:["entry model","entry_model","model","модель"],
    bias:["bias","биас"],setup:["setup","сетап","setups"],direction_type:["continuation","direction type","direction_type","cont","c/r"],
    result:["result","результат","итог"],rr:["rr","r:r","risk reward"],risk:["risk","риск"],
    entry_details:["entry details","entry_details","details","вход"],notes:["note","notes","заметк","комментар"],mistakes:["mistake","ошибк"]};
  const list=aliases[field]||[field];
  for(const hd of headers){ const l=hd.toLowerCase().trim();
    if(list.some(a=>l===a)) return hd; }
  for(const hd of headers){ const l=hd.toLowerCase().trim();
    if(list.some(a=>l.includes(a))) return hd; }
  return "";
}
function buildMap(){
  IMP.map={};
  let h='<p class="hint">Найдено строк: <b style="color:var(--text)">'+IMP.rows.length+"</b></p>"+
    '<div class="map-grid">';
  for(const [f,label] of IMP_FIELDS){
    const guess=guessHeader(f,IMP.headers); IMP.map[f]=guess;
    h+='<span class="k">'+label+'</span><select onchange="IMP.map[\''+f+'\']=this.value">'+
      '<option value="">— пропустить —</option>'+
      IMP.headers.map(hd=>'<option '+(hd===guess?"selected":"")+' value="'+esc(hd)+'">'+esc(hd)+"</option>").join("")+"</select>";
  }
  h+="</div>";
  $("#impMap").innerHTML=h;
  $("#impGo").disabled=!IMP.rows.length;
}
function normResult(v){
  const s=(v||"").toString().trim().toLowerCase();
  if(["win","tp","w","профит","+","take"].some(x=>s===x||s.startsWith(x+" ")||s===x)) return "Win";
  if(s.startsWith("tp")||s==="win") return "Win";
  if(s.startsWith("sl")||s==="loss"||s==="lose"||s==="l") return "Loss";
  if(s.startsWith("be")||s.includes("безуб")||s==="0") return "BE";
  if(s==="sk") return "BE";
  return v?"BE":"";
}
function normPos(v){
  const s=(v||"").toString().trim().toLowerCase();
  if(s.startsWith("long")||s==="l"||s.includes("лонг")) return "Long";
  if(s.startsWith("short")||s==="s"||s.includes("шорт")) return "Short";
  return "";
}
function normDate(v){
  if(!v) return "";
  const s=v.toString().trim();
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})[T ]?(\d{2}):?(\d{2})?/);
  if(m) return m[1]+"-"+m[2]+"-"+m[3]+"T"+(m[4]||"00")+":"+(m[5]||"00");
  m=s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if(m) return m[1]+"-"+m[2]+"-"+m[3]+"T00:00";
  m=s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ T](\d{1,2}):(\d{2}))?/);
  if(m) return m[3]+"-"+pad(+m[2])+"-"+pad(+m[1])+"T"+(m[4]?pad(+m[4]):"00")+":"+(m[5]||"00");
  const d=new Date(s);
  return isNaN(d)?"":isoDay(d)+"T"+pad(d.getHours())+":"+pad(d.getMinutes());
}
async function doImport(){
  const out=[];
  for(const row of IMP.rows){
    const g=f=>IMP.map[f]?row[IMP.map[f]]:"";
    const date=normDate(g("date"));
    const result=normResult(g("result"));
    if(!date && !g("pair")) continue;
    out.push({
      pair:(g("pair")||"").toString().trim(), date, session:(g("session")||"").toString().trim(),
      position:normPos(g("position")), entry_model:(g("entry_model")||"").toString().trim(),
      bias:normPos(g("bias")), setup:(g("setup")||"").toString().trim(),
      direction_type:(g("direction_type")||"").toString().trim(), result,
      rr:(g("rr")||"").toString().replace(",","."), risk:(g("risk")||"").toString().replace("%","").replace(",","."),
      entry_details:(g("entry_details")||"").toString(), notes:(g("notes")||"").toString(),
      mistakes:(g("mistakes")||"").toString(), screenshots:[],
    });
  }
  if(!out.length){ alert("Нечего импортировать"); return; }
  const btn=$("#impGo"); btn.disabled=true; btn.textContent="Импортирую…";
  const res=await api("POST","/api/import",out);
  await reload(); closeModal(); render();
  alert("Импортировано сделок: "+res.added);
}
function parseCSV(text){
  const rows=[]; let row=[],cur="",q=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(q){ if(c==='"'){ if(text[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=c; }
    else if(c==='"') q=true;
    else if(c===","||c===";"){ row.push(cur);cur=""; }
    else if(c==="\n"||c==="\r"){ if(c==="\r"&&text[i+1]==="\n")i++; row.push(cur);cur=""; if(row.length>1||row[0]!=="")rows.push(row); row=[]; }
    else cur+=c;
  }
  if(cur!==""||row.length){row.push(cur);rows.push(row);}
  return rows;
}
async function exportData(){
  const data=await api("GET","/api/trades");
  const blob=new Blob([JSON.stringify(data,null,1)],{type:"application/json"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download="trading-journal-"+isoDay(new Date())+".json";
  a.click();
}

/* ================= рендер ================= */
const VIEWS={dashboard:vDashboard,journal:vJournal,monthly:vJournal,quarterly:vQuarterly,yearly:vYearly,analytics:vAnalytics};
function render(){
  const v=VIEWS[S.view]?S.view:"dashboard";
  document.querySelectorAll(".nav a").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
  $("#main").innerHTML='<div class="page">'+VIEWS[v]()+"</div>";
}
window.addEventListener("hashchange",()=>{ S.view=location.hash.slice(1)||"dashboard"; render(); });
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ if(!$("#lightbox").hidden)closeLightbox(); else if(!$("#modal").hidden)closeModal(); }
});
$("#modal").addEventListener("click",e=>{ if(e.target.id==="modal")closeModal(); });

function markDemo(){
  const b=document.createElement("div");
  b.className="demo-badge";
  b.innerHTML='<b>Демо</b><span>Сделки хранятся только в вашем браузере</span>'+
              '<button type="button" onclick="DemoStore.reset()">Сбросить</button>';
  document.body.appendChild(b);
}

(async function init(){
  markTheme();
  try{
    await reload();
  }catch(e){
    /* сервера нет — значит это публичное демо, работаем на данных в браузере */
    try{
      await DemoStore.init();
      DEMO=true;
      await reload();
      markDemo();
    }catch(e2){
      $("#main").innerHTML='<div class="empty">Сервер не отвечает. Запусти app.py</div>';
      return;
    }
  }
  S.view=location.hash.slice(1)||"dashboard";
  if(S.view==="monthly"){ S.view="journal"; location.hash="journal"; }
  render();
})();
