/* Trading Journal — вся логика на клиенте, данные через /api */
"use strict";

/* ---------------- состояние ---------------- */
const now = new Date();
const S = {
  trades: [],
  view: "dashboard",
  selDay: isoDay(now),          // выбранный день в Journal
  jMonth: isoMonth(now),        // месяц календаря Journal
  jMode: (function(){ try{ return localStorage.getItem("tj_jmode")||"cal"; }catch(e){ return "cal"; } })(),
                                // cal | table | list
  mMonth: isoMonth(now),        // Monthly
  qYear: now.getFullYear(),     // Quarterly
  yYear: now.getFullYear(),     // Yearly
  dim: "pair",                  // Analytics — інструменти завжди заповнені, на відміну від сетапу
  filters: {},
  formShots: [],
  all: [], mRep:null, ovPeriod:"month",
  pages:{},                     // номер страницы для каждого списка сделок                // сделка, открытая во второй панели журнала
};

const TF_LIST = ["1m","3m","5m","15m","30m","1H","4H","1D","1W"];
const TF_SLOTS = ["1m","3m","5m","15m","30m","1H","4H"];
const TF_ORDER = ["1W","1D","4H","1H","30m","15m","5m","3m","1m"];
const SESSIONS = ["LONDON","NY","FRANKFURT","PH","PM"];
/* активы для подсказок в форме. Старые инструменты (форекс, золото) остаются
   в статистике полностью, но новую сделку по ним не предлагаем. */
const PAIRS_ACTIVE = ["US100","GER40","ES500"];
/* значения полей — язык интерфейса берём из T на каждый вызов, чтобы переключение
   языка без перезагрузки страницы сразу подхватывалось везде */
function DIMS(){ return [
  {k:"pair",label:T.fPair},{k:"session",label:T.fSession},{k:"position",label:T.fPosition},
  {k:"entry_model",label:T.fEntryModel},{k:"bias",label:T.fBias},{k:"setup",label:T.fSetup},
  {k:"direction_type",label:T.fDirType},{k:"result",label:T.kResSplit},{k:"mistakes",label:T.fMistakes},
  {k:"emotion",label:T.fEmotion},
]; }

/* ---------------- утилиты ---------------- */
function $(s){ return document.querySelector(s); }
function pad(n){ return (n<10?"0":"")+n; }
function isoDay(d){ return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate()); }
function isoMonth(d){ return d.getFullYear()+"-"+pad(d.getMonth()+1); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function shotSrc(s){
  if(!s.file) return s.data||"";
  return window.Pub&&Pub.on ? Pub.shot(s.file) : "/shots/"+esc(s.file);
}
function r1(v){ return Math.round(v*100)/100; }
function fmtR(v){ if(v==null||isNaN(v)) return "—"; const x=r1(v); return (x>0?"+":"")+x+"%"; }
function clsR(v){ return v>0.0001?"pos":v<-0.0001?"neg":"beclr"; }
function fmtPct(v){ return v==null?"—":(Math.round(v*10)/10)+"%"; }
/* Похоже ли это на тикер, а не на кусок текста из соседней колонки.
   Тикеры пишутся латиницей и коротко: «NAS 100», «GER40», «S&P 500».
   Кириллица, длинная фраза или отсутствие латинских букв — повод переспросить. */
function looksLikePair(v){
  v=(v||"").trim();
  if(!v) return false;
  if(/[Ѐ-ӿ]/.test(v)) return false;    // кириллица
  if(v.length>16) return false;
  if(v.split(/\s+/).length>3) return false;
  return /[A-Za-z]/.test(v);                     // хоть одна латинская буква
}
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
  /* Гість дивиться демо, але писати не може: будь-який запит, окрім
     читання, впирається у вікно «увійдіть». Перевірка стоїть тут, а не
     біля кожної кнопки, щоб жоден запис не проліз повз неї. */
  if(DEMO && window.Guest && Guest.on && method!=="GET"){
    Guest.block(); throw new Error("guest");
  }
  /* Чужий журнал: писати не можна взагалі, а читаємо тільки те, що для
     нього призначено. Підміна адреси стоїть тут одна на всі розділи. */
  if(window.Pub && Pub.on){
    if(method!=="GET"){ Pub.block(); throw new Error("pub"); }
    url = Pub.url(url);
    if(!url) throw new Error("pub");
  }
  if(DEMO) return DemoStore.handle(method,url,body);
  const res=await fetch(url,{method,credentials:"same-origin",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  /* до першого успішного завантаження 401 означає «сесії немає» — з цього
     init зробить режим гостя. Пізніше це вже протухла сесія, там вхід */
  if(res.status===401){ if(dataReady) location.href="/login"; throw new Error("API 401"); }
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
    [T.kCount, st.n, "", T.kCountTip],
    [T.kWinRate, fmtPct(st.wr), "", T.kWinRateTip],
    [T.kNetPct, fmtR(st.net), clsR(st.net), T.kNetPctTip],
    [T.kAvgRR, st.avgRR!=null?r1(st.avgRR):"—", "", T.kAvgRRTip],
    [T.kProfitFactor, st.pfTxt, "", T.kProfitFactorTip],
    [T.kResSplit, st.wins+" / "+st.losses+" / "+st.be, "small", T.kResSplitTip],
    [T.kBeSplit, st.beM+" / "+st.beP, "small", T.kBeSplitTip],
  ];
  if(!opts.compact) cells.push([T.kAvgRisk, st.avgRisk!=null?r1(st.avgRisk)+"%":"—","", T.kAvgRiskTip]);
  return '<div class="kpis">'+cells.map(c=>
    '<div class="kpi"'+(c[3]?' data-tip="'+esc(c[3])+'"':"")+
    '><div class="l">'+c[0]+'</div><div class="v '+c[2]+'">'+c[1]+'</div></div>').join("")+"</div>";
}

/* ---------------- график equity ---------------- */
function equitySVG(list){
  const arr=sortAsc(list);
  if(arr.length<2) return '<div class="empty">'+T.kEmptyChart+'</div>';
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
    '<span class="eqrange">'+T.eqMax+' '+fmtR(eq[hiI])+" · "+T.eqMin+" "+fmtR(eq[loI])+"</span>"+
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
  return '<div class="trow" onclick="openTradeRow(\''+t.id+'\')">'+
    '<span class="d">'+esc(d)+'</span><span class="p">'+esc(t.pair||"—")+" "+pos+"</span>"+
    '<span class="info">'+info+"</span>"+dtb+badge+
    '<span class="r '+clsR(r)+'">'+fmtR(r)+"</span></div>";
}
/* длинный список идёт страницами: сами строки те же, добавилась только навигация */
function tradesCard(list,title,key){
  key=key||title;
  const pg=Pagi.slice(list,key);
  const rows=pg.items.length?pg.items.map(tradeRow).join(""):'<div class="empty">'+T.tlEmpty+'</div>';
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
  let h='<div class="cal">'+T.wds.map(w=>'<div class="wd">'+w+"</div>").join("");
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
        if(t.result==="Win")  return '<i class="mk tp'+(rv?" rev":"")+'" data-tip="'+T.calTpTip+(rv?" · "+T.calRevSuffix:"")+'">TP</i>';
        if(t.result==="Loss") return '<i class="mk sl'+(rv?" rev":"")+'" data-tip="'+T.calSlTip+(rv?" · "+T.calRevSuffix:"")+'">SL</i>';
        if(t.result==="BE+")  return '<i class="mk beplus'+(rv?" rev":"")+'" data-tip="'+T.calBePlusTip+'">BE+</i>';
        return '<i class="mk be'+(rv?" rev":"")+'" data-tip="'+T.calBeMinusTip+'">BE\u2212</i>';
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
  const selects=[["result",T.fResult,["Win","Loss","BE-","BE+"]],["position",T.fPosition,["Long","Short"]],
    ["pair",T.fPair,uniqueVals("pair")],["session",T.fSession,uniqueVals("session")],
    ["setup",T.fSetup,uniqueVals("setup")],["entry_model",T.flModel,uniqueVals("entry_model")],
    ["bias",T.fBias,uniqueVals("bias")],["direction_type",T.fDirTypeFilter,["Continuation","Reversal"]]];
  let h='<div class="filters">';
  for(const [f,label,vals] of selects){
    if(!vals.length) continue;
    h+='<select onchange="setFilter(\''+f+'\',this.value)"><option value="">'+label+"</option>"+
      vals.map(v=>'<option '+(S.filters[f]===v?"selected":"")+' value="'+esc(v)+'">'+esc(f==="result"?resLabel(v):v)+"</option>").join("")+"</select>";
  }
  h+=periodBtn();
  if(Object.keys(S.filters).some(k=>S.filters[k])) h+='<button class="clear" onclick="clearFilters()">'+T.flClear+'</button>';
  return h+"</div>";
}
/* ---------- выбор даты и периода (shadcn/ui · Date Picker) ---------- */
const CAL_ICON='<svg width="13" height="13" aria-hidden="true" viewBox="0 0 24 24" fill="none">'+
  '<rect x="3" y="4.5" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.7"/>'+
  '<path d="M3 9.5h18M8 3v3M16 3v3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
const SHARE_ICON='<svg width="14" height="14" aria-hidden="true" viewBox="0 0 24 24" fill="none">'+
  '<rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.6"/>'+
  '<circle cx="8.5" cy="10" r="1.6" stroke="currentColor" stroke-width="1.5"/>'+
  '<path d="M4 17l5-4 4 3 3-2 4 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function periodBtn(){
  const f=S.filters.from||"", t=S.filters.to||"";
  const lab=(f||t) ? (DatePicker.human(f)||"…")+" — "+(DatePicker.human(t)||"…") : T.flPeriod;
  return '<button class="dbtn'+((f||t)?" set":"")+'" data-tip="'+T.flPeriodTip+'" '+
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
function OV_PERIODS(){ return [["month",T.ovPeriodMonth],["quarter",T.ovPeriodQuarter],["year",T.ovPeriodYear]]; }
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
    return {list:S.trades.filter(t=>(t.date||"").slice(0,4)===y), lab:T.ovYearSummary, when:y};
  if(S.ovPeriod==="quarter"){
    const q=Math.floor(now.getMonth()/3), from=q*3+1, to=q*3+3;
    const list=S.trades.filter(t=>{
      const k=monKey(t); if(k.slice(0,4)!==y) return false;
      const m=+k.slice(5,7); return m>=from && m<=to;
    });
    return {list, lab:T.ovQuarterSummary, when:["I","II","III","IV"][q]+" "+T.ovQuarterWord+" "+y};
  }
  const mk=isoMonth(now);
  const monthOver = now.getDate()===new Date(now.getFullYear(),now.getMonth()+1,0).getDate();
  return {list:S.trades.filter(t=>monKey(t)===mk), lab: monthOver?T.ovMonthSummary:T.ovMonthLive, when:T.months[now.getMonth()]+" "+y};
}

function ovSign(r){ return r>0.0001?"pos":r<-0.0001?"neg":"be"; }
/* в обзоре проценты пишем как в макете: два знака в итогах, один в клетках дня */
function ovFmt(v){ return (v>0?"+":"")+(v==null?0:v).toFixed(2)+"%"; }
function ovFmt1(v){ return (v>0?"+":"")+v.toFixed(1)+"%"; }
function ovWord(n){
  if(LANG==="en") return n===1?T.wordTrade:T.wordTradePl;
  const a=n%10, b=n%100;
  return a===1&&b!==11 ? T.wordTrade : (a>=2&&a<=4&&!(b>=12&&b<=14)) ? T.wordTradeFew : T.wordTradeMany;
}

/* поточний тиждень — крупний ряд зверху, в клітинці світиться результат дня */
function ovWeekHtml(){
  const byDay=groupBy(S.trades, dayKey);
  /* тиждень календарний: з понеділка по неділю, а не сім останніх днів */
  const now=new Date();
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const monday=new Date(today.getFullYear(),today.getMonth(),today.getDate()-((today.getDay()+6)%7));
  let cells="", n=0, sum=0;
  for(let i=0;i<7;i++){
    const d=new Date(monday.getFullYear(),monday.getMonth(),monday.getDate()+i);
    const key=isoDay(d), list=byDay.get(key)||[];
    const r=list.reduce((a,t)=>a+netR(t),0);
    n+=list.length; sum+=r;
    const wd=T.wds[(d.getDay()+6)%7];
    if(!list.length){
      /* будній день без угод — пропуск. Вихідні не рахуємо, сьогодні і решту
         тижня теж: ці дні ще не минули, угода може з'явитись */
      const weekend=d.getDay()===0||d.getDay()===6;
      const skip=!weekend&&d<today;
      cells+='<div class="day off'+(skip?" skip":"")+'"><span class="wd">'+wd+'</span><span class="dn">'+d.getDate()+
        '</span><span class="bot"><span class="dr">'+(skip?T.ovSkip:"·")+'</span></span></div>';
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
    '<div class="sec-lab"><span class="t">'+T.ovLastWeek+'</span>'+
    '<span class="wn">'+n+" "+ovWord(n)+'</span>'+
    '<span class="wsum '+ovSign(sum)+'">'+ovFmt(sum)+'</span>'+
    '<a href="#journal">'+T.ovWholeMonth+'</a></div>'+
    '<div class="days">'+cells+"</div></div>";
}

/* восемь показателей hairline-сеткой */
function ovStatsHtml(st){
  /* порожній період показуємо нулями, а не прочерками: у тій же сітці поруч
     стоять «0» і «0 / 0 / 0», і прочерки читались як збій, а не як «нічого» */
  const rows=[
    [T.kCount, String(st.n), "", T.kCountTip],
    [T.kWinRate, fmtPct(st.wr==null?0:st.wr), "", T.kWinRateTip],
    [T.kNetPct, ovFmt(st.net), clsR(st.net), T.kNetPctTip],
    [T.kAvgRR, String(r1(st.avgRR==null?0:st.avgRR)), "", T.kAvgRRTip],
    [T.kProfitFactor, st.pfTxt==="—"?"0":st.pfTxt, "", T.kProfitFactorTip],
    [T.kResSplit, st.wins+" / "+st.losses+" / "+st.be, "", T.kResSplitTip],
    [T.kBeSplit, st.beM+" / "+st.beP, "", T.kBeSplitTip],
    [T.kAvgRisk, r1(st.avgRisk==null?0:st.avgRisk)+"%", "", T.kAvgRiskTip],
  ];
  return '<div class="stats">'+rows.map(([l,v,c,tip])=>
    '<div class="st"'+(tip?' data-tip="'+esc(tip)+'"':"")+
    '><div class="lab">'+l+'</div><div class="val '+c+'">'+v+"</div></div>").join("")+"</div>";
}

/* сглаженная кривая по точкам */
/* линейная интерполяция, как curveLinear в ProfitLossLine */
/* Плавная кривая через все точки. Берём монотонную кубику: она проходит
   ровно по точкам и, в отличие от обычного сглаживания, не выскакивает за
   них — на графике денег это важно, иначе рисовались бы прибыли, которых
   не было. */
function plPath(pts){
  const n=pts.length;
  if(n<3) return "M"+pts.map(p=>p[0].toFixed(2)+","+p[1].toFixed(2)).join(" L");
  const dx=[],dy=[],sl=[],m=[];
  for(let i=0;i<n-1;i++){
    dx[i]=pts[i+1][0]-pts[i][0];
    dy[i]=pts[i+1][1]-pts[i][1];
    sl[i]=dx[i]===0?0:dy[i]/dx[i];
  }
  m[0]=sl[0]; m[n-1]=sl[n-2];
  for(let i=1;i<n-1;i++) m[i]=(sl[i-1]*sl[i]<=0)?0:(sl[i-1]+sl[i])/2;
  /* ограничение Фрица — Карлсона: гасит выбросы на резких перепадах */
  for(let i=0;i<n-1;i++){
    if(sl[i]===0){ m[i]=0; m[i+1]=0; continue; }
    const a=m[i]/sl[i], b=m[i+1]/sl[i], h=Math.hypot(a,b);
    if(h>3){ m[i]=3*a/h*sl[i]; m[i+1]=3*b/h*sl[i]; }
  }
  let d="M"+pts[0][0].toFixed(2)+","+pts[0][1].toFixed(2);
  for(let i=0;i<n-1;i++){
    const h=dx[i]/3;
    d+=" C"+(pts[i][0]+h).toFixed(2)+","+(pts[i][1]+m[i]*h).toFixed(2)+
       " "+(pts[i+1][0]-h).toFixed(2)+","+(pts[i+1][1]-m[i+1]*h).toFixed(2)+
       " "+pts[i+1][0].toFixed(2)+","+pts[i+1][1].toFixed(2);
  }
  return d;
}
/* тот же контур, но замкнутый на нулевую ось — под заливку */
function plArea(pts,y0){
  if(!pts.length) return "";
  return plPath(pts)+" L"+pts[pts.length-1][0].toFixed(2)+","+y0.toFixed(1)+
         " L"+pts[0][0].toFixed(2)+","+y0.toFixed(1)+" Z";
}
/* ломаная режется нулевой осью: каждый кусок красится по своему знаку */
function plSegments(pts,vals,y0){
  const segs=[]; let cur=[pts[0]], pos=vals[0]>=0;
  for(let i=1;i<pts.length;i++){
    const p=vals[i]>=0;
    if(p!==pos){
      const t=vals[i-1]/(vals[i-1]-vals[i]);            /* доля отрезка до нуля */
      const xz=pts[i-1][0]+(pts[i][0]-pts[i-1][0])*t;
      cur.push([xz,y0]); segs.push({pos:pos,pts:cur});
      cur=[[xz,y0]]; pos=p;
    }
    cur.push(pts[i]);
  }
  segs.push({pos:pos,pts:cur});
  return segs;
}

/* прибыль/убыток по календарным датам.
   Bklit UI · Profit/Loss Line как есть: ломаная (curveLinear) режется нулевой осью
   на сегменты по знаку, без заливки; нулевая строка сетки подсвечена
   (Grid highlightRowValues={[0]}); при наведении — курсор и подпись с индикатором.
   Один и тот же график на «Огляді» (год) и в журнале (месяц) — меняется только ось X. */
let plSeq=0;
/* Круглые засечки: шаг из ряда 1 / 2 / 2.5 / 5 / 10, а границы — по нему.
   Так подписи выходят ровные, а линии сетки стоят ровно на подписях. */
function niceScale(min,max,count){
  if(max===min){ max=min+1; }
  const raw=(max-min)/(count||4);
  const mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const n=raw/mag;
  const step=(n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*mag;
  const lo=Math.floor(min/step)*step, hi=Math.ceil(max/step)*step;
  const vals=[];
  for(let v=lo; v<=hi+step*1e-9; v+=step) vals.push(Math.round(v*1e6)/1e6);
  return {lo,hi,step,vals};
}

function plChart(list, opts){
  opts=opts||{};
  const title=opts.title||T.ovPnlTitle;
  const month=opts.ym||null;                       /* "YYYY-MM" — режим месяца */
  const arr=sortAsc(list);
  if(arr.length<2)
    return '<div class="shell rise"><div class="core"><div class="chart-lab">'+
      '<span class="t">'+esc(title)+'</span></div>'+
      '<div class="empty">'+T.kEmptyChart+'</div></div></div>';
  const vals=[], iso=[];
  let acc=0, peak=0, dd=0;
  for(const t of arr){
    acc+=netR(t);
    peak=Math.max(peak,acc);
    dd=Math.min(dd,acc-peak);
    vals.push(acc); iso.push((t.date||"").slice(0,10));
  }
  const W=640,H=156,pad=10;
  /* Шаг по горизонтали — одна сделка, а не один день.
     По календарю выходило рвано: в день без сделок линия стояла полкой,
     а шесть сделок за один день падали отвесной стенкой в одной точке.
     Равный шаг на сделку — та же логика, что в личном журнале. */
  const N=vals.length;
  /* Засечки берём круглые: если просто делить размах на четыре, подписи
     округляются и шаг выходит рваным — 3, 0, −3, −5, −8. */
  const sc=niceScale(Math.min(...vals,0),Math.max(...vals,0),4);
  const X=i=>(N<2?0:i/(N-1))*W;
  const Y=v=>H-pad-(v-sc.lo)/(sc.hi-sc.lo)*(H-pad*2);
  const pts=vals.map((v,i)=>[X(i),Y(v)]);
  const last=vals.length-1;
  const y0=Y(0);                                  /* высота нулевой оси */
  const grid=sc.vals.map(v=>
    '<line x1="0" y1="'+Y(v).toFixed(1)+'" x2="'+W+'" y2="'+Y(v).toFixed(1)+
    '" class="ovgrid" vector-effect="non-scaling-stroke"/>').join("");
  /* сегменты по знаку: над нулём — цвет прибыли, под нулём — цвет збитку.
     под каждым — мягкая заливка, чтобы линия не висела в пустоте */
  const id="pl"+(++plSeq);
  /* кусок из одной точки рисуется точкой из-за круглых концов — выкидываем */
  const segs=plSegments(pts,vals,y0).filter(sg=>
    sg.pts.length>1 && sg.pts.some(p=>p[0]!==sg.pts[0][0]||p[1]!==sg.pts[0][1]));
  const fill=segs.map(sg=>
    '<path d="'+plArea(sg.pts,y0)+'" fill="url(#'+id+(sg.pos?"u":"d")+')" stroke="none"/>').join("");
  const line=segs.map(sg=>
    '<path d="'+plPath(sg.pts)+'" fill="none" stroke="'+(sg.pos?"var(--up)":"var(--down)")+
    '" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>').join("");
  const grad=(sfx,col,down)=>
    '<linearGradient id="'+id+sfx+'" x1="0" y1="'+(down?"0":"1")+'" x2="0" y2="'+(down?"1":"0")+'">'+
    '<stop offset="0" stop-color="'+col+'" stop-opacity="0"/>'+
    '<stop offset="1" stop-color="'+col+'" stop-opacity=".26"/></linearGradient>';
  const svg='<svg viewBox="0 0 '+W+" "+H+'" width="100%" height="'+H+'" preserveAspectRatio="none">'+
    '<defs>'+grad("u","var(--up)",false)+grad("d","var(--down)",true)+'</defs>'+
    grid+fill+
    '<line class="plzero" x1="0" x2="'+W+'" y1="'+y0.toFixed(1)+'" y2="'+y0.toFixed(1)+'" vector-effect="non-scaling-stroke"/>'+
    line+
    '<line class="plcursor" x1="0" x2="0" y1="0" y2="'+H+'" vector-effect="non-scaling-stroke" hidden/>'+
    '<line class="plhover" stroke-linecap="round" stroke-width="7" vector-effect="non-scaling-stroke" hidden/></svg>';
  const dec=sc.step<1?1:0;
  const yax=sc.vals.slice().reverse().map(v=>"<span>"+v.toFixed(dec)+"</span>").join("");

  /* Подписи ставим по тем сделкам, что стоят в этих точках: шаг равный,
     но когда это было — всё равно видно. */
  let ticks=[];
  if(month){
    const at=[...new Set([0,Math.round((N-1)*.25),Math.round((N-1)*.5),
                          Math.round((N-1)*.75),N-1])].sort((a,b)=>a-b);
    let prev="";
    for(const i of at){
      const d=String(+iso[i].slice(8,10));
      if(d===prev) continue;
      prev=d;
      ticks.push({t:d,f:N<2?0:i/(N-1)});
    }
  }else{
    const seen=new Set();
    iso.forEach((d,i)=>{
      const m=d.slice(5,7);
      if(seen.has(m)) return;
      seen.add(m);
      const f=N<2?0:i/(N-1);
      /* слишком близкие подписи налезают друг на друга */
      if(ticks.length && f-ticks[ticks.length-1].f<.055) return;
      ticks.push({t:T.monShort[+m-1],f:f});
    });
  }
  const xax='<div class="xax">'+ticks.map(x=>
    '<span style="left:'+(x.f*100).toFixed(2)+'%">'+x.t+"</span>").join("")+"</div>";
  /* точки для подписи под курсором кладём в реестр графиков: их может быть несколько */
  if(window.PL) PL.data[id]=pts.map((p,i)=>({x:p[0],y:p[1],v:vals[i],d:iso[i]}));
  return '<div class="shell rise"><div class="core plline">'+
    '<div class="chart-lab"><span class="t">'+esc(title)+'</span>'+
    '<span class="v '+clsR(vals[last])+'">'+ovFmt(vals[last])+"</span>"+
    '<span class="dd">'+T.ovDrawdown+' '+ovFmt(dd)+"</span></div>"+
    '<div class="chart"><div class="yax">'+yax+"</div>"+
    '<div class="plwrap" data-pl="'+id+'">'+svg+'<div class="pltip" hidden></div></div></div>'+xax+"</div></div>";
}

/* прибыль/убыток за выбранный период — «Огляд».
   Раньше здесь всегда стоял год: переключаешь на месяц, цифры сверху
   меняются, а график остаётся годовым — и не сходится с ними. */
function ovEquityHtml(){
  const per=ovEquityPeriod();
  return plChart(per.list, per.opts);
}
function ovEquityPeriod(){
  const per=ovPeriod();
  if(S.ovPeriod==="month")
    return {list:per.list, opts:{title:T.ovPnlTitle+" · "+T.ovMonthWord, ym:isoMonth(new Date())}};
  if(S.ovPeriod==="quarter")
    return {list:per.list, opts:{title:T.ovPnlTitle+" · "+T.ovQuarterWord}};
  return {list:per.list, opts:{title:T.ovPnlTitle+" · "+T.railYearWord}};
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
    if(!rows.length) return '<div class="empty">'+T.railNoData+'</div>';
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
    : '<div class="empty">'+T.railNoData+'</div>';
  return '<aside class="rail"><div class="inner"><div class="cut">'+
    '<section><h3>'+T.railSessions+'<em>'+T.railYearWord+'</em></h3><div class="rows">'+share(byCount("session"))+"</div></section>"+
    '<section><h3>'+T.railInstruments+'<em>'+T.railYearWord+'</em></h3><div class="rows">'+share(byCount("pair"))+"</div></section>"+
    '<section><h3>'+T.railSetups+'<em>'+T.railNetPctWord+'</em></h3><div class="rows">'+setupRows+"</div></section>"+
    "</div></div></aside>";
}

function vDashboard(){
  if(!S.trades.length){
    /* Порожній журнал — це перший екран нової людини. Замість однієї
       кнопки даємо три шляхи: перенести з Notion (найшвидший, тому
       перший), записати руками або спершу описати свою ТС. */
    const way=(cls,fn,tag,title,text)=>
      '<button class="way'+cls+'" onclick="'+fn+'">'+
      '<em>'+T[tag]+'</em><b>'+T[title]+'</b><span>'+T[text]+'</span></button>';
    return '<div class="vhead"><h1>'+T.ovTitle+'</h1></div>'+
      '<div class="card"><div class="in" style="padding:26px 24px">'+
      '<div style="font-size:20px;font-weight:600;letter-spacing:-.01em">'+T.bgTitle+'</div>'+
      '<div class="hint" style="margin-top:8px;max-width:62ch;line-height:1.6">'+T.bgLead+'</div>'+
      '<div class="begin">'+
        way(" main","__notion.open()","bgNotionTag","bgNotionTitle","bgNotionText")+
        way("","openForm()","bgTradeTag","bgTradeTitle","bgTradeText")+
        way("","location.hash='ts'","bgTsTag","bgTsTitle","bgTsText")+
      '</div></div></div>';
  }
  const per=ovPeriod(), st=calc(per.list);
  const rs=per.list.map(netR);
  const best=rs.length?Math.max(...rs):null, worst=rs.length?Math.min(...rs):null;
  const btns=OV_PERIODS().map(([k,l])=>
    '<button class="'+(S.ovPeriod===k?"on":"")+'" onclick="ovSetPeriod(\''+k+'\')">'+l+"</button>").join("");
  /* період порожній, а журнал ні — не показуємо самі нулі, а кажемо чому
     і коли була остання угода (дату цифрами: відмінок місяця в трьох мовах різний) */
  let note="";
  if(!per.list.length && S.trades.length){
    const last=S.trades.map(dayKey).filter(Boolean).sort().pop();
    note='<div class="pnote">'+T.ovPeriodEmpty+
      (last ? " · "+T.ovLastTradeOn+" "+last.split("-").reverse().join(".") : "")+"</div>";
  }

  return '<div class="ovw">'+
    '<div class="ohead"><h1>'+T.ovTitle+'</h1><div class="per">'+btns+"</div></div>"+
    '<div class="flow">'+
      ovWeekHtml()+
      '<div class="shell rise"><div class="core">'+
        '<div class="sum"><div><div class="lab">'+per.lab+"</div>"+
        '<div class="big '+clsR(st.net)+'">'+ovFmt(st.net)+"</div>"+note+"</div>"+
        '<div class="when">'+per.when+"</div>"+
        '<div class="right"><div class="lab">'+T.ovBestWorst+'</div>'+
        '<div class="v">'+ovFmt(best==null?0:best)+" · "+ovFmt(worst==null?0:worst)+"</div></div></div>"+
        ovStatsHtml(st)+
      "</div></div>"+
      ovEquityHtml()+
    "</div>"+
    ovRailHtml()+
  "</div>";
}

/* ---------- Journal: живой журнал месяца ---------- */
function vJournal(){
  const monthTrades=S.trades.filter(t=>monKey(t)===S.jMonth);
  const st=calc(monthTrades);
  /* шапка: что смотрим и отдельное действие. Перемотка месяца — в самой карточке */
  const modeTabs='<div class="seg-tabs">'+
    '<button class="'+(S.jMode==="cal"?"on":"")+'" data-tip="'+T.jrCalTabTip+'" onclick="setJMode(\'cal\')">'+T.jrCalTab+'</button>'+
    '<button class="'+(S.jMode==="table"?"on":"")+'" data-tip="'+T.jrTableTabTip+'" onclick="setJMode(\'table\')">'+T.jrTableTab+'</button>'+
    '<button class="'+(S.jMode==="list"?"on":"")+'" data-tip="'+T.jrAllTabTip+'" onclick="setJMode(\'list\')">'+T.jrAllTab+'</button>'+
    "</div>";
  const shareBtn='<button class="jact" data-tip="'+T.jrShareBtnTip+'" data-ym="'+S.jMonth+
    '" onclick="openShare(this.dataset.ym)">'+SHARE_ICON+T.jrShareBtn+"</button>";

  let h='<div class="jhead"><h1>'+T.jrTitle+'</h1>'+modeTabs;
  if(S.jMode==="list"){
    h+="</div>";
    const list=sortDesc(applyFilters(S.trades));
    return h+filterBar()+tradesCard(list,T.jrAllTab+" · "+list.length,"all");
  }
  h+='<div class="tools">'+shareBtn+"</div></div>";

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
  const dayLabel=dsel.getDate()+" "+T.monthsGen[dsel.getMonth()]+", "+T.wds[(dsel.getDay()+6)%7];

  let chips="";
  if(dayTrades.length){
    chips='<div class="chips">'+
      '<span class="chip"><b>'+dst.n+"</b> "+T.abbrTrades+"</span>"+
      '<span class="chip '+(dst.net>0?"pos":dst.net<0?"neg":"")+'">'+fmtR(dst.net)+"</span>"+
      (dst.wr!=null?'<span class="chip">WR <b>'+fmtPct(dst.wr)+"</b></span>":"")+
      (dst.avgRR!=null?'<span class="chip">'+T.kAvgRRShort+' <b>'+r1(dst.avgRR)+"</b></span>":"")+
      "</div>";
  }
  const dayPanel =
    '<div class="card daypanel"><h3>'+dayLabel+"</h3>"+chips+
    (mistakes.length?'<div class="mistline">'+T.jrMistakesPrefix+' <span class="neg">'+mistakes.join(" · ")+"</span></div>":"")+
    (dayTrades.length
      ? '<div class="tlist">'+dayTrades.map((t,i)=>dayTradeHtml(t,dayTrades.length===1||i===0)).join("")+"</div>"
      : '<div class="empty">'+T.tlEmpty+'</div>')+
    '<button class="addday" onclick="openForm(null,\''+S.selDay+'\')">'+T.jrAddDayBtn+'</button>'+
    "</div>";

  const leftPane = S.jMode==="table"
    ? monthTableHtml(monthTrades)
    : '<div class="card jpane jpane-cal"><div class="panehead">'+monthNavHtml()+"</div>"+
      calHtml(S.jMonth,"pickDay",S.selDay)+
      "</div>";
  /* панель дня живёт в гнезде: так её высота равна левой половине, а не тянет страницу вниз */
  h+='<div class="jgrid">'+leftPane+'<div class="dayslot">'+dayPanel+"</div></div>";

  /* месяц целиком: динамика, сетапы, разрезы */
  if(monthTrades.length){
    h+=plChart(monthTrades,{title:T.jrMonthEquity,ym:S.jMonth});
    h+=bestWorstHtml(monthTrades);
    h+=beReportHtml(monthTrades);
  }
  return h;
}

/* Перемотка месяца живёт в самой карточке журнала — рядом с тем, что она листает.
   Одной группой: ‹ місяць › и «Сьогодні», все одинаковыми кнопками. */
function monthNavHtml(){
  const [Y,M]=S.jMonth.split("-").map(Number);
  return '<div class="mnav">'+
    '<button class="nb" aria-label="'+T.jrPrevMonth+'" data-tip="'+T.jrPrevMonth+'" onclick="shiftJMonth(-1)">‹</button>'+
    '<button class="lb" data-tip="'+T.jrPickDayTip+'" onclick="pickDate(this)">'+
      CAL_ICON+T.months[M-1]+" "+Y+"</button>"+
    '<button class="nb" aria-label="'+T.jrNextMonth+'" data-tip="'+T.jrNextMonth+'" onclick="shiftJMonth(1)">›</button>'+
    '<span class="sep"></span>'+
    '<button class="tb" data-tip="'+T.jrTodayTip+'" onclick="goToday()">'+T.jrToday+'</button>'+
    "</div>";
}

/* вид журнала: календарь, таблица месяца или все сделки. Выбор запоминаем */
function setJMode(v){
  S.jMode=v; S.pages={};
  try{ localStorage.setItem("tj_jmode",v); }catch(e){}
  render();
}

/* месяц таблицей: те же угоди, что в календаре, но подряд и с колонками */
function monthTableHtml(list){
  if(!list.length)
    return '<div class="card jpane jpane-list"><h3>'+T.jrMonthTrades+
      '<span class="hr">'+monthNavHtml()+'</span></h3>'+
      '<div class="empty">'+T.jrMonthEmpty+'</div></div>';
  const rows=sortAsc(list).map(t=>{
    const r=netR(t);
    const day=(t.date||"").slice(0,10);
    const dt=dirType(t);
    return '<tr class="'+(day===S.selDay?"sel":"")+'" onclick="pickDay(\''+day+'\')">'+
      '<td class="dt">'+esc(day.slice(8,10)+"."+day.slice(5,7))+
        '<i>'+esc((t.date||"").slice(11,16))+"</i></td>"+
      "<td>"+esc(t.pair||"—")+"</td>"+
      '<td>'+(t.position?'<span class="badge '+(t.position==="Long"?"long":"short")+'">'+esc(t.position)+"</span>":"—")+"</td>"+
      "<td>"+esc(t.session||"—")+"</td>"+
      '<td class="wide">'+esc(t.setup||"—")+"</td>"+
      '<td>'+(dt?'<span class="badge '+(dt==="Reversal"?"rev":"cont")+'">'+(dt==="Reversal"?"REV":"CONT")+"</span>":"—")+"</td>"+
      '<td><span class="badge '+(t.result==="Win"?"win":t.result==="Loss"?"loss":t.result==="BE+"?"beplus":"be")+'">'+
        resLabel(t.result)+"</span></td>"+
      '<td class="num">'+(t.rr!=null&&t.rr!==""?r1(t.rr):"—")+"</td>"+
      '<td class="num '+clsR(r)+'">'+fmtR(r)+"</td></tr>";
  }).join("");
  return '<div class="card jpane jpane-list"><h3>'+T.jrMonthTrades+
    '<span class="hr"><em>'+list.length+' '+T.abbrPieces+'</em>'+monthNavHtml()+"</span></h3>"+
    '<div class="mtwrap"><table class="mtable">'+
    "<thead><tr><th>"+T.fDate+"</th><th>"+T.fPair+"</th><th>"+T.fPosition+"</th><th>"+T.fSession+"</th>"+
    '<th class="wide">'+T.fSetup+'</th><th>'+T.jrTypeCol+'</th><th>'+T.fResult+'</th><th class="num">RR</th><th class="num">'+T.jrTotalCol+'</th></tr></thead>'+
    "<tbody>"+rows+"</tbody></table></div></div>";
}

/* сделка в панели дня: строка-заголовок и под ней вся карточка целиком.
   Первая раскрыта сразу, остальные — по клику, чтобы день с пятью угодами
   не превращался в простыню */
function dayTradeHtml(t, open){
  const r=netR(t);
  const pos=t.position?'<span class="badge '+(t.position==="Long"?"long":"short")+'">'+esc(t.position)+"</span>":"";
  const dt=dirType(t);
  const dtb=dt?'<span class="badge '+(dt==="Reversal"?"rev":"cont")+'">'+(dt==="Reversal"?"REV":"CONT")+"</span>":"";
  const badge='<span class="badge '+(t.result==="Win"?"win":t.result==="Loss"?"loss":t.result==="BE+"?"beplus":"be")+'">'+resLabel(t.result)+"</span>";
  return '<details class="dtrade"'+(open?" open":"")+'>'+
    '<summary><span class="p">'+esc(t.pair||"—")+" "+pos+"</span>"+
      '<span class="d">'+esc((t.date||"").slice(11,16))+"</span>"+dtb+badge+
      '<span class="r '+clsR(r)+'">'+fmtR(r)+"</span></summary>"+
    '<div class="dbody">'+tradeBodyHtml(t)+
      '<div class="dact">'+
        '<button class="btn" onclick="openForm(\''+t.id+'\')">'+T.tcEdit+'</button>'+
        '<button class="btn danger" onclick="delTrade(\''+t.id+'\')">'+T.tcDelete+'</button>'+
      "</div></div></details>";
}

function shiftJMonth(d){ const [y,m]=S.jMonth.split("-").map(Number); const dt=new Date(y,m-1+d,1); S.jMonth=isoMonth(dt); S.pages={}; render(); }
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
    ? T.beVerdictPos
    : delta<-0.001
      ? T.beVerdictNeg
      : T.beVerdictZero;
  const bar=(a,b)=>{
    const m=Math.max(a,b,0.001);
    return '<div class="bebar"><span class="t" style="width:'+(a/m*100)+'%;background:var(--up)"></span></div>'+
           '<div class="bebar"><span class="t" style="width:'+(b/m*100)+'%;background:var(--down)"></span></div>';
  };
  return '<div class="card"><h3>'+T.beTitle+'</h3><div class="in">'+
    '<div class="begrid">'+
      '<div class="becell"><div class="l">'+T.beMinusLabel+'</div>'+
        '<div class="v pos">+'+r1(saved)+'%</div><div class="s">'+minus.length+' '+T.beMinusDesc+'</div></div>'+
      '<div class="becell"><div class="l">'+T.bePlusLabel+'</div>'+
        '<div class="v neg">\u2212'+r1(lost)+'%</div><div class="s">'+plus.length+' '+T.bePlusDesc+'</div></div>'+
      '<div class="becell"><div class="l">'+T.beNetLabel+'</div>'+
        '<div class="v '+clsR(delta)+'">'+fmtR(delta)+'</div><div class="s">'+verdict+'</div></div>'+
      '<div class="becell"><div class="l">'+T.beShareLabel+'</div>'+
        '<div class="v beclr">'+share+'%</div><div class="s">'+be.length+' '+T.beOf+' '+list.length+' '+T.wordTradeMany+'</div></div>'+
    "</div>"+bar(saved,lost)+
    '<div class="behint">'+T.beHint+'</div>'+
    "</div></div>";
}

/* ---------- разрезы месяца ---------- */
function bestWorstHtml(list){
  const dims=[["setup",T.fSetup],["pair",T.fPair],["entry_model",T.fEntryModel],["session",T.fSession],
              ["direction_type",T.fDirType],["bias",T.fBias],["position",T.fPosition]];
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
    cells+='<div class="cell"><div class="t">'+T.fMistakes+'</div>'+
      mist.map(m=>'<div class="row"><span class="k">'+esc(m.name)+' · '+m.n+'</span><span class="v '+clsR(m.net)+'">'+fmtR(m.net)+"</span></div>").join("")+"</div>";
  }
  return cells?'<div class="card"><h3>'+T.bwTitle+'</h3><div class="bw">'+cells+"</div></div>":"";
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
    const flag = rows.length>1 ? (i===0?' <span class="tick best">'+T.dtBestTag+'</span>':(i===rows.length-1?' <span class="tick worst">'+T.dtWorstTag+'</span>':"")) : "";
    return "<tr><td>"+esc(g.name)+flag+"</td><td>"+g.st.n+"</td><td>"+fmtPct(g.st.wr)+
      '</td><td class="'+clsR(g.st.net)+'">'+fmtR(g.st.net)+"</td></tr>";
  }).join("");
  return '<div class="rep-card"><h4>'+esc(label)+'</h4><table class="simple mini">'+
    "<tr><th>"+esc(label)+"</th><th>"+T.dtColCount+"</th><th>WR</th><th>"+T.colTotal+"</th></tr>"+body+"</table></div>";
}
function openMonthReport(ym){
  S.mRep=ym;
  const [Y,M]=ym.split("-").map(Number);
  const list=S.trades.filter(t=>monKey(t)===ym);
  const st=calc(list);
  const title=T.months[M-1]+" "+Y;
  let h='<div class="m-head"><h2>'+title+' <span class="'+clsR(st.net)+'" style="font-family:var(--mono)">'+fmtR(st.net)+"</span></h2>"+
    '<button class="x" onclick="closeModal()">×</button></div><div class="m-body rep">';
  if(!list.length){ h+='<div class="empty">'+T.mrNoTrades+'</div>'; }
  else{
    h+=kpiHtml(st);
    h+='<div class="card"><h3>'+T.mrDynamics+'</h3><div class="in">'+equitySVG(list)+"</div></div>";

    /* дни */
    const byDay=[...groupBy(list,dayKey).entries()].sort((a,b)=>a[0]<b[0]?-1:1)
      .map(([d,arr])=>({d,st:calc(arr)}));
    const best=byDay.slice().sort((a,b)=>b.st.net-a.st.net);
    h+='<div class="rep-sec">'+T.mrDaysSection+'</div><div class="rep-grid">'+
      '<div class="rep-card scrolly"><h4>'+T.mrAllDays+' ('+byDay.length+")</h4>"+
      '<table class="simple mini"><tr><th>'+T.mrColDay+'</th><th>'+T.dtColCount+'</th><th>WR</th><th>'+T.colTotal+'</th></tr>'+
      byDay.map(x=>{
        const dt=new Date(x.d+"T00:00");
        return '<tr class="click" data-day="'+x.d+'" onclick="gotoDayFromReport(this.dataset.day)">'+
          "<td>"+dt.getDate()+" "+T.monShort[dt.getMonth()]+", "+T.wds[(dt.getDay()+6)%7]+"</td>"+
          "<td>"+x.st.n+"</td><td>"+fmtPct(x.st.wr)+'</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div>"+
      '<div class="rep-card"><h4>'+T.mrExtremeDays+'</h4><table class="simple mini c3">'+
      '<tr><th>'+T.mrColDay+'</th><th>'+T.dtColCount+'</th><th>'+T.colTotal+'</th></tr>'+
      best.slice(0,3).concat(best.slice(-3).reverse()).filter((v,i,a)=>a.indexOf(v)===i).map(x=>{
        const dt=new Date(x.d+"T00:00");
        return "<tr><td>"+dt.getDate()+" "+T.monShort[dt.getMonth()]+"</td><td>"+x.st.n+
          '</td><td class="'+clsR(x.st.net)+'">'+fmtR(x.st.net)+"</td></tr>";
      }).join("")+"</table></div></div>";

    /* разрезы */
    h+='<div class="rep-sec">'+T.mrCutsSection+'</div><div class="rep-grid">'+
      dimTable(list,"setup",T.fSetup)+dimTable(list,"pair",T.mrAsset)+
      dimTable(list,"session",T.fSession)+dimTable(list,"entry_model",T.fEntryModel)+
      dimTable(list,"direction_type",T.fDirType)+dimTable(list,"position",T.fPosition)+
      "</div>";

    /* ошибки */
    const mist=[...groupBy(list,t=>t.mistakes).entries()].map(([name,arr])=>({name,st:calc(arr)}))
      .sort((a,b)=>a.st.net-b.st.net);
    const withM=list.filter(t=>(t.mistakes||"").trim()), noM=list.filter(t=>!(t.mistakes||"").trim());
    h+='<div class="rep-sec">'+T.fMistakes+'</div>';
    if(mist.length){
      h+='<div class="rep-grid"><div class="rep-card"><h4>'+T.mrCostly+'</h4><table class="simple mini">'+
        "<tr><th>"+T.mrMistakeCol+"</th><th>"+T.dtColCount+"</th><th>"+T.colTotal+"</th></tr>"+
        mist.map(m=>"<tr><td>"+esc(m.name)+"</td><td>"+m.st.n+'</td><td class="'+clsR(m.st.net)+'">'+fmtR(m.st.net)+"</td></tr>").join("")+
        "</table></div>"+
        '<div class="rep-card"><h4>'+T.mrWithVsWithout+'</h4><table class="simple mini">'+
        "<tr><th></th><th>"+T.dtColCount+"</th><th>WR</th><th>"+T.colTotal+"</th></tr>"+
        '<tr><td>'+T.mrWithMark+'</td><td>'+withM.length+"</td><td>"+fmtPct(calc(withM).wr)+'</td><td class="'+clsR(calc(withM).net)+'">'+fmtR(calc(withM).net)+"</td></tr>"+
        '<tr><td>'+T.mrWithoutMark+'</td><td>'+noM.length+"</td><td>"+fmtPct(calc(noM).wr)+'</td><td class="'+clsR(calc(noM).net)+'">'+fmtR(calc(noM).net)+"</td></tr>"+
        "</table></div></div>";
    } else h+='<div class="hint" style="padding:4px 0 12px">'+T.mrNoMistakesHint+'</div>';

    /* риск */
    const offSize=list.filter(t=>(t.risk||1)!==1), onSize=list.filter(t=>(t.risk||1)===1);
    if(offSize.length){
      h+='<div class="rep-sec">'+T.mrRiskSection+'</div><div class="rep-grid"><div class="rep-card"><h4>'+T.mrRiskDeviation+'</h4>'+
        '<table class="simple mini"><tr><th></th><th>'+T.dtColCount+'</th><th>WR</th><th>'+T.colTotal+'</th></tr>'+
        '<tr><td>'+T.mrRisk1+'</td><td>'+onSize.length+"</td><td>"+fmtPct(calc(onSize).wr)+'</td><td class="'+clsR(calc(onSize).net)+'">'+fmtR(calc(onSize).net)+"</td></tr>"+
        '<tr><td>'+T.mrRiskOther+'</td><td>'+offSize.length+"</td><td>"+fmtPct(calc(offSize).wr)+'</td><td class="'+clsR(calc(offSize).net)+'">'+fmtR(calc(offSize).net)+"</td></tr>"+
        "</table></div></div>";
    }
    h+='<div class="rep-sec">'+T.mrBeSectionShort+'</div>'+beReportHtml(list);
    h+='<div class="rep-sec">'+T.mrAllTradesSection+'</div><div class="card"><div class="tlist">'+
      sortAsc(list).map(tradeRow).join("")+"</div></div>";
  }
  h+='</div><div class="m-foot"><button class="btn primary" data-ym="'+ym+'" onclick="closeModal();openShare(this.dataset.ym)">'+T.jrShareBtn+'</button>'+
    '<button class="btn" data-ym="'+ym+'" onclick="gotoMonthFromReport(this.dataset.ym)">'+T.mrOpenInJournal+'</button>'+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">'+T.mrClose+'</button></div>';
  openModal(h);
}

/* ---------- Quarterly ---------- */
function vQuarterly(){
  const Y=S.qYear;
  let h='<div class="vhead"><h1>'+T.qtTitle+'</h1><div class="right">'+
    '<button class="navbtn" onclick="S.qYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.qYear++;render()">›</button></div></div>';
  h+='<div class="qgrid">';
  for(let q=0;q<4;q++){
    const months=[q*3+1,q*3+2,q*3+3];
    const keys=months.map(m=>Y+"-"+pad(m));
    const list=S.trades.filter(t=>keys.includes(monKey(t)));
    const st=calc(list);
    const perMonth=months.map(m=>{
      const ml=S.trades.filter(t=>monKey(t)===Y+"-"+pad(m));
      return {m,label:T.monShort[m-1],net:ml.reduce((a,t)=>a+netR(t),0),n:ml.length};
    });
    const withTrades=perMonth.filter(x=>x.n);
    let bw="";
    if(withTrades.length>1){
      const b=withTrades.reduce((a,c)=>c.net>a.net?c:a), w=withTrades.reduce((a,c)=>c.net<a.net?c:a);
      bw='<div class="qr"><span>'+T.qBestMonth+'</span><b class="'+clsR(b.net)+'">'+b.label+" "+fmtR(b.net)+"</b></div>"+
         '<div class="qr"><span>'+T.qWorstMonth+'</span><b class="'+clsR(w.net)+'">'+w.label+" "+fmtR(w.net)+"</b></div>";
    }
    const maxAbs=Math.max(0.001,...perMonth.map(x=>Math.abs(x.net)));
    const bars=perMonth.map(x=>{
      const wPct=Math.abs(x.net)/maxAbs*100;
      const color=x.net>0?"var(--up)":x.net<0?"var(--down)":"var(--line)";
      return '<div class="mbar"><span>'+x.label+'</span><span class="track"><i style="left:0;width:'+Math.max(x.n?4:0,wPct)+'%;background:'+color+'"></i></span><span class="val">'+(x.n?fmtR(x.net):"—")+"</span></div>";
    }).join("");
    h+='<div class="qcard"><h4>Q'+(q+1)+" "+Y+'<span class="netr '+clsR(st.net)+'">'+(st.n?fmtR(st.net):"—")+"</span></h4>"+
      '<div class="rows">'+
      '<div class="qr"><span>'+T.qTrades+'</span><b>'+st.n+"</b></div>"+
      '<div class="qr"><span>'+T.kWinRate+'</span><b>'+fmtPct(st.wr)+"</b></div>"+
      '<div class="qr"><span>'+T.kAvgRRShort+'</span><b>'+(st.avgRR!=null?r1(st.avgRR):"—")+"</b></div>"+
      '<div class="qr"><span>'+T.kProfitFactor+'</span><b>'+st.pfTxt+"</b></div>"+bw+
      '<div style="margin-top:8px">'+bars+"</div></div></div>";
  }
  return h+"</div>";
}

/* ---------- Yearly ---------- */
function vYearly(){
  const Y=S.yYear;
  const list=S.trades.filter(t=>(t.date||"").slice(0,4)==String(Y));
  const st=calc(list);
  let h='<div class="vhead"><h1>'+T.yrTitle+'</h1><div class="right">'+
    '<button class="navbtn" onclick="S.yYear--;render()">‹</button><span class="perlabel">'+Y+'</span><button class="navbtn" onclick="S.yYear++;render()">›</button></div></div>';
  h+=kpiHtml(st);
  if(list.length) h+='<div class="card"><h3>'+T.yrEquityTitle+'</h3><div class="in">'+equitySVG(list)+"</div></div>";
  h+=beReportHtml(list);
  /* месяцы */
  let mrows="";
  for(let m=1;m<=12;m++){
    const ml=list.filter(t=>monKey(t)===Y+"-"+pad(m));
    if(!ml.length) continue;
    const ms=calc(ml);
    mrows+='<tr class="click" onclick="openMonthReport(\''+Y+"-"+pad(m)+'\')">'+
      "<td>"+T.months[m-1]+' <span class="go">'+T.yrBreakdown+'</span></td><td>'+ms.n+"</td><td>"+fmtPct(ms.wr)+'</td><td class="'+clsR(ms.net)+'">'+fmtR(ms.net)+"</td><td>"+(ms.avgRR!=null?r1(ms.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>'+T.yrMonthsTitle+'</h3><table class="simple"><tr><th>'+T.yrColMonth+'</th><th>'+T.kCount+'</th><th>'+T.kWinRate+'</th><th>'+T.kNetPct+'</th><th>'+T.kAvgRRShort+'</th></tr>'+
    (mrows||'<tr><td colspan="5" class="empty">'+T.yrNoData+'</td></tr>')+"</table></div>";
  /* кварталы */
  let qrows="";
  for(let q=0;q<4;q++){
    const keys=[1,2,3].map(i=>Y+"-"+pad(q*3+i));
    const ql=list.filter(t=>keys.includes(monKey(t)));
    if(!ql.length) continue;
    const qs=calc(ql);
    qrows+="<tr><td>Q"+(q+1)+"</td><td>"+qs.n+"</td><td>"+fmtPct(qs.wr)+'</td><td class="'+clsR(qs.net)+'">'+fmtR(qs.net)+"</td><td>"+(qs.avgRR!=null?r1(qs.avgRR):"—")+"</td></tr>";
  }
  h+='<div class="card"><h3>'+T.qtTitle+'</h3><table class="simple"><tr><th>'+T.yrColQuarter+'</th><th>'+T.kCount+'</th><th>'+T.kWinRate+'</th><th>'+T.kNetPct+'</th><th>'+T.kAvgRRShort+'</th></tr>'+
    (qrows||'<tr><td colspan="5" class="empty">'+T.yrNoData+'</td></tr>')+"</table></div>";
  return h;
}

/* ---------- Analytics ---------- */
function vAnalytics(){
  const list=applyFilters(S.trades);
  let h='<div class="vhead"><h1>'+T.anTitle+'</h1><span class="sub">'+list.length+" "+T.anSampleSuffix+"</span></div>";
  h+=filterBar();
  h+='<div class="dims">'+DIMS().map(d=>'<button class="pill '+(S.dim===d.k?"on":"")+'" onclick="S.dim=\''+d.k+'\';render()">'+d.label+"</button>").join("")+"</div>";
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
  h+='<div class="card"><h3>'+T.anResultsPrefix+' '+esc(DIMS().find(d=>d.k===S.dim).label)+"</h3>"+
    '<div class="ahead"><span>'+T.anColName+'</span><span>'+T.kCount+'</span><span>'+T.kWinRate+'</span><span>'+T.kAvgRRShort+'</span><span>'+T.kNetPct+'</span></div>'+
    (rows||'<div class="empty">'+T.anNoData+'</div>')+"</div>";
  h+=window.__links ? __links.html(list) : "";      /* зв'язки, static/links.js */
  return h;
}

/* ================= МОДАЛКИ ================= */
function openModal(html){ $("#modalBox").innerHTML=html; $("#modal").hidden=false; document.body.style.overflow="hidden"; }
function closeModal(){
  if(window.Panel && Panel.isOpen()) Panel.close();
  $("#modal").hidden=true; document.body.style.overflow="";
  S.formShots=[]; document.removeEventListener("paste", onPasteShot);
}

/* ---------- вид левого меню: current, flat, icons ---------- */
function setNav(v){
  document.documentElement.setAttribute("data-nav",v);
  try{ localStorage.setItem("tj_nav",v); }catch(e){}
  render();
}
function markLayout(){}

/* ---------- тема ---------- */
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
  b.innerHTML = (dark ? sun : moon) + "<span>" + (dark ? T.themeLight : T.themeDark) + "</span>";
  b.title = dark ? T.themeToLight : T.themeToDark;
}

$("#modal") && null;

function openLightbox(src){ $("#lightboxImg").src=src; $("#lightbox").hidden=false; }
function closeLightbox(){ $("#lightbox").hidden=true; $("#lightboxImg").src=""; }

/* ---------- просмотр сделки ---------- */
/* содержимое карточки сделки четырьмя блоками: итог, как торговал, записи, графики.
   Обёртку задаёт вызывающий */
function tradeBodyHtml(t){
  const r=netR(t);

  /* 1. итог сделки. Инструмент, направление, время и общий процент уже стоят
     в шапке карточки — повторять их здесь незачем, от этого и была каша */
  const facts=[[T.fResult,resLabel(t.result)||"—",""],
    ["RR",(t.rr!=null&&t.rr!=="")?r1(t.rr):"—",""],
    [T.fRisk,(t.risk!=null&&t.risk!=="")?r1(t.risk)+"%":"—",""]];
  let h='<div class="tstats">'+facts.map(f=>
    '<div class="st"><div class="lab">'+f[0]+'</div><div class="val '+f[2]+'">'+esc(f[1])+"</div></div>").join("")+"</div>";

  /* 2. обстоятельства входа. Заполненное показываем, пустое собираем одной
     строкой внизу: видно, чего не хватает, но экран это не съедает */
  const ctx=[[T.fSession,t.session],[T.fBias,t.bias],[T.fEntryModel,t.entry_model],
    [T.fSetup,t.setup],[T.fDirTypeFilter,dirType(t)]];
  h+=section(T.tcHowTraded,
    '<div class="tfields">'+ctx.filter(f=>f[1]).map(f=>
      '<div class="fr"><span class="l">'+f[0]+'</span><span class="v">'+esc(f[1])+"</span></div>").join("")+"</div>",
    ctx.filter(f=>!f[1]).map(f=>f[0]));

  /* 3. записи руками */
  const notes=[[T.fEntryDetails,"entry_details"],[T.fNotes,"notes"],
    [T.fMistakes,"mistakes"],[T.tcComments,"comments"]];
  const wrote=notes.filter(f=>(t[f[1]]||"").trim());
  h+=section(T.tcWhatWrote,
    wrote.map(f=>'<div class="tnote"><div class="l">'+f[0]+'</div><div class="v">'+
      esc(t[f[1]].trim())+"</div></div>").join(""),
    notes.filter(f=>!(t[f[1]]||"").trim()).map(f=>f[0]));

  /* 4. графики: подпись таймфрейма стоит на самой картинке */
  const shots=(t.screenshots||[]).slice().sort((a,b)=>TF_ORDER.indexOf(a.tf)-TF_ORDER.indexOf(b.tf));
  h+=section(T.tcCharts,
    shots.length ? '<div class="charts">'+shots.map(s=>
      '<div class="chart-item"><div class="l">'+esc(s.tf||"chart")+'</div><img loading="lazy" src="'+
      shotSrc(s)+'" onclick="openLightbox(this.src)"></div>').join("")+"</div>" : "",
    shots.length ? [] : [T.tcNoScreens]);
  return h;
}

/* Раздел карточки. Пустые поля не занимают по строке каждое — они уходят
   одной приглушённой строкой «не заповнено: …» */
function section(title,body,missing){
  if(!body && !missing.length) return "";
  return '<section class="tsec"><h3>'+title+"</h3>"+body+
    (missing.length ? '<div class="tempty">'+(body?T.tcNotFilled+" ":"")+
      esc(missing.join(", "))+"</div>" : "")+"</section>";
}

/* карточка сделки выезжающей панелью — остаётся для узких экранов и отчётов */
function openTrade(id){
  const t=(S.all.length?S.all:S.trades).find(x=>x.id===id); if(!t) return;
  const r=netR(t);
  const pos=t.position?'<span class="badge '+(t.position==="Long"?"long":"short")+'">'+esc(t.position)+"</span>":"";
  const when=(t.date||"").replace("T"," ").slice(0,16);
  const h='<div class="m-head thead"><div class="ttl"><h2>'+esc(t.pair||T.tradeDefaultName)+"</h2>"+pos+
    '<span class="dt">'+esc(when)+"</span></div>"+
    '<span class="res '+clsR(r)+'">'+fmtR(r)+"</span>"+
    '<button class="x" aria-label="'+T.mrClose+'" data-tip="'+T.closeEscTip+'" onclick="closeModal()">×</button></div>'+
    '<div class="m-body trade">'+tradeBodyHtml(t)+"</div>"+
    '<div class="m-foot"><button class="btn primary" onclick="openForm(\''+t.id+'\')">'+T.tcEdit+'</button>'+
    '<span class="sp"></span>'+
    '<button class="btn danger" onclick="delTrade(\''+t.id+'\')">'+T.tcDelete+'</button></div>';
  Sheet.open(h);
}

function findTrade(id){ return (S.all.length?S.all:S.trades).find(x=>x.id===id); }
/* клик по строке — карточка выезжает справа */
function openTradeRow(id){ openTrade(id); }
async function delTrade(id){
  if(!await Ask.yes(T.confirmDeleteTrade, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
  await api("DELETE","/api/trades/"+id);
  await reload(); closeModal(); render();
}

/* ---------- форма сделки ---------- */
function dl(id,vals){ return '<datalist id="'+id+'">'+vals.map(v=>'<option value="'+esc(v)+'">').join("")+"</datalist>"; }

function openForm(id, presetDay){
  /* гостя спиняємо тут, а не на «зберегти»: нечесно давати заповнити
     всю форму й аж тоді сказати, що записати нікуди */
  if(window.Guest && Guest.block(T.gsGateTrade)) return;
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
      '<button type="button" class="more" onclick="showOwn(\''+field+'\')" title="'+T.fmOwnValueTip+'">＋</button></div>'+
      '<input class="qinput" id="fld_'+field+'"'+(num?' type="number" step="0.25" min="0"':"")+
      ' value="'+esc(cur)+'" placeholder="'+esc(ph||"")+'" autocomplete="off"'+
      (cur&&!known?"":" hidden")+' oninput="markQuick();calcOutcome()">';
  };

  const models=[...new Set(["cisd",...topVals("entry_model",4)])];
  const setups=topVals("setup",4);
  const mistakes=topVals("mistakes",5);
  /* інструменти беремо з журналу, як моделі й сетапи. Жорсткий PAIRS_ACTIVE
     підсовував US100/ES500, яких у журналі немає, тож свій індекс щоразу
     вписували руками — звідси «NAS 100» і «NAS100» поруч. Список лишаємо
     тільки як підказку для порожнього журналу */
  const ownPairs=topVals("pair",5);
  const pairs=ownPairs.length?ownPairs:PAIRS_ACTIVE;

  let h='<div class="m-head"><h2>'+(t?T.fmEditTitle:T.fmNewTitle)+
    '</h2><button class="x" onclick="closeModal()">×</button></div>';

  h+='<div class="m-body form">'+

  /* ---- сделка ---- */
  '<section class="fcard"><h4>'+T.tradeDefaultName+'</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>'+T.fPair+' <i>*</i></label>'+
        pick("pair",pairs,t?t.pair:"",T.fmOwnPairPh)+"</div>"+
      '<div class="f"><label>'+T.fmDateTime+' <i>*</i></label>'+
        '<input id="fld_date" type="datetime-local" value="'+esc(dt)+'"></div>'+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>'+T.fSession+'</label>'+
        pick("session",SESSIONS,t?t.session:"",T.fmOwnSessionPh)+"</div>"+
      '<div class="f"><label>'+T.fmDirectionLabel+'</label>'+
        seg("position",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.position:"","big")+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- контекст ---- */
  '<section class="fcard"><h4>'+T.fmContextSection+'</h4><div class="fbody">'+
    '<div class="frow">'+
      '<div class="f"><label>'+T.fmBiasLabel+'</label>'+
        seg("bias",[{v:"Long",t:"Long",cls:"lng"},{v:"Short",t:"Short",cls:"shr"}],t?t.bias:"","big")+"</div>"+
      '<div class="f"><label>'+T.fmEntryTypeLabel+' <span class="autotag" id="dirTag">'+T.fmAutoWillFill+'</span></label>'+
        seg("direction_type",[{v:"Continuation",t:T.fmContinuation,cls:"cont"},
                              {v:"Reversal",t:T.fmReversal,cls:"rev"}],t?dirType(t):"","big")+"</div>"+
    "</div>"+
    '<div class="frow">'+
      '<div class="f"><label>'+T.fEntryModel+'</label>'+
        pick("entry_model",models,t?t.entry_model:"",T.fmOwnModelPh)+"</div>"+
      '<div class="f"><label>'+T.fSetup+'</label>'+
        pick("setup",setups,t?t.setup:"",T.fmOwnSetupPh)+"</div>"+
    "</div>"+
  "</div></section>"+

  /* ---- результат ---- */
  '<section class="fcard accent"><h4>'+T.fmResultSection+'</h4><div class="fbody">'+
    '<div class="f"><label>'+T.fmFinishedAs+' <i>*</i></label>'+
      seg("result",[{v:"Win",t:"TP",cls:"win"},{v:"Loss",t:"SL",cls:"loss"},
                    {v:"BE-",t:"BE\u2212",cls:"bek"},{v:"BE+",t:"BE+",cls:"bepk"}],t?t.result:"","big res")+"</div>"+
    '<div class="frow">'+
      '<div class="f"><label>RR</label>'+
        '<input id="fld_rr" type="number" step="0.1" min="0" placeholder="2.5" oninput="calcOutcome()" value="'+(t&&t.rr!=null?t.rr:"")+'"></div>'+
      '<div class="f"><label>'+T.fmRiskLabel+'</label>'+
        pick("risk",["0.5","1","1.5","2"],(t&&t.risk!=null?String(t.risk):"1"),T.fmOwnRiskPh,true)+"</div>"+
    "</div>"+
    '<div class="outcome" id="outcome"></div>'+
  "</div></section>"+

  /* ---- скриншоты ---- */
  '<section class="fcard"><h4>'+T.fmShotsSection+'</h4><div class="fbody">'+
    '<div class="tfgrid" id="shotsEdit"></div>'+
    '<input id="shotFile" type="file" accept="image/*" multiple hidden>'+
  "</div></section>"+

  /* ---- заметки ---- */
  '<section class="fcard"><h4>'+T.fNotes+'</h4><div class="fbody">'+
    '<div class="f"><label>'+T.fEntryDetails+'</label><textarea id="fld_entry_details" placeholder="'+T.fmEntryDetailsPh+'">'+v("entry_details")+"</textarea></div>"+
    '<div class="f"><label>'+T.fmThoughtsLabel+'</label><textarea id="fld_notes" class="short">'+v("notes")+"</textarea></div>"+
    '<div class="f"><label>'+T.fmMistakeLabel+'</label>'+
      '<div class="quick">'+mistakes.map(x=>
        '<button type="button" data-f="mistakes" data-v="'+esc(x)+'" onclick="quickSet(this)">'+esc(x)+"</button>").join("")+"</div>"+
      '<input id="fld_mistakes" value="'+v("mistakes")+'" placeholder="'+T.fmMistakeEmptyPh+'" autocomplete="off" oninput="markQuick()"></div>'+
    '<div class="f"><label>'+T.fmEmotionLabel+' <span class="autotag">'+T.fmEmotionAutotag+'</span></label>'+
      '<div class="quick">'+T.emotions.map(x=>
        '<button type="button" data-f="emotion" data-v="'+esc(x)+'" onclick="quickSet(this)">'+esc(x)+"</button>").join("")+"</div>"+
      '<input id="fld_emotion" value="'+v("emotion")+'" placeholder="'+T.fmEmotionPh+'" autocomplete="off" oninput="markQuick()"></div>'+
  "</div></section>"+

  "</div>";

  h+='<div class="m-foot">'+
    (t?'<button class="btn danger" onclick="delTrade(\''+t.id+'\')">'+T.tcDelete+'</button>':"")+
    '<span class="sp"></span><button class="btn" onclick="closeModal()">'+T.fmCancel+'</button>'+
    '<button class="btn primary" onclick="saveTrade(\''+(t?t.id:"")+'\')">'+T.fmSave+'</button></div>';

  Sheet.open(h,{cls:"form-pnl"});
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
  if(!res){ box.className="outcome"; box.innerHTML='<span class="hint">'+T.calcChooseResult+'</span>'; return; }
  let val=0, txt="";
  if(res==="Win"){ val=r*rr; txt=T.calcTakePrefix+r1(r)+T.calcTakeMid+r1(rr); }
  else if(res==="Loss"){ val=-r; txt=T.calcStopMsg; }
  else { val=0; txt = res==="BE+" ? T.calcBePlusMsg : T.calcBeMinusMsg; }
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
  if(tag) tag.textContent = val ? T.fmAutoFilled : T.fmAutoWillFill;
}

/* вставка скрина из буфера обмена */
function onPasteShot(e){
  /* Форма угоди тепер виїжджає панеллю, а не лежить у #modal — стара
     перевірка обривала вставку ще до буфера. Досить того, що форма
     на екрані: #shotsEdit існує тільки поки вона відкрита. */
  if(!$("#shotsEdit")) return;
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
  if(field==="direction_type"){ S.dirTouched=true; const tag=$("#dirTag"); if(tag) tag.textContent=T.fmAutoManual; }
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
      '<button type="button" class="rm" title="'+T.shotRemoveTip+'" onclick="removeShot('+i+')">×</button></div>'+
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
        '<button type="button" class="pick" title="'+T.shotPickFileTip+'" data-tf="'+tf+
        '" onclick="event.stopPropagation();pickFor(this.dataset.tf)">'+T.shotFileWord+'</button></div>'+
        '<div class="drop">'+(on?'<span class="ready">Ctrl+V</span>':"+")+'</div></div>';
    }
  }
  S.formShots.forEach((s,i)=>{ if(!used.has(i)) h+=filledTile(s,i,s.tf||"?"); });
  h+='<div class="attach" data-drop="" onclick="$(\'#shotFile\').click()">'+
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none">'+
    '<path d="M12 16V4M8 8l4-4 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'+
    '<path d="M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'+
    T.shotDragHint+'</div>';
  h+='<div class="tfhint">'+T.shotTfHint+'</div>';
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
    /* подвійні пробіли всередині назви теж плодять двійників («NAS  100») */
    pair:g("pair").replace(/\s+/g," "), date:g("date"), session:g("session"), position:g("position"),
    entry_model:g("entry_model"), bias:g("bias"), setup:g("setup"),
    direction_type:g("direction_type"), result:g("result"),
    rr:g("rr"), risk:g("risk"),
    entry_details:g("entry_details"), notes:g("notes"), mistakes:g("mistakes"),
    emotion:g("emotion"), comments:"",
    screenshots:S.formShots,
  };
  if(!t.pair){ alert(T.alertNeedPair); return; }
  /* «1 Месяц» колись приїхало сюди з чужої колонки Notion. Не забороняємо —
     перепитуємо: раптом інструмент і справді так зветься */
  if(!looksLikePair(t.pair) && !await Ask.yes(T.alertOddPair.replace("%s", t.pair), {ok:T.askYes, cancel:T.askNo})) return;
  if(!t.date){ alert(T.alertNeedDate); return; }
  if(!t.result){ alert(T.alertNeedResult); return; }
  if(t.result==="Win" && !num(t.rr)){ alert(T.alertNeedRR); return; }
  const btn=document.querySelector(".m-foot .primary"); if(btn){btn.disabled=true;btn.textContent=T.fmSaving;}
  try{
    let saved=null;
    if(id) await api("PUT","/api/trades/"+id,t);
    else   saved=await api("POST","/api/trades",t);
    await reload(); closeModal(); render();
    /* Звірка з ТС — уже після того, як форма закрилась: людина не має
       чекати ні на сервер, ні на модель. Правки чужих полів не чіпаємо:
       мова про щойно зроблений вхід, а не про виправлену давню угоду. */
    if(saved && saved.id && window.Watch) Watch.afterTrade(saved.id);
  }catch(err){ alert(T.alertSaveFail+err.message); if(btn){btn.disabled=false;btn.textContent=T.fmSave;} }
}

/* ---------- импорт / экспорт ---------- */
const IMP={rows:[],headers:[],map:{}};
function IMP_FIELDS(){ return [["pair",T.fPair],["date",T.fDate],["session",T.fSession],["position",T.fPosition],
  ["entry_model",T.fEntryModel],["bias",T.fBias],["setup",T.fSetup],["direction_type",T.impDirTypeShort],
  ["result",T.fResult],["rr","RR"],["risk",T.fRisk],["entry_details",T.fEntryDetails],["notes",T.fNotes],["mistakes",T.fMistakes],
  ["emotion",T.fEmotion]]; }

function openImport(){
  let h='<div class="m-head"><h2>'+T.imTitle+'</h2><button class="x" onclick="closeModal()">×</button></div>'+
  '<div class="m-body">'+
  '<p class="hint">'+T.imHint+'</p>'+
  '<input id="impFile" type="file" accept=".json,.csv,.txt" style="margin:12px 0">'+
  '<div id="impMap"></div></div>'+
  '<div class="m-foot"><span class="sp"></span><button class="btn" onclick="closeModal()">'+T.fmCancel+'</button>'+
  '<button class="btn primary" id="impGo" disabled onclick="doImport()">'+T.imGoBtn+'</button></div>';
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
    }catch(err){ $("#impMap").innerHTML='<p class="neg">'+T.imParseError+esc(err.message)+"</p>"; return; }
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
  let h='<p class="hint">'+T.imFoundRows+'<b style="color:var(--text)">'+IMP.rows.length+"</b></p>"+
    '<div class="map-grid">';
  for(const [f,label] of IMP_FIELDS()){
    const guess=guessHeader(f,IMP.headers); IMP.map[f]=guess;
    h+='<span class="k">'+label+'</span><select onchange="IMP.map[\''+f+'\']=this.value">'+
      '<option value="">'+T.imSkipOption+'</option>'+
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
  if(!out.length){ alert(T.imNothingToImport); return; }
  const btn=$("#impGo"); btn.disabled=true; btn.textContent=T.imImporting;
  const res=await api("POST","/api/import",out);
  await reload(); closeModal(); render();
  alert(T.imImportedCount+res.added);
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
let bootRendered=false;              /* перший рендер іде одразу після заставки-лоадера — своя
                                         плавна поява карток тут зайва: між лоадером і готовим
                                         виглядом інакше проскакує ще один «порожній» кадр */
let dataReady=false;                 /* поки reload() не завершився — жоден виклик render() не
                                         чіпає #main: там і далі стоїть заставка-лоадер із розмітки */
/* У чужому журналі своїх розділів немає: «Аналіз дня» і «Моя ТС» читають
   особисте, тому на них не пускаємо навіть за адресою з решіткою. */
const PUB_VIEWS={dashboard:1,journal:1,monthly:1,quarterly:1,yearly:1,analytics:1,news:1};
function viewAllowed(v){
  if(!VIEWS[v]) return false;
  return window.Pub&&Pub.on ? !!PUB_VIEWS[v] : true;
}
function render(){
  if(!dataReady) return;
  const v=viewAllowed(S.view)?S.view:"dashboard";
  /* «Новини» переїхали з меню в групу інструментів — підсвічування шукаємо
     і там, інакше відкритий розділ ніде не позначався */
  document.querySelectorAll(".nav a, .side a[data-v]").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
  if(window.PL) PL.reset();
  /* «enter» только при смене раздела: перерисовка после правки угоди
     не должна каждый раз моргать всей страницей */
  const fresh = tickedView!==v && bootRendered;
  $("#main").innerHTML='<div class="page'+(fresh?" enter":"")+'">'+VIEWS[v]()+"</div>";
  /* блоки появляются тихо, как в макете — крім найпершого рендера: там
     одразу показуємо готовий вигляд без окремої появи */
  if(bootRendered){
    requestAnimationFrame(()=>document.querySelectorAll(".page .rise,.ovw .rail").forEach(el=>el.classList.add("in")));
  }else{
    document.querySelectorAll(".page .rise,.ovw .rail").forEach(el=>el.classList.add("in"));
    bootRendered=true;
  }
  tickedView=v;
  if(window.Ticker) Ticker.run($("#main"), fresh);
  if(window.PL) PL.mount();
  if(window.Tip) Tip.mount($("#main"));
}
window.addEventListener("hashchange",()=>{ S.view=location.hash.slice(1)||"dashboard"; render(); });
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ if(!$("#lightbox").hidden)closeLightbox(); else if(!$("#modal").hidden)closeModal(); }
});
$("#modal").addEventListener("click",e=>{ if(e.target.id==="modal")closeModal(); });

/* ---------- аккаунт и Telegram ---------- */
async function logout(){
  if(!await Ask.yes(T.confirmLogout, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
  try{ await api("POST","/api/auth/logout"); }catch(e){}
  location.href="/login";
}

async function openTelegram(){
  if(window.Guest && Guest.block(T.gsGateConnect)) return;
  let user=null;
  try{ user=(await api("GET","/api/auth/me")).user; }catch(e){ return; }
  const head='<div class="m-head"><h2>Telegram</h2><button class="x" onclick="closeModal()">×</button></div>';
  const foot='<div class="m-foot"><span class="sp"></span><button class="btn" onclick="closeModal()">'+T.mrClose+'</button></div>';
  let body;
  if(user && user.telegram_linked){
    body='<div class="m-body"><p class="hint">'+T.tgLinkedPrefix+' <b>'+esc(user.telegram ? "@"+user.telegram : "Telegram")+'</b>. '+
      T.tgLinkedDesc+'</p>'+
      '<button class="btn danger" onclick="unlinkTelegram()">'+T.tgUnlink+'</button></div>';
  }else{
    body='<div class="m-body"><p class="hint">'+T.tgNotLinkedDesc+'</p>'+
      '<button class="btn primary" onclick="linkTelegram()">'+T.tgGetCode+'</button>'+
      '<div id="tgLink" style="margin-top:14px"></div></div>';
  }
  openModal(head+body+foot);
}

async function linkTelegram(){
  const box=$("#tgLink"); if(box) box.innerHTML='<span class="hint">'+T.tgPreparing+'</span>';
  try{
    const r=await api("POST","/api/telegram/link-code");
    box.innerHTML='<p class="hint">'+T.tgCodeValid+'</p>'+
      '<a class="btn primary" href="'+esc(r.link)+'" target="_blank" rel="noopener">'+T.tgOpenBotPrefix+esc(r.bot)+'</a>'+
      '<p class="hint" style="margin-top:10px">'+T.tgManualPrefix+' <b>/start '+esc(r.code)+'</b></p>';
  }catch(e){
    box.innerHTML='<span class="hint">'+T.tgCodeError+'</span>';
  }
}

async function unlinkTelegram(){
  if(!await Ask.yes(T.confirmUnlinkTg, {ok:T.askYes, cancel:T.askNo, danger:true})) return;
  try{ await api("POST","/api/telegram/unlink"); }catch(e){}
  closeModal();
  refreshTelegramStatus();
}

/* ---------- розділ «Підключення» (Notion + Telegram) у сайдбарі ---------- */
function toggleConn(){
  const box=document.getElementById("conn"); if(!box) return;
  const open=!box.classList.contains("open");
  box.classList.toggle("open",open);
  if(open){
    refreshTelegramStatus();
    if(window.__notion && window.__notion.refreshState) window.__notion.refreshState();
  }
}

let telegramLinked=false;
function paintTelegramStatus(){
  const el=document.getElementById("telegramStatus"), row=document.getElementById("telegramBtn");
  if(!el) return;
  el.textContent = telegramLinked ? T.connConnected : T.connNotConnected;
  if(row) row.classList.toggle("connected", telegramLinked);
}
window.paintTelegramStatus=paintTelegramStatus;
async function refreshTelegramStatus(){
  let user=null;
  try{ user=(await api("GET","/api/auth/me")).user; }catch(e){ return; }
  telegramLinked=!!(user && user.telegram_linked);
  paintTelegramStatus();
}

function markDemo(){
  const b=document.createElement("div");
  b.className="demo-badge";
  b.innerHTML='<b>'+T.demoLabel+'</b><span>'+T.demoDesc+'</span>'+
              '<button type="button" onclick="DemoStore.reset()">'+T.demoReset+'</button>';
  document.body.appendChild(b);
}

(async function init(){
  markTheme(); markLayout();
  /* /u/<нік> — чужий журнал: режим вмикається до першого запиту, бо він
     міняє й адресу, за якою беруться угоди. */
  if(window.Pub && Pub.detect()) Pub.start();
  try{
    await reload();
  }catch(e){
    /* У чужому журналі свої причини не відкритись — закритий журнал і
       відсутній акаунт. Pub пояснює їх сам, демо тут ні до чого. */
    if(window.Pub && Pub.on){ if(Pub.fail(e)) return; }
    /* Дві різні причини сюди потрапити. 401 — людина просто не увійшла:
       показуємо їй журнал на демо-даних і кличемо завести свій. Будь-яка
       інша помилка — сервера немає (публічне демо), там усе як було. */
    const guest = String(e && e.message) === "API 401";
    try{
      await DemoStore.init();
      DEMO=true;
      await reload();
      if(guest && window.Guest) Guest.start(); else markDemo();
    }catch(e2){
      $("#main").innerHTML='<div class="empty">'+T.initServerError+'</div>';
      return;
    }
  }
  dataReady=true;
  S.view=location.hash.slice(1)||"dashboard";
  if(S.view==="monthly"){ S.view="journal"; location.hash="journal"; }
  render();
  if(window.Sparks) Sparks.start();
  if(!DEMO && !(window.Pub && Pub.on)) refreshTelegramStatus();
})();
