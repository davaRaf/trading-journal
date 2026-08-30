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
  all: [], mRep:null, ovPeriod:"month",
  pages:{},                     // номер страницы для каждого списка сделок
  selTrade:null,                // сделка, открытая во второй панели журнала
};

const MONTHS = ["Січень","Лютий","Березень","Квітень","Травень","Червень","Липень","Серпень","Вересень","Жовтень","Листопад","Грудень"];
const WDS = ["Пн","Вт","Ср","Чт","Пт","Сб","Нд"];
const MON_SHORT = ["січ","лют","бер","кві","тра","чер","лип","сер","вер","жов","лис","гру"];
/* родовий відмінок — для дат виду «30 серпня» */
const MONTHS_GEN = ["січня","лютого","березня","квітня","травня","червня","липня","серпня","вересня","жовтня","листопада","грудня"];
const TF_LIST = ["1m","3m","5m","15m","30m","1H","4H","1D","1W"];
const TF_SLOTS = ["1m","3m","5m","15m","30m","1H","4H"];
const TF_ORDER = ["1W","1D","4H","1H","30m","15m","5m","3m","1m"];
const SESSIONS = ["LONDON","NY","FRANKFURT","PH","PM"];
/* активы для подсказок в форме. Старые инструменты (форекс, золото) остаются
   в статистике полностью, но новую сделку по ним не предлагаем. */
const PAIRS_ACTIVE = ["US100","GER40","ES500"];
const DIMS = [
  {k:"pair",label:"Інструмент"},{k:"session",label:"Сесія"},{k:"position",label:"Напрямок"},
  {k:"entry_model",label:"Модель входу"},{k:"bias",label:"Біас"},{k:"setup",label:"Сетап"},
  {k:"direction_type",label:"Продовження / Розворот"},{k:"result",label:"TP / SL / BE"},{k:"mistakes",label:"Помилки"},
];

/* короткие пояснения к показателям — всплывают при наведении */
const TIPS = {
  "Угод":"Скільки угод потрапило у вибірку",
  "Win Rate":"Частка прибуткових угод: TP до всіх закритих",
  "Підсумок, %":"Сумарний результат у відсотках від депозиту",
  "Середній RR":"Середнє відношення цілі до стопа",
  "Profit Factor":"Сума прибутків поділена на суму збитків. Більше 1 — плюс",
  "TP / SL / BE":"Скільки угод дійшло до цілі, до стопа, у беззбиток",
  "BE− / BE+":"Беззбиток, після якого ціна пішла проти / дійшла б до цілі",
  "Середній ризик":"Середній ризик на угоду, % від депозиту",
};

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
    ["Угод", st.n, ""],
    ["Win Rate", fmtPct(st.wr), ""],
    ["Підсумок, %", fmtR(st.net), clsR(st.net)],
    ["Середній RR", st.avgRR!=null?r1(st.avgRR):"—", ""],
    ["Profit Factor", st.pfTxt, ""],
    ["TP / SL / BE", st.wins+" / "+st.losses+" / "+st.be, "small"],
    ["BE\u2212 / BE+", st.beM+" / "+st.beP, "small"],
  ];
  if(!opts.compact) cells.push(["Середній ризик", st.avgRisk!=null?r1(st.avgRisk)+"%":"—",""]);
  return '<div class="kpis">'+cells.map(c=>
    '<div class="kpi"'+(TIPS[c[0]]?' data-tip="'+esc(TIPS[c[0]])+'"':"")+
    '><div class="l">'+c[0]+'</div><div class="v '+c[2]+'">'+c[1]+'</div></div>').join("")+"</div>";
}

/* ---------------- график equity ---------------- */
function equitySVG(list){
  const arr=sortAsc(list);
  if(arr.length<2) return '<div class="empty">Замало угод для графіка</div>';
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
    '<span class="eqrange">макс '+fmtR(eq[hiI])+" · мін "+fmtR(eq[loI])+"</span>"+
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
  return '<div class="trow'+(S.selTrade===t.id?" on":"")+'" onclick="openTradeRow(\''+t.id+'\')">'+
    '<span class="d">'+esc(d)+'</span><span class="p">'+esc(t.pair||"—")+" "+pos+"</span>"+
    '<span class="info">'+info+"</span>"+dtb+badge+
    '<span class="r '+clsR(r)+'">'+fmtR(r)+"</span></div>";
}
/* длинный список идёт страницами: сами строки те же, добавилась только навигация */
function tradesCard(list,title,key){
  key=key||title;
  const pg=Pagi.slice(list,key);
  const rows=pg.items.length?pg.items.map(tradeRow).join(""):'<div class="empty">Угод немає</div>';
  return '<div class="card" data-pagi="'+esc(key)+'"><h3>'+esc(title)+'</h3><div class="tlist">'+rows+"</div>"+
    Pagi.html(key,pg.page,pg.pages)+"</div>";
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
        if(t.result==="Win")  return '<i class="mk tp'+(rv?" rev":"")+'" data-tip="Тейк-профіт'+(rv?" · вхід проти біасу":"")+'">TP</i>';
        if(t.result==="Loss") return '<i class="mk sl'+(rv?" rev":"")+'" data-tip="Стоп-лос'+(rv?" · вхід проти біасу":"")+'">SL</i>';
        if(t.result==="BE+")  return '<i class="mk beplus'+(rv?" rev":"")+'" data-tip="Беззбиток, потім ціна дійшла б до цілі">BE+</i>';
        return '<i class="mk be'+(rv?" rev":"")+'" data-tip="Беззбиток, потім ціна пішла проти">BE\u2212</i>';
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
  const selects=[["result","Результат",["Win","Loss","BE-","BE+"]],["position","Напрямок",["Long","Short"]],
    ["pair","Інструмент",uniqueVals("pair")],["session","Сесія",uniqueVals("session")],
    ["setup","Сетап",uniqueVals("setup")],["entry_model","Модель",uniqueVals("entry_model")],
    ["bias","Біас",uniqueVals("bias")],["direction_type","Прод. / Розв.",["Continuation","Reversal"]]];
  let h='<div class="filters">';
  for(const [f,label,vals] of selects){
    if(!vals.length) continue;
    h+='<select onchange="setFilter(\''+f+'\',this.value)"><option value="">'+label+"</option>"+
      vals.map(v=>'<option '+(S.filters[f]===v?"selected":"")+' value="'+esc(v)+'">'+esc(f==="result"?resLabel(v):v)+"</option>").join("")+"</select>";
  }
  h+=periodBtn();
  if(Object.keys(S.filters).some(k=>S.filters[k])) h+='<button class="clear" onclick="clearFilters()">Скинути ×</button>';
  return h+"</div>";
}
/* ---------- выбор даты и периода (shadcn/ui · Date Picker) ---------- */
const CAL_ICON='<svg width="13" height="13" viewBox="0 0 24 24" fill="none">'+
  '<rect x="3" y="4.5" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.7"/>'+
  '<path d="M3 9.5h18M8 3v3M16 3v3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
function periodBtn(){
  const f=S.filters.from||"", t=S.filters.to||"";
  const lab=(f||t) ? (DatePicker.human(f)||"…")+" — "+(DatePicker.human(t)||"…") : "Період";
  return '<button class="dbtn'+((f||t)?" set":"")+'" data-tip="Показати угоди за проміжок дат" '+
    'onclick="pickRange(this)">'+CAL_ICON+esc(lab)+"</button>";
}
function pickRange(btn){
  DatePicker.open(btn,{mode:"range",value:{from:S.filters.from||"",to:S.filters.to||""},onPick:r=>{
    if(r.from) S.filters.from=r.from; else delete S.filters.from;
    if(r.to) S.filters.to=r.to; else delete S.filters.to;
    S.pages={}; render();
  }});
}
function pickDate(btn){
  DatePicker.open(btn,{mode:"single",value:S.selDay,onPick:key=>pickDay(key)});
}
function setFilter(f,v){ if(v)S.filters[f]=v; else delete S.filters[f]; S.pages={}; render(); }
function clearFilters(){ S.filters={}; S.pages={}; render(); }
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

/* ---------- Обзор: раскладка из макета (design/dash.html) ---------- */
const OV_PERIODS = [["month","Місяць"],["quarter","Квартал"],["year","Рік"]];
const RES_TAG = {"Win":"TP","Loss":"SL","BE-":"BE−","BE+":"BE+"};

function ovSetPeriod(p){ S.ovPeriod=p; render(); }
function ovOpenDay(key){
  S.selDay=key; S.jMonth=key.slice(0,7); S.jMode="cal"; S.view="journal";
  location.hash="journal"; render();
}

/* сделки выбранного периода + как он называется */
function ovPeriod(){
  const now=new Date(), y=String(now.getFullYear());
  if(S.ovPeriod==="year")
    return {list:S.trades.filter(t=>(t.date||"").slice(0,4)===y), lab:"Підсумок року", when:y};
  if(S.ovPeriod==="quarter"){
    const q=Math.floor(now.getMonth()/3), from=q*3+1, to=q*3+3;
    const list=S.trades.filter(t=>{
      const k=monKey(t); if(k.slice(0,4)!==y) return false;
      const m=+k.slice(5,7); return m>=from && m<=to;
    });
    return {list, lab:"Підсумок кварталу", when:["I","II","III","IV"][q]+" квартал "+y};
  }
  const mk=isoMonth(now);
  return {list:S.trades.filter(t=>monKey(t)===mk), lab:"Підсумок місяця", when:MONTHS[now.getMonth()]+" "+y};
}

function ovSign(r){ return r>0.0001?"pos":r<-0.0001?"neg":"be"; }
/* в обзоре проценты пишем как в макете: два знака в итогах, один в клетках дня */
function ovFmt(v){ return (v>0?"+":"")+(v==null?0:v).toFixed(2)+"%"; }
function ovFmt1(v){ return (v>0?"+":"")+v.toFixed(1)+"%"; }
function ovWord(n){
  const a=n%10, b=n%100;
  return a===1&&b!==11 ? "угода" : (a>=2&&a<=4&&!(b>=12&&b<=14)) ? "угоди" : "угод";
}

/* последняя неделя — крупный ряд сверху, в клетке светится исход дня */
function ovWeekHtml(){
  const byDay=groupBy(S.trades, dayKey);
  /* якорь недели — сегодня; если за неделю сделок нет, показываем неделю последней сделки */
  let now=new Date();
  const recent=[...byDay.keys()].sort();
  const lastKey=recent[recent.length-1];
  if(lastKey){
    const weekAgo=isoDay(new Date(now.getFullYear(),now.getMonth(),now.getDate()-6));
    if(lastKey<weekAgo) now=new Date(+lastKey.slice(0,4),+lastKey.slice(5,7)-1,+lastKey.slice(8,10));
  }
  let cells="", n=0, sum=0;
  for(let i=6;i>=0;i--){
    const d=new Date(now.getFullYear(),now.getMonth(),now.getDate()-i);
    const key=isoDay(d), list=byDay.get(key)||[];
    const r=list.reduce((a,t)=>a+netR(t),0);
    n+=list.length; sum+=r;
    const wd=WDS[(d.getDay()+6)%7];
    if(!list.length){
      cells+='<div class="day off"><span class="wd">'+wd+'</span><span class="dn">'+d.getDate()+
        '</span><span class="bot"><span class="dr">·</span></span></div>';
      continue;
    }
    const cnt={};
    for(const t of list) cnt[t.result]=(cnt[t.result]||0)+1;
    const top=Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a])[0];
    const cls=top==="Win"?"w":top==="Loss"?"l":"b";
    const val=Math.abs(r)<0.005?"0%":ovFmt1(r);
    cells+='<div class="day '+ovSign(r)+'" onclick="ovOpenDay(\''+key+'\')" title="'+
      list.length+" "+ovWord(list.length)+'">'+
      '<span class="glow '+cls+'">'+(RES_TAG[top]||"")+'</span>'+
      '<span class="wd">'+wd+'</span><span class="dn">'+d.getDate()+'</span>'+
      '<span class="bot"><span class="dr">'+val+'</span></span></div>';
  }
  return '<div class="week rise">'+
    '<div class="sec-lab"><span class="t">Останній тиждень</span>'+
    '<span class="wn">'+n+" "+ovWord(n)+'</span>'+
    '<span class="wsum '+ovSign(sum)+'">'+ovFmt(sum)+'</span>'+
    '<a href="#journal">весь місяць</a></div>'+
    '<div class="days">'+cells+"</div></div>";
}

/* восемь показателей hairline-сеткой */
function ovStatsHtml(st){
  const rows=[
    ["Угод", String(st.n), ""],
    ["Win Rate", st.wr==null?"·":fmtPct(st.wr), ""],
    ["Підсумок, %", ovFmt(st.net), clsR(st.net)],
    ["Середній RR", st.avgRR==null?"·":String(r1(st.avgRR)), ""],
    ["Profit Factor", st.pfTxt, ""],
    ["TP / SL / BE", st.wins+" / "+st.losses+" / "+st.be, ""],
    ["BE− / BE+", st.beM+" / "+st.beP, ""],
    ["Середній ризик", (st.avgRisk==null?"·":r1(st.avgRisk))+"%", ""],
  ];
  return '<div class="stats">'+rows.map(([l,v,c])=>
    '<div class="st"'+(TIPS[l]?' data-tip="'+esc(TIPS[l])+'"':"")+
    '><div class="lab">'+l+'</div><div class="val '+c+'">'+v+"</div></div>").join("")+"</div>";
}

/* сглаженная кривая по точкам */
function ovSmooth(pts){
  let d="M"+pts[0][0]+","+pts[0][1];
  for(let i=1;i<pts.length;i++){
    const [px,py]=pts[i-1],[cx,cy]=pts[i],mx=(px+cx)/2;
    d+=" C"+mx+","+py+" "+mx+","+cy+" "+cx+","+cy;
  }
  return d;
}

/* прибыль/убыток за год по календарным датам.
   Линия из Bklit UI · Profit/Loss Line: над нулём зелёная, под нулём красная,
   заливка тает к нулевой оси, при наведении — курсор с подписью дня. */
function ovEquityHtml(){
  const y=String(new Date().getFullYear());
  const arr=sortAsc(S.trades.filter(t=>(t.date||"").slice(0,4)===y));
  if(arr.length<2)
    return '<div class="shell rise"><div class="core"><div class="chart-lab">'+
      '<span class="t">Прибуток / збиток</span></div>'+
      '<div class="empty">Замало угод для графіка</div></div></div>';
  const start=new Date(+y,0,1);
  const days=[], vals=[], iso=[], months=new Set();
  let acc=0, peak=0, dd=0;
  for(const t of arr){
    acc+=netR(t);
    peak=Math.max(peak,acc);
    dd=Math.min(dd,acc-peak);
    const day=(t.date||"").slice(0,10);
    const d=new Date(+day.slice(0,4),+day.slice(5,7)-1,+day.slice(8,10));
    days.push(Math.round((d-start)/86400000));
    vals.push(acc); iso.push(day);
    months.add(day.slice(5,7));
  }
  const W=640,H=156,pad=10;
  const dmax=days[days.length-1]||364;
  const max=Math.max(...vals,0), min=Math.min(...vals,0);
  const X=i=>days[i]/dmax*W;
  const Y=v=>H-pad-(v-min)/((max-min)||1)*(H-pad*2);
  const pts=vals.map((v,i)=>[X(i),Y(v)]);
  const d=ovSmooth(pts);
  const last=vals.length-1;
  const y0=Y(0);                                  /* высота нулевой оси */
  const zero=Math.min(1,Math.max(0,y0/H));        /* та же высота долей — для градиентов */
  const grid=[0,.25,.5,.75,1].map(p=>
    '<line x1="0" y1="'+(pad+p*(H-pad*2))+'" x2="'+W+'" y2="'+(pad+p*(H-pad*2))+
    '" class="ovgrid" vector-effect="non-scaling-stroke"/>').join("");
  /* линия и заливка меняют цвет ровно на нуле */
  const defs='<defs>'+
    '<linearGradient id="plStroke" x1="0" y1="0" x2="0" y2="1">'+
      '<stop offset="0" stop-color="var(--up)"/>'+
      '<stop offset="'+zero.toFixed(4)+'" stop-color="var(--up)"/>'+
      '<stop offset="'+zero.toFixed(4)+'" stop-color="var(--down)"/>'+
      '<stop offset="1" stop-color="var(--down)"/></linearGradient>'+
    '<linearGradient id="plFill" x1="0" y1="0" x2="0" y2="1">'+
      '<stop offset="0" stop-color="var(--up)" stop-opacity=".13"/>'+
      '<stop offset="'+zero.toFixed(4)+'" stop-color="var(--up)" stop-opacity="0"/>'+
      '<stop offset="'+zero.toFixed(4)+'" stop-color="var(--down)" stop-opacity="0"/>'+
      '<stop offset="1" stop-color="var(--down)" stop-opacity=".12"/></linearGradient>'+
    "</defs>";
  const area='<path d="'+d+" L"+X(last)+","+y0.toFixed(1)+" L"+X(0)+","+y0.toFixed(1)+' Z" fill="url(#plFill)"/>';
  const svg='<svg viewBox="0 0 '+W+" "+H+'" width="100%" height="'+H+'" preserveAspectRatio="none">'+
    defs+grid+area+
    '<line class="plzero" x1="0" x2="'+W+'" y1="'+y0.toFixed(1)+'" y2="'+y0.toFixed(1)+'" vector-effect="non-scaling-stroke"/>'+
    '<path d="'+d+'" fill="none" stroke="url(#plStroke)" stroke-width="1.9" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'+
    '<line class="plcursor" x1="0" x2="0" y1="0" y2="'+H+'" vector-effect="non-scaling-stroke" hidden/>'+
    '<line class="plhover" stroke-linecap="round" stroke-width="7" vector-effect="non-scaling-stroke" hidden/>'+
    '<line x1="'+X(last)+'" x2="'+X(last)+'" y1="'+Y(vals[last]).toFixed(1)+'" y2="'+Y(vals[last]).toFixed(1)+'" stroke-linecap="round" stroke-width="6.5" vector-effect="non-scaling-stroke" stroke="'+(vals[last]<0?"var(--down)":"var(--up)")+'"/></svg>';
  const yax=[0,1,2,3,4].map(i=>{
    const v=max-(max-min)*i/4;
    return "<span>"+Math.round(v)+"</span>";
  }).join("");
  const mon=[...months].sort();
  const xax='<div class="xax" style="grid-template-columns:repeat('+mon.length+',1fr)">'+
    mon.map(m=>"<span>"+MON_SHORT[+m-1]+"</span>").join("")+"</div>";
  /* точки для подписи под курсором держим рядом с графиком */
  S.plPts=pts.map((p,i)=>({x:p[0],y:p[1],v:vals[i],d:iso[i]}));
  S.plBox={W:W,H:H};
  return '<div class="shell rise"><div class="core plline">'+
    '<div class="chart-lab"><span class="t">Прибуток / збиток</span>'+
    '<span class="v '+clsR(vals[last])+'">'+ovFmt(vals[last])+"</span>"+
    '<span class="dd">просадка '+ovFmt(dd)+"</span></div>"+
    '<div class="chart"><div class="yax">'+yax+"</div>"+
    '<div class="plwrap">'+svg+'<div class="pltip" hidden></div></div></div>'+xax+"</div></div>";
}

/* колонка-компаньон: где, чем и по какой модели торгуем за год */
function ovRailHtml(){
  const y=String(new Date().getFullYear());
  const yl=S.trades.filter(t=>(t.date||"").slice(0,4)===y);
  const bar=(nm,qt,w,cls)=>
    '<div class="bar '+(cls||"")+'"><span class="nm">'+esc(nm)+"</span>"+
    '<span class="qt">'+qt+"</span>"+
    '<span class="ln"><i style="width:'+Math.max(w,2).toFixed(1)+'%"></i></span></div>';
  const byCount=field=>[...groupBy(yl,t=>t[field]).entries()]
    .map(([k,v])=>[k,v.length]).sort((a,b)=>b[1]-a[1]).slice(0,4);
  const share=rows=>{
    if(!rows.length) return '<div class="empty">Немає даних</div>';
    const mx=Math.max(...rows.map(r=>r[1]));
    return rows.map(([nm,n])=>bar(nm,"<b>"+n+"</b> · "+Math.round(n/yl.length*100)+"%",n/mx*100)).join("");
  };
  /* при равном итоге выше тот, по которому сделок больше */
  const setups=[...groupBy(yl,t=>t.setup).entries()]
    .map(([k,v])=>[k,r1(calc(v).net),v.length])
    .sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])||b[2]-a[2]).slice(0,3);
  const smx=Math.max(1,...setups.map(x=>Math.abs(x[1])));
  const setupRows=setups.length
    ? setups.map(([nm,r,n])=>bar(nm,'<b class="'+clsR(r)+'">'+ovFmt1(r)+"</b> · "+n,Math.abs(r)/smx*100,ovSign(r))).join("")
    : '<div class="empty">Немає даних</div>';
  return '<aside class="rail"><div class="inner"><div class="cut">'+
    '<section><h3>Сесії<em>рік</em></h3><div class="rows">'+share(byCount("session"))+"</div></section>"+
    '<section><h3>Інструменти<em>рік</em></h3><div class="rows">'+share(byCount("pair"))+"</div></section>"+
    '<section><h3>Сетапи<em>підсумок, %</em></h3><div class="rows">'+setupRows+"</div></section>"+
    "</div></div></aside>";
}

function vDashboard(){
  if(!S.trades.length){
    return '<div class="vhead"><h1>Огляд</h1></div>'+
      '<div class="card"><div class="in" style="text-align:center;padding:56px 20px">'+
      '<div style="font-size:17px;font-weight:600;margin-bottom:6px">Журнал порожній</div>'+
      '<div class="hint" style="margin-bottom:18px">Додай першу угоду — статистика збереться сама.<br>Старі угоди можна завантажити через «Імпорт» ліворуч унизу.</div>'+
      '<button class="btn primary" onclick="openForm()">+ New Trade</button></div></div>';
  }
  const per=ovPeriod(), st=calc(per.list);
  const rs=per.list.map(netR);
  const best=rs.length?Math.max(...rs):null, worst=rs.length?Math.min(...rs):null;
  const btns=OV_PERIODS.map(([k,l])=>
    '<button class="'+(S.ovPeriod===k?"on":"")+'" onclick="ovSetPeriod(\''+k+'\')">'+l+"</button>").join("");

  return '<div class="ovw">'+
    '<div class="ohead"><h1>Огляд</h1><div class="per">'+btns+"</div></div>"+
    '<div class="flow">'+
      ovWeekHtml()+
      '<div class="shell rise"><div class="core">'+
        '<div class="sum"><div><div class="lab">'+per.lab+"</div>"+
        '<div class="big '+clsR(st.net)+'">'+(per.list.length?ovFmt(st.net):"—")+"</div></div>"+
        '<div class="when">'+per.when+"</div>"+
        '<div class="right"><div class="lab">Найкраща · найгірша</div>'+
        '<div class="v">'+(best==null?"—":ovFmt(best)+" · "+ovFmt(worst))+"</div></div></div>"+
        ovStatsHtml(st)+
      "</div></div>"+
      ovEquityHtml()+
    "</div>"+
    ovRailHtml()+
  "</div>";
}

/* ---------- Journal: живой журнал месяца ---------- */
function vJournal(){
  const [Y,M]=S.jMonth.split("-").map(Number);
  const label=MONTHS[M-1]+" "+Y;
  const monthTrades=S.trades.filter(t=>monKey(t)===S.jMonth);
  const st=calc(monthTrades);
  const modeBtns='<button class="pill '+(S.jMode==="cal"?"on":"")+'" onclick="S.jMode=\'cal\';render()">Місяць</button>'+
    '<button class="pill '+(S.jMode==="list"?"on":"")+'" onclick="S.jMode=\'list\';render()">Усі угоди</button>';

  let h='<div class="vhead"><h1>Журнал</h1>';
  if(S.jMode==="cal"){
    h+='<div class="right">'+
      '<button class="navbtn" data-tip="Попередній місяць" onclick="shiftJMonth(-1)">‹</button><button class="perlabel dbtn" data-tip="Вибрати день у календарі" onclick="pickDate(this)">'+CAL_ICON+label+'</button><button class="navbtn" data-tip="Наступний місяць" onclick="shiftJMonth(1)">›</button>'+
      '<button class="pill" data-tip="Повернутись до поточного дня" onclick="goToday()">Сьогодні</button>'+
      '<button class="pill share" data-tip="Зібрати картинку з підсумками місяця" data-ym="'+S.jMonth+'" onclick="openShare(this.dataset.ym)">Картинка для каналу</button>'+
      modeBtns+"</div></div>";
  }else{
    h+='<div class="right">'+modeBtns+"</div></div>";
    const list=sortDesc(applyFilters(S.trades));
    return h+filterBar()+
      '<div class="jsplit">'+tradesCard(list,"Усі угоди · "+list.length,"all")+tradePaneHtml(false)+"</div>";
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
  const dayLabel=dsel.getDate()+" "+MONTHS_GEN[dsel.getMonth()]+", "+WDS[(dsel.getDay()+6)%7];

  let chips="";
  if(dayTrades.length){
    chips='<div class="chips">'+
      '<span class="chip"><b>'+dst.n+"</b> уг</span>"+
      '<span class="chip '+(dst.net>0?"pos":dst.net<0?"neg":"")+'">'+fmtR(dst.net)+"</span>"+
      (dst.wr!=null?'<span class="chip">WR <b>'+fmtPct(dst.wr)+"</b></span>":"")+
      (dst.avgRR!=null?'<span class="chip">сер. RR <b>'+r1(dst.avgRR)+"</b></span>":"")+
      "</div>";
  }
  const dayPanel =
    '<div class="card daypanel"><h3>'+dayLabel+"</h3>"+chips+
    (mistakes.length?'<div class="mistline">Помилки: <span class="neg">'+mistakes.join(" · ")+"</span></div>":"")+
    (dayTrades.length
      ? '<div class="tlist">'+dayTrades.map(tradeRow).join("")+"</div>"
      : '<div class="empty">Угод немає</div>')+
    '<button class="addday" onclick="openForm(null,\''+S.selDay+'\')">+ Угода на цей день</button>'+
    "</div>";

  h+='<div class="jgrid">'+
    '<div class="card">'+calHtml(S.jMonth,"pickDay",S.selDay)+
      '<div class="callegend"><i class="mk tp">TP</i>тейк<i class="mk sl">SL</i>стоп<i class="mk be">BE</i>беззбиток'+
      '<span class="lgend-rev"><i class="mk tp rev">TP</i>рамка — розворот проти біасу</span></div>'+
    "</div>"+(S.selTrade&&findTrade(S.selTrade)?tradePaneHtml(true):dayPanel)+"</div>";

  /* месяц целиком: динамика и разрезы */
  if(monthTrades.length){
    h+='<div class="split">'+
      '<div class="card"><h3>Еквіті місяця · %</h3><div class="in">'+equitySVG(monthTrades)+"</div></div>"+
      '<div style="min-width:0">'+bestWorstHtml(monthTrades)+"</div></div>";
    h+=beReportHtml(monthTrades);
    h+=tradesCard(sortDesc(monthTrades),"Угоди місяця · "+monthTrades.length,"month");
  }
  return h;
}
function shiftJMonth(d){ const [y,m]=S.jMonth.split("-").map(Number); const dt=new Date(y,m-1+d,1); S.jMonth=isoMonth(dt); S.pages={}; render(); }
function pickDay(key){ S.selTrade=null; S.selDay=key; if(key.slice(0,7)!==S.jMonth)S.jMonth=key.slice(0,7); render(); }
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
    ? "Беззбиток у плюсі: врятував більше, ніж забрав. Лишаємо як є."
    : delta<-0.001
      ? "Беззбиток у мінусі: забрав більше, ніж урятував. Переносиш стоп зарано."
      : "Беззбиток вийшов у нуль.";
  const bar=(a,b)=>{
    const m=Math.max(a,b,0.001);
    return '<div class="bebar"><span class="t" style="width:'+(a/m*100)+'%;background:var(--up)"></span></div>'+
           '<div class="bebar"><span class="t" style="width:'+(b/m*100)+'%;background:var(--down)"></span></div>';
  };
  return '<div class="card"><h3>Беззбитки · врятували чи забрали</h3><div class="in">'+
    '<div class="begrid">'+
      '<div class="becell"><div class="l">BE\u2212 · врятували від стопу</div>'+
        '<div class="v pos">+'+r1(saved)+'%</div><div class="s">'+minus.length+' угод — ціна пішла проти, стоп забрав би гроші</div></div>'+
      '<div class="becell"><div class="l">BE+ · забрали тейк</div>'+
        '<div class="v neg">\u2212'+r1(lost)+'%</div><div class="s">'+plus.length+' угод — ціна дійшла б до цілі без тебе</div></div>'+
      '<div class="becell"><div class="l">Чистий ефект</div>'+
        '<div class="v '+clsR(delta)+'">'+fmtR(delta)+'</div><div class="s">'+verdict+'</div></div>'+
      '<div class="becell"><div class="l">Частка беззбитків</div>'+
        '<div class="v beclr">'+share+'%</div><div class="s">'+be.length+' з '+list.length+' угод</div></div>'+
    "</div>"+bar(saved,lost)+
    '<div class="behint">BE\u2212 — тапнуло в беззбиток, далі пішло проти: беззбиток спрацював на твою користь. '+
    'BE+ — тапнуло в беззбиток, а далі ціна дійшла до цілі: угода була б прибутковою.</div>'+
    "</div></div>";
}

/* ---------- разрезы месяца ---------- */
function bestWorstHtml(list){
  const dims=[["setup","Сетап"],["pair","Інструмент"],["entry_model","Модель входу"],["session","Сесія"],
              ["direction_type","Продовження / Розворот"],["bias","Біас"],["position","Напрямок"]];
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
    cells+='<div class="cell"><div class="t">Помилки</div>'+
      mist.map(m=>'<div class="row"><span class="k">'+esc(m.name)+' · '+m.n+'</span><span class="v '+clsR(m.net)+'">'+fmtR(m.net)+"</span></div>").join("")+"</div>";
  }
  return cells?'<div class="card"><h3>Найкраще / найгірше</h3><div class="bw">'+cells+"</div></div>":"";
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
    const flag = rows.length>1 ? (i===0?' <span class="tick best">найкращий</span>':(i===rows.length-1?' <span class="tick worst">найгірший</span>':"")) : "";
    return "<tr><td>"+esc(g.name)+flag+"</td><td>"+g.st.n+"</td><td>"+fmtPct(g.st.wr)+
      '</td><td class="'+clsR(g.st.net)+'">'+fmtR(g.st.net)+"</td></tr>";
  }).join("");
  return '<div class="rep-card"><h4>'+esc(label)+'</h4><table class="simple mini">'+
    "<tr><th>"+esc(label)+"</th><th>Уг.</th><th>WR</th><th>Підсумок</th></tr>"+body+"</table></div>";
}
function openMonthReport(ym){
  S.mRep=ym;
  const [Y,M]=ym.split("-").map(Number);
  const list=S.trades.filter(t=>monKey(t)===ym);
  const st=calc(list);
  const title=MONTHS[M-1]+" "+Y;
  let h='<div class="m-head"><h2>'+title+' <span class="'+clsR(st.net)+'" style="font-family:var(--mono)">'+fmtR(st.net)+"</span></h2>"+
    '<button class="x" onclick="closeModal()">×</button></div><div class="m-body rep">';
  if(!list.length){ h+='<div class="empty">Цього місяця угод не було</div>'; }
  else{
    h+=kpiHtml(st);
    h+='<div class="card"><h3>Динаміка місяця</h3><div class="in">'+equitySVG(list)+"</div></div>";

    /* дни */
    const byDay=[...groupBy(list,dayKey).entries()].sort((a,b)=>a[0]<b[0]?-1:1)
      .map(([d,arr])=>({d,st:calc(arr)}));
    const best=byDay.slice().sort((a,b)=>b.st.net-a.st.net);
    h+='<div class="rep-sec">Дні</div><div class="rep-grid">'+
      '<div class="rep-card scrolly"><h4>Усі торгові дні ('+byDay.length+")</h4>"+
      '<table class="simple mini"><tr><th>День</th><th>Уг.</th><th>WR</th><th>Підсумок</th></tr>'+
      byDay.map(x=>{
        const dt=new Date(x.d+"T00:00");
        return '<tr class="click" data-day="'+x.d+'" onclick="gotoDayFromReport(this.dataset.day)">'+
          "<td>"+dt.getDate()+" "+MON_SHORT[dt.getMonth()]+", "+WDS[(dt.getDay()+6)%7]+"</td>"+
          "<td>"+x.st.n+"</td><td>"+fmtPct(x.st.wr)+'</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div>"+
      '<div class="rep-card"><h4>Крайні дні</h4><table class="simple mini c3">'+
      '<tr><th>День</th><th>Уг.</th><th>Підсумок</th></tr>'+
      best.slice(0,3).concat(best.slice(-3).reverse()).filter((v,i,a)=>a.indexOf(v)===i).map(x=>{
        const dt=new Date(x.d+"T00:00");
        return "<tr><td>"+dt.getDate()+" "+MON_SHORT[dt.getMonth()]+"</td><td>"+x.st.n+
          '</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div></div>";

    /* разрезы */
    h+='<div class="rep-sec">Розрізи</div><div class="rep-grid">'+
      dimTable(list,"setup","Сетап")+dimTable(list,"pair","Актив")+
      dimTable(list,"session","Сесія")+dimTable(list,"entry_model","Модель входу")+
      dimTable(list,"direction_type","Продовження / Розворот")+dimTable(list,"position","Напрямок")+
      "</div>";

    /* ошибки */
    const mist=[...groupBy(list,t=>t.mistakes).entries()].map(([name,arr])=>({name,st:calc(arr)}))
      .sort((a,b)=>a.st.net-b.st.net);
    const withM=list.filter(t=>(t.mistakes||"").trim()), noM=list.filter(t=>!(t.mistakes||"").trim());
    h+='<div class="rep-sec">Помилки</div>';
    if(mist.length){
      h+='<div class="rep-grid"><div class="rep-card"><h4>Що коштувало грошей</h4><table class="simple mini">'+
        "<tr><th>Помилка</th><th>Уг.</th><th>Підсумок</th></tr>"+
        mist.map(m=>"<tr><td>"+esc(m.name)+"</td><td>"+m.st.n+'</td><td class="'+clsR(m.st.net)+'">'+fmtR(m.st.net)+"</td></tr>").join("")+
        "</table></div>"+
        '<div class="rep-card"><h4>З помилкою проти без</h4><table class="simple mini">'+
        "<tr><th></th><th>Уг.</th><th>WR</th><th>Підсумок</th></tr>"+
        '<tr><td>З позначкою</td><td>'+withM.length+"</td><td>"+fmtPct(calc(withM).wr)+'</td><td class="'+clsR(calc(withM).net)+'">'+fmtR(calc(withM).net)+"</td></tr>"+
        '<tr><td>Без позначки</td><td>'+noM.length+"</td><td>"+fmtPct(calc(noM).wr)+'</td><td class="'+clsR(calc(noM).net)+'">'+fmtR(calc(noM).net)+"</td></tr>"+
        "</table></div></div>";
    } else h+='<div class="hint" style="padding:4px 0 12px">За місяць помилок не позначено.</div>';

    /* риск */
    const offSize=list.filter(t=>(t.risk||1)!==1), onSize=list.filter(t=>(t.risk||1)===1);
    if(offSize.length){
      h+='<div class="rep-sec">Розмір ризику</div><div class="rep-grid"><div class="rep-card"><h4>Відхилення від 1%</h4>'+
        '<table class="simple mini"><tr><th></th><th>Уг.</th><th>WR</th><th>Підсумок</th></tr>'+
        '<tr><td>Ризик 1%</td><td>'+onSize.length+"</td><td>"+fmtPct(calc(onSize).wr)+'</td><td class="'+clsR(calc(onSize).net)+'">'+fmtR(calc(onSize).net)+"</td></tr>"+
        '<tr><td>Інший ризик</td><td>'+offSize.length+"</td><td>"+fmtPct(calc(offSize).wr)+'</td><td class="'+clsR(calc(offSize).net)+'">'+fmtR(calc(offSize).net)+"</td></tr>"+
        "</table></div></div>";
    }
    h+='<div class="rep-sec">Беззбитки</div>'+beReportHtml(list);
    h+='<div class="rep-sec">Усі угоди місяця</div><div class="card"><div class="tlist">'+
      sortAsc(list).map(tradeRow).join("")+"</div></div>";
  }
  h+='</div><div class="m-foot"><button class="btn primary" data-ym="'+ym+'" onclick="closeModal();openShare(this.dataset.ym)">Картинка для каналу</button>'+
    '<button class="btn" data-ym="'+ym+'" onclick="gotoMonthFromReport(this.dataset.ym)">Відкрити в журналі</button>'+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">Закрити</button></div>';
  openModal(h);
}

/* ---------- Quarterly ---------- */
function vQuarterly(){
  const Y=S.qYear;
  let h='<div class="vhead"><h1>Квартали</h1><div class="right">'+
    '<button class="navbtn" onclick="S.qYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.qYear++;render()">›</button></div></div>';
  h+='<div class="qgrid">';
  for(let q=0;q<4;q++){
    const months=[q*3+1,q*3+2,q*3+3];
    const keys=months.map(m=>Y+"-"+pad(m));
    const list=S.trades.filter(t=>keys.includes(monKey(t)));
    const st=calc(list);
    const perMonth=months.map(m=>{
      const ml=S.trades.filter(t=>monKey(t)===Y+"-"+pad(m));
      return {m,label:MON_SHORT[m-1],net:ml.reduce((a,t)=>a+netR(t),0),n:ml.length};
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
      '<div class="qr"><span>Сер. RR</span><b>'+(st.avgRR!=null?r1(st.avgRR):"—")+"</b></div>"+
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
  let h='<div class="vhead"><h1>Роки</h1><div class="right">'+
    '<button class="navbtn" onclick="S.yYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.yYear++;render()">›</button></div></div>';
  h+=kpiHtml(st);
  if(list.length) h+='<div class="card"><h3>Еквіті року · %</h3><div class="in">'+equitySVG(list)+"</div></div>";
  h+=beReportHtml(list);
  /* месяцы */
  let mrows="";
  for(let m=1;m<=12;m++){
    const ml=list.filter(t=>monKey(t)===Y+"-"+pad(m));
    if(!ml.length) continue;
    const ms=calc(ml);
    mrows+='<tr class="click" onclick="openMonthReport(\''+Y+"-"+pad(m)+'\')">'+
      "<td>"+MONTHS[m-1]+' <span class="go">розбір →</span></td><td>'+ms.n+"</td><td>"+fmtPct(ms.wr)+'</td><td class="'+clsR(ms.net)+'">'+fmtR(ms.net)+"</td><td>"+(ms.avgRR!=null?r1(ms.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>Місяці · клік по місяцю відкриває розбір</h3><table class="simple"><tr><th>Місяць</th><th>Угод</th><th>Win Rate</th><th>Підсумок, %</th><th>Сер. RR</th></tr>'+
    (mrows||'<tr><td colspan="5" class="empty">Немає даних</td></tr>')+"</table></div>";
  /* кварталы */
  let qrows="";
  for(let q=0;q<4;q++){
    const keys=[1,2,3].map(i=>Y+"-"+pad(q*3+i));
    const ql=list.filter(t=>keys.includes(monKey(t)));
    if(!ql.length) continue;
    const qs=calc(ql);
    qrows+="<tr><td>Q"+(q+1)+"</td><td>"+qs.n+"</td><td>"+fmtPct(qs.wr)+'</td><td class="'+clsR(qs.net)+'">'+fmtR(qs.net)+"</td><td>"+(qs.avgRR!=null?r1(qs.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>Квартали</h3><table class="simple"><tr><th>Квартал</th><th>Угод</th><th>Win Rate</th><th>Підсумок, %</th><th>Сер. RR</th></tr>'+
    (qrows||'<tr><td colspan="5" class="empty">Немає даних</td></tr>')+"</table></div>";
  return h;
}

/* ---------- Analytics ---------- */
function vAnalytics(){
  const list=applyFilters(S.trades);
  let h='<div class="vhead"><h1>Аналітика</h1><span class="sub">'+list.length+" угод у вибірці</span></div>";
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
  h+='<div class="card"><h3>Результати · '+esc(DIMS.find(d=>d.k===S.dim).label)+"</h3>"+
    '<div class="ahead"><span>Назва</span><span>Угод</span><span>Win Rate</span><span>Сер. RR</span><span>Підсумок, %</span></div>'+
    (rows||'<div class="empty">Немає даних — поле не заповнене в жодній угоді</div>')+"</div>";
  return h;
}

/* ================= МОДАЛКИ ================= */
function openModal(html){ $("#modalBox").innerHTML=html; $("#modal").hidden=false; document.body.style.overflow="hidden"; }
function closeModal(){
  if(window.Panel && Panel.isOpen()) Panel.close();
  $("#modal").hidden=true; document.body.style.overflow="";
  S.formShots=[]; document.removeEventListener("paste", onPasteShot);
}

/* ---------- тема ---------- */
/* ---------- чем набраны цифры ---------- */
function setNum(v){
  document.documentElement.setAttribute("data-num",v);
  try{ localStorage.setItem("tj_num",v); }catch(e){}
  markNum();
  render();
}
function markNum(){
  const el=$("#numFont");
  if(el) el.value=document.documentElement.getAttribute("data-num")||"geist";
}

/* ---------- вид левого меню: current, flat, icons ---------- */
function setNav(v){
  document.documentElement.setAttribute("data-nav",v);
  try{ localStorage.setItem("tj_nav",v); }catch(e){}
  render();
}
function markLayout(){}

function toggleTheme(){
  const dark = document.documentElement.getAttribute("data-theme")==="dark";
  if(dark) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme","dark");
  try{ localStorage.setItem("tj_theme", dark?"light":"dark"); }catch(e){}
  markTheme();
}
function markTheme(){
  const b=$("#themeBtn"); if(!b) return;
  const dark = document.documentElement.getAttribute("data-theme")==="dark";
  const sun='<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="4.2" stroke="currentColor" stroke-width="1.6"/><path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  const moon='<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M20 14.2A8.2 8.2 0 019.8 4a8.4 8.4 0 100 20 8.2 8.2 0 0010.2-9.8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  b.innerHTML = (dark ? sun : moon) + "<span>" + (dark ? "Світла тема" : "Темна тема") + "</span>";
  b.title = dark ? "Перемкнути на світлу" : "Перемкнути на темну";
}

$("#modal") && null;

function openLightbox(src){ $("#lightboxImg").src=src; $("#lightbox").hidden=false; }
function closeLightbox(){ $("#lightbox").hidden=true; $("#lightboxImg").src=""; }

/* ---------- просмотр сделки ---------- */
/* содержимое карточки сделки: поля, тексты, графики. Обёртку задаёт вызывающий */
function tradeBodyHtml(t){
  const r=netR(t);
  const fields=[["Інструмент",t.pair],["Дата",(t.date||"").replace("T"," ")],["Сесія",t.session],["Напрямок",t.position],
    ["Модель входу",t.entry_model],["Біас",t.bias],["Сетап",t.setup],["Прод. / Розв.",dirType(t)],
    ["Результат",resLabel(t.result)],["RR",t.rr!=null?t.rr:""],["Ризик",t.risk!=null?t.risk+"%":""],["Підсумок",fmtR(r)]];
  let h='<div class="dgrid">'+fields.filter(f=>f[1]!==""&&f[1]!=null).map(f=>
    '<div class="f2"><div class="l">'+f[0]+'</div><div class="v">'+esc(f[1])+"</div></div>").join("")+"</div>";
  for(const [label,key] of [["Як заходив","entry_details"],["Нотатки","notes"],["Помилки","mistakes"],["Коментарі","comments"]]){
    if((t[key]||"").trim()) h+='<div class="dtext"><div class="l">'+label+'</div><div class="v">'+esc(t[key])+"</div></div>";
  }
  const shots=(t.screenshots||[]).slice().sort((a,b)=>TF_ORDER.indexOf(a.tf)-TF_ORDER.indexOf(b.tf));
  if(shots.length){
    h+='<div class="dtext"><div class="l">Графіки · '+shots.map(s=>esc(s.tf||"")).join(" | ")+"</div></div>";
    h+='<div class="charts">'+shots.map(s=>
      '<div class="chart-item"><div class="l">'+esc(s.tf||"chart")+'</div><img loading="lazy" src="'+shotSrc(s)+'" onclick="openLightbox(this.src)"></div>').join("")+"</div>";
  }
  return h;
}

/* карточка сделки выезжающей панелью — остаётся для узких экранов и отчётов */
function openTrade(id){
  const t=(S.all.length?S.all:S.trades).find(x=>x.id===id); if(!t) return;
  const r=netR(t);
  const h='<div class="m-head"><h2>'+esc(t.pair||"Угода")+' <span class="'+clsR(r)+'" style="font-family:var(--mono)">'+fmtR(r)+"</span></h2>"+
    '<button class="x" onclick="closeModal()">×</button></div>'+
    '<div class="m-body">'+tradeBodyHtml(t)+"</div>"+
    '<div class="m-foot"><button class="btn" onclick="openForm(\''+t.id+'\')">Змінити</button>'+
    '<button class="btn danger" onclick="delTrade(\''+t.id+'\')">Видалити</button><span class="sp"></span>'+
    '<button class="btn" onclick="closeModal()">Закрити</button></div>';
  Sheet.open(h);
}

/* ---------- сделка прямо в странице: вторая панель журнала ---------- */
function findTrade(id){ return (S.all.length?S.all:S.trades).find(x=>x.id===id); }
/* на широком экране карточка встаёт во вторую панель, на узком выезжает */
function openTradeRow(id){
  if(S.view==="journal" && innerWidth>=1100 && $("#modal").hidden && !Panel.isOpen()) pickTrade(id);
  else openTrade(id);
}
function pickTrade(id){ S.selTrade=id; render(); }
function closeTradeCard(){ S.selTrade=null; render(); }
function tradePaneHtml(back){
  const t=S.selTrade?findTrade(S.selTrade):null;
  if(!t) return '<div class="card tpane"><div class="empty">Вибери угоду зі списку</div></div>';
  const r=netR(t);
  return '<div class="card tpane"><div class="tpane-head">'+
    '<h3>'+esc(t.pair||"Угода")+' <span class="'+clsR(r)+'">'+fmtR(r)+"</span></h3>"+
    '<button class="x" title="Закрити картку" onclick="closeTradeCard()">×</button></div>'+
    '<div class="tpane-body">'+tradeBodyHtml(t)+"</div>"+
    '<div class="tpane-foot">'+
      (back?'<button class="btn" onclick="closeTradeCard()">← До дня</button>':"")+
      '<button class="btn" onclick="openForm(\''+t.id+'\')">Змінити</button>'+
      '<button class="btn danger" onclick="delTrade(\''+t.id+'\')">Видалити</button></div></div>';
}
async function delTrade(id){
  if(!confirm("Видалити угоду? Статистика перерахується.")) return;
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
      '<button type="button" class="more" onclick="showOwn(\''+field+'\')" title="Своє значення">＋</button></div>'+
      '<input class="qinput" id="fld_'+field+'"'+(num?' type="number" step="0.25" min="0"':"")+
      ' value="'+esc(cur)+'" placeholder="'+esc(ph||"")+'" autocomplete="off"'+
      (cur&&!known?"":" hidden")+' oninput="markQuick();calcOutcome()">';
  };

  const models=[...new Set(["cisd",...topVals("entry_model",4)])];
  const setups=topVals("setup",4);
  const mistakes=topVals("mistakes",5);

  let h='<div class="m-head"><h2>'+(t?"Змінити угоду":"Нова угода")+
    '</h2><button class="x" onclick="closeModal()">×</button></div>';

  h+='<div class="m-body form">'+

  /* ---- сделка ---- */
  '<section class="fcard"><h4>Угода</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>Інструмент <i>*</i></label>'+
        pick("pair",PAIRS_ACTIVE,t?t.pair:"","свій інструмент")+"</div>"+
      '<div class="f"><label>Дата й час <i>*</i></label>'+
        '<input id="fld_date" type="datetime-local" value="'+esc(dt)+'"></div>'+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>Сесія</label>'+
        pick("session",SESSIONS,t?t.session:"","своя сесія")+"</div>"+
      '<div class="f"><label>Напрямок угоди</label>'+
        seg("position",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.position:"","big")+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- контекст ---- */
  '<section class="fcard"><h4>Контекст</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>Біас дня</label>'+
        seg("bias",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.bias:"","big")+"</div>"+
      '<div class="f"><label>Тип входу <span class="autotag" id="dirTag">підставиться сам</span></label>'+
        seg("direction_type",[{v:"Continuation",t:"Продовження",cls:"cont"},
                              {v:"Reversal",t:"Розворот",cls:"rev"}],t?dirType(t):"","big")+"</div>"+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>Модель входу</label>'+
        pick("entry_model",models,t?t.entry_model:"","своя модель")+"</div>"+
      '<div class="f"><label>Сетап</label>'+
        pick("setup",setups,t?t.setup:"","свій сетап")+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- результат ---- */
  '<section class="fcard accent"><h4>Результат</h4><div class="fbody">'+
    '<div class="f"><label>Чим завершилася <i>*</i></label>'+
      seg("result",[{v:"Win",t:"TP",cls:"win"},{v:"Loss",t:"SL",cls:"loss"},
                    {v:"BE-",t:"BE\u2212",cls:"bek"},{v:"BE+",t:"BE+",cls:"bepk"}],t?t.result:"","big res")+"</div>"+
    '<div class="frow">'+
      '<div class="f"><label>RR — у скільки разів ціль далі за стоп</label>'+
        '<input id="fld_rr" type="number" step="0.1" min="0" placeholder="2.5" oninput="calcOutcome()" value="'+(t&&t.rr!=null?t.rr:"")+'"></div>'+
      '<div class="f"><label>Ризик, % від депозиту</label>'+
        pick("risk",["0.5","1","1.5","2"],(t&&t.risk!=null?String(t.risk):"1"),"свій ризик",true)+"</div>"+
    "</div>"+
    '<div class="outcome" id="outcome"></div>'+
  "</div></section>"+

  /* ---- скриншоты ---- */
  '<section class="fcard"><h4>Скриншоти за таймфреймами</h4><div class="fbody">'+
    '<div class="tfgrid" id="shotsEdit"></div>'+
    '<input id="shotFile" type="file" accept="image/*" multiple hidden>'+
  "</div></section>"+

  /* ---- заметки ---- */
  '<section class="fcard"><h4>Нотатки</h4><div class="fbody">'+
    '<div class="f"><label>Як заходив</label><textarea id="fld_entry_details" placeholder="тест 4h імб, 1m цисд, ціль 15m фрактал">'+v("entry_details")+"</textarea></div>"+
    '<div class="f"><label>Думки про угоду</label><textarea id="fld_notes" class="short">'+v("notes")+"</textarea></div>"+
    '<div class="f"><label>Помилка, якщо була</label>'+
      '<div class="quick">'+mistakes.map(x=>
        '<button type="button" data-f="mistakes" data-v="'+esc(x)+'" onclick="quickSet(this)">'+esc(x)+"</button>").join("")+"</div>"+
      '<input id="fld_mistakes" value="'+v("mistakes")+'" placeholder="порожньо, якщо помилок немає" autocomplete="off" oninput="markQuick()"></div>'+
  "</div></section>"+

  "</div>";

  h+='<div class="m-foot">'+
    (t?'<button class="btn danger" onclick="delTrade(\''+t.id+'\')">Видалити</button>':"")+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">Скасувати</button>'+
    '<button class="btn primary" onclick="saveTrade(\''+(t?t.id:"")+'\')">Зберегти</button></div>';

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
  if(!res){ box.className="outcome"; box.innerHTML='<span class="hint">Обери результат — покажу, скільки це у відсотках</span>'; return; }
  let val=0, txt="";
  if(res==="Win"){ val=r*rr; txt="Тейк за ризику "+r1(r)+"% і RR "+r1(rr); }
  else if(res==="Loss"){ val=-r; txt="Стоп забирає ризик повністю"; }
  else { val=0; txt = res==="BE+" ? "Беззбиток, але ціна дійшла б до цілі" : "Беззбиток, далі пішло проти"; }
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
  if(tag) tag.textContent = val ? "підставлено само" : "підставиться сам";
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
      putShot(tf,dataUrl,"з буфера");
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
  if(field==="direction_type"){ S.dirTouched=true; const tag=$("#dirTag"); if(tag) tag.textContent="обрано вручну"; }
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
      '<button type="button" class="rm" title="Прибрати" onclick="removeShot('+i+')">×</button></div>'+
      '<img src="'+src+'" onclick="openLightbox(this.src)"></div>';
  };
  let h="";
  for(const tf of TF_SLOTS){
    const i=S.formShots.findIndex((s,idx)=>s.tf===tf && !used.has(idx));
    if(i>=0){ used.add(i); h+=filledTile(S.formShots[i],i,tf); }
    else{
      const on=S.activeTf===tf;
      h+='<div class="tfslot'+(on?" active":"")+'" data-tf="'+tf+'" data-drop="'+tf+'" onclick="armSlot(this.dataset.tf)">'+
        '<div class="tfl"><span>'+tf+'</span>'+
        '<button type="button" class="pick" title="Обрати файл" data-tf="'+tf+
        '" onclick="event.stopPropagation();pickFor(this.dataset.tf)">файл</button></div>'+
        '<div class="drop">'+(on?'<span class="ready">Ctrl+V</span>':"+")+'</div></div>';
    }
  }
  S.formShots.forEach((s,i)=>{ if(!used.has(i)) h+=filledTile(s,i,s.tf||"?"); });
  h+='<div class="attach" data-drop="" onclick="$(\'#shotFile\').click()">'+
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none">'+
    '<path d="M12 16V4M8 8l4-4 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'+
    '<path d="M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'+
    'Перетягни картинки сюди або <b>обери файли</b> — розкладемо по таймфреймах</div>';
  h+='<div class="tfhint">Скопіюй графік у TradingView (<b>Ctrl+Alt+S</b>) → клікни потрібний таймфрейм → <b>Ctrl+V</b>. Зберігати картинку на комп\'ютер не потрібно.</div>';
  box.innerHTML=h;
  /* перетаскивание: в конкретный таймфрейм или в общую зону */
  if(window.Attach) Attach.mount(box, acceptFiles);
}
/* общий приём картинок: из диалога, перетаскиванием и из буфера */
function acceptFiles(files, tf){
  [...files].forEach((f,idx)=>{
    resizeImage(f).then(dataUrl=>{
      const slot = tf || (idx===0 && S.activeTf ? S.activeTf : (guessTf(f.name)||firstEmptyTf()));
      putShot(slot,dataUrl,f.name);
      if(!tf && idx===0) S.activeTf=null;
    });
  });
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
  acceptFiles(files, null);
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
  if(!t.pair){ alert("Вкажи інструмент"); return; }
  if(!t.date){ alert("Вкажи дату"); return; }
  if(!t.result){ alert("Вкажи результат — TP / SL / BE\u2212 / BE+"); return; }
  if(t.result==="Win" && !num(t.rr)){ alert("Для TP потрібен RR — інакше результат порахується як 0R"); return; }
  const btn=document.querySelector(".m-foot .primary"); if(btn){btn.disabled=true;btn.textContent="Зберігаю…";}
  try{
    if(id) await api("PUT","/api/trades/"+id,t);
    else   await api("POST","/api/trades",t);
    await reload(); closeModal(); render();
  }catch(err){ alert("Не збереглося: "+err.message); if(btn){btn.disabled=false;btn.textContent="Зберегти";} }
}

/* ---------- импорт / экспорт ---------- */
const IMP={rows:[],headers:[],map:{}};
const IMP_FIELDS=[["pair","Інструмент"],["date","Дата"],["session","Сесія"],["position","Напрямок"],
  ["entry_model","Модель входу"],["bias","Біас"],["setup","Сетап"],["direction_type","Прод./Розв."],
  ["result","Результат"],["rr","RR"],["risk","Ризик"],["entry_details","Як заходив"],["notes","Нотатки"],["mistakes","Помилки"]];

function openImport(){
  let h='<div class="m-head"><h2>Імпорт угод</h2><button class="x" onclick="closeModal()">×</button></div>'+
  '<div class="m-body">'+
  '<p class="hint">Підходить файл <b>JSON</b> (масив угод) або <b>CSV</b> (перший рядок — заголовки). '+
  'Після завантаження зістав колонки з полями журналу — назви, що збігаються, підставляться самі.</p>'+
  '<input id="impFile" type="file" accept=".json,.csv,.txt" style="margin:12px 0">'+
  '<div id="impMap"></div></div>'+
  '<div class="m-foot"><span class="sp"></span><button class="btn" onclick="closeModal()">Скасувати</button>'+
  '<button class="btn primary" id="impGo" disabled onclick="doImport()">Імпортувати</button></div>';
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
    }catch(err){ $("#impMap").innerHTML='<p class="neg">Не вдалося розібрати файл: '+esc(err.message)+"</p>"; return; }
    buildMap();
  };
  fr.readAsText(f,"utf-8");
}
function guessHeader(field,headers){
  /* распознаём и украинские, и старые русские заголовки — файлы бывают разные */
  const aliases={pair:["pair","актив","інструмент","symbol","ticker"],date:["date","дата","time","час"],
    session:["session","сесія","сессия"],
    position:["position","позиція","позиция","direction","напр"],entry_model:["entry model","entry_model","model","модель"],
    bias:["bias","біас","биас"],setup:["setup","сетап","setups"],direction_type:["continuation","direction type","direction_type","cont","c/r"],
    result:["result","результат","підсум","итог"],rr:["rr","r:r","risk reward"],risk:["risk","ризик","риск"],
    entry_details:["entry details","entry_details","details","вхід","вход"],
    notes:["note","notes","нотат","заметк","коментар","комментар"],mistakes:["mistake","помилк","ошибк"]};
  const list=aliases[field]||[field];
  for(const hd of headers){ const l=hd.toLowerCase().trim();
    if(list.some(a=>l===a)) return hd; }
  for(const hd of headers){ const l=hd.toLowerCase().trim();
    if(list.some(a=>l.includes(a))) return hd; }
  return "";
}
function buildMap(){
  IMP.map={};
  let h='<p class="hint">Знайдено рядків: <b style="color:var(--text)">'+IMP.rows.length+"</b></p>"+
    '<div class="map-grid">';
  for(const [f,label] of IMP_FIELDS){
    const guess=guessHeader(f,IMP.headers); IMP.map[f]=guess;
    h+='<span class="k">'+label+'</span><select onchange="IMP.map[\''+f+'\']=this.value">'+
      '<option value="">— пропустити —</option>'+
      IMP.headers.map(hd=>'<option '+(hd===guess?"selected":"")+' value="'+esc(hd)+'">'+esc(hd)+"</option>").join("")+"</select>";
  }
  h+="</div>";
  $("#impMap").innerHTML=h;
  $("#impGo").disabled=!IMP.rows.length;
}
function normResult(v){
  const s=(v||"").toString().trim().toLowerCase();
  if(["win","tp","w","профіт","профит","+","take"].some(x=>s===x||s.startsWith(x+" ")||s===x)) return "Win";
  if(s.startsWith("tp")||s==="win") return "Win";
  if(s.startsWith("sl")||s==="loss"||s==="lose"||s==="l") return "Loss";
  if(s.startsWith("be")||s.includes("беззб")||s.includes("безуб")||s==="0") return "BE";
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
  if(!out.length){ alert("Нічого імпортувати"); return; }
  const btn=$("#impGo"); btn.disabled=true; btn.textContent="Імпортую…";
  const res=await api("POST","/api/import",out);
  await reload(); closeModal(); render();
  alert("Імпортовано угод: "+res.added);
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
let tickedView=null;                 /* цифры отсчитываются при смене раздела, а не при каждой перерисовке */
function render(){
  const v=VIEWS[S.view]?S.view:"dashboard";
  document.querySelectorAll(".nav a").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
  $("#main").innerHTML='<div class="page">'+VIEWS[v]()+"</div>";
  /* блоки обзора появляются тихо, как в макете */
  requestAnimationFrame(()=>document.querySelectorAll(".ovw .rise,.ovw .rail").forEach(el=>el.classList.add("in")));
  const fresh = tickedView!==v; tickedView=v;
  if(window.Ticker) Ticker.run($("#main"), fresh);
  if(window.PL) PL.mount();
  if(window.Tip) Tip.mount($("#main"));
}
window.addEventListener("hashchange",()=>{ S.view=location.hash.slice(1)||"dashboard"; render(); });
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ if(!$("#lightbox").hidden)closeLightbox(); else if(!$("#modal").hidden)closeModal(); }
});
$("#modal").addEventListener("click",e=>{ if(e.target.id==="modal")closeModal(); });

function markDemo(){
  const b=document.createElement("div");
  b.className="demo-badge";
  b.innerHTML='<b>Демо</b><span>Угоди зберігаються лише у вашому браузері</span>'+
              '<button type="button" onclick="DemoStore.reset()">Скинути</button>';
  document.body.appendChild(b);
}

(async function init(){
  markTheme(); markLayout(); markNum();
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
      $("#main").innerHTML='<div class="empty">Сервер не відповідає. Запусти app.py</div>';
      return;
    }
  }
  S.view=location.hash.slice(1)||"dashboard";
  if(S.view==="monthly"){ S.view="journal"; location.hash="journal"; }
  render();
})();
