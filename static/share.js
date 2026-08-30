/* Картинка со статистикой месяца — для отправки в Telegram.
   Рисуем на canvas: заголовок, показатели, календарь, кривая, выводы. */
"use strict";

const SHARE_W = 1080;

function themeColors(){
  const cs = getComputedStyle(document.documentElement);
  const g = n => cs.getPropertyValue(n).trim();
  return {
    bg:g("--bg"), panel:g("--panel"), panel2:g("--panel-2"),
    line:g("--line"), lineSoft:g("--line-soft"),
    text:g("--text"), dim:g("--dim"), faint:g("--faint"),
    accent:g("--accent"), up:g("--up"), down:g("--down"), be:g("--be"),
  };
}
function withAlpha(hex, a){
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.replace("#",""));
  if(!m) return hex;
  const n = parseInt(m[1],16);
  return "rgba("+((n>>16)&255)+","+((n>>8)&255)+","+(n&255)+","+a+")";
}

function roundRect(ctx,x,y,w,h,r){
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.quadraticCurveTo(x+w,y,x+w,y+r);
  ctx.lineTo(x+w,y+h-r); ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
  ctx.lineTo(x+r,y+h); ctx.quadraticCurveTo(x,y+h,x,y+h-r);
  ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath();
}
const MONO = '"IBM Plex Mono",ui-monospace,Consolas,monospace';
const SANS = '"IBM Plex Sans","Segoe UI",system-ui,sans-serif';

async function buildMonthImage(ym){
  await document.fonts.ready;
  const C = themeColors();
  const [Y,M] = ym.split("-").map(Number);
  const list = S.trades.filter(t=>monKey(t)===ym);
  const st = calc(list);

  /* выводы считаем заранее — от них зависит высота */
  const topOf = key => {
    const g = [...groupBy(list,t=>fieldVal(t,key)).entries()]
      .map(([n,a])=>({n,net:a.reduce((s,t)=>s+netR(t),0),cnt:a.length}))
      .sort((a,b)=>b.net-a.net);
    return g.length?g:null;
  };
  const lines = [];
  {
    const ses = topOf("session"), dir = topOf("direction_type"), pr = topOf("pair");
    if(ses) lines.push(["Лучшая сессия", ses[0].n+" · "+ses[0].cnt+" сд", ses[0].net]);
    if(ses && ses.length>1) lines.push(["Худшая сессия", ses[ses.length-1].n+" · "+ses[ses.length-1].cnt+" сд", ses[ses.length-1].net]);
    if(pr) lines.push(["Лучший актив", pr[0].n+" · "+pr[0].cnt+" сд", pr[0].net]);
    if(dir) dir.forEach(d=> lines.push([d.n==="Reversal"?"Развороты":"По биасу", d.cnt+" сделок", d.net]));
    if(st.be) lines.push(["Безубытки", "спасли "+r1(st.beSaved)+"%, отняли "+r1(st.beLost)+"%", st.beSaved-st.beLost]);
  }
  const shown = lines.slice(0,6);

  const calStart = (new Date(Y,M-1,1).getDay()+6)%7;
  const calDim = new Date(Y,M,0).getDate();
  const calRows = Math.ceil((calStart+calDim)/7);

  const SHARE_H = Math.round(
    214 + 128 + 108 +           // шапка, показатели, чипы
    60 + calRows*92 + 34 +      // календарь
    20 + 210 + 40 +             // график
    28 + shown.length*52 + 26 + // выводы
    92                          // подвал
  );

  const cv = document.createElement("canvas");
  cv.width = SHARE_W; cv.height = SHARE_H;
  const x = cv.getContext("2d");

  x.fillStyle = C.bg; x.fillRect(0,0,SHARE_W,SHARE_H);
  const P = 64;                       // поля
  let y = 78;

  /* ---------- шапка ---------- */
  x.fillStyle = C.accent; x.font = "500 22px "+MONO;
  x.fillText("ИТОГИ МЕСЯЦА", P, y);
  y += 58;
  x.fillStyle = C.text; x.font = "700 76px "+SANS;
  x.fillText(MONTHS[M-1]+" "+Y, P, y);

  const resTxt = fmtR(st.net);
  x.font = "600 76px "+MONO;
  const rw = x.measureText(resTxt).width;
  x.fillStyle = st.net>0 ? C.up : st.net<0 ? C.down : C.be;
  x.fillText(resTxt, SHARE_W-P-rw, y);
  y += 34;

  x.strokeStyle = C.line; x.lineWidth = 2;
  x.beginPath(); x.moveTo(P,y); x.lineTo(SHARE_W-P,y); x.stroke();
  y += 44;

  /* ---------- показатели ---------- */
  const cells = [
    ["Сделок", String(st.n), C.text],
    ["Winrate", fmtPct(st.wr), C.text],
    ["Profit Factor", st.pfTxt, C.text],
    ["Средний RR", st.avgRR!=null?String(r1(st.avgRR)):"—", C.text],
  ];
  const cw = (SHARE_W-P*2-3*14)/4, ch = 108;
  cells.forEach((c,i)=>{
    const cx = P + i*(cw+14);
    x.fillStyle = C.panel; roundRect(x,cx,y,cw,ch,10); x.fill();
    x.strokeStyle = C.line; x.lineWidth = 1.5; x.stroke();
    x.fillStyle = C.faint; x.font = "500 17px "+MONO;
    x.fillText(c[0].toUpperCase(), cx+18, y+34);
    x.fillStyle = c[2]; x.font = "500 40px "+MONO;
    x.fillText(c[1], cx+18, y+82);
  });
  y += ch + 20;

  /* строка TP / SL / BE */
  x.fillStyle = C.panel; roundRect(x,P,y,SHARE_W-P*2,68,10); x.fill();
  x.strokeStyle = C.line; x.stroke();
  const chips = [
    ["TP", st.wins, C.up], ["SL", st.losses, C.down],
    ["BE−", st.beM, C.be], ["BE+", st.beP, C.accent],
  ];
  let chx = P+22;
  chips.forEach(c=>{
    x.fillStyle = withAlpha(c[2],.16);
    roundRect(x,chx,y+18,60,32,8); x.fill();
    x.fillStyle = c[2]; x.font = "600 19px "+MONO;
    const tw = x.measureText(c[0]).width;
    x.fillText(c[0], chx+30-tw/2, y+40);
    x.fillStyle = C.text; x.font = "500 26px "+MONO;
    x.fillText(String(c[1]), chx+72, y+43);
    chx += 72 + x.measureText(String(c[1])).width + 34;
  });
  y += 68 + 40;

  /* ---------- календарь ---------- */
  x.fillStyle = C.faint; x.font = "500 18px "+MONO;
  x.fillText("КАЛЕНДАРЬ", P, y); y += 26;

  const gap = 8, cols = 7;
  const cellW = (SHARE_W-P*2 - gap*(cols-1))/cols, cellH = 84;
  const byDay = groupBy(list, dayKey);
  const start = calStart, dim = calDim;

  x.fillStyle = C.faint; x.font = "500 15px "+MONO;
  WDS.forEach((w,i)=> x.fillText(w.toUpperCase(), P+i*(cellW+gap)+8, y+16));
  y += 34;

  const rows = calRows;
  for(let d=1; d<=dim; d++){
    const idx = start+d-1, col = idx%7, row = Math.floor(idx/7);
    const cx = P+col*(cellW+gap), cy = y+row*(cellH+gap);
    const key = Y+"-"+pad(M)+"-"+pad(d);
    const dl = byDay.get(key)||[];
    const net = dl.reduce((a,t)=>a+netR(t),0);
    if(dl.length){
      const col2 = net>0.0001?C.up : net<-0.0001?C.down : C.be;
      x.fillStyle = withAlpha(col2,.17); roundRect(x,cx,cy,cellW,cellH,9); x.fill();
      x.strokeStyle = withAlpha(col2,.5); x.lineWidth = 1.5; x.stroke();
    }else{
      x.fillStyle = C.panel; roundRect(x,cx,cy,cellW,cellH,9); x.fill();
      x.strokeStyle = C.lineSoft; x.lineWidth = 1.5; x.stroke();
    }
    x.fillStyle = dl.length?C.dim:C.faint; x.font = "500 16px "+MONO;
    x.fillText(String(d), cx+10, cy+24);
    if(dl.length){
      x.fillStyle = net>0.0001?C.up : net<-0.0001?C.down : C.be;
      x.font = "600 22px "+MONO;
      x.fillText(fmtR(net), cx+10, cy+56);
      x.fillStyle = C.faint; x.font = "400 14px "+MONO;
      x.fillText(dl.length+" сд", cx+10, cy+74);
    }
  }
  y += rows*(cellH+gap) + 34;

  /* ---------- кривая ---------- */
  x.fillStyle = C.faint; x.font = "500 18px "+MONO;
  x.fillText("НАКОПЛЕННЫЙ РЕЗУЛЬТАТ", P, y); y += 20;

  const chH = 210, chW = SHARE_W-P*2;
  x.fillStyle = C.panel; roundRect(x,P,y,chW,chH,10); x.fill();
  x.strokeStyle = C.line; x.lineWidth = 1.5; x.stroke();

  const arr = sortAsc(list); const eq = []; let acc = 0;
  arr.forEach(t=>{ acc += netR(t); eq.push(acc); });
  if(eq.length>1){
    const pad2 = 26;
    const lo = Math.min(0,...eq), hi = Math.max(0.001,...eq);
    const gx = i => P+pad2 + i*(chW-pad2*2)/(eq.length-1);
    const gy = v => y+pad2 + (hi-v)*(chH-pad2*2)/((hi-lo)||1);
    x.strokeStyle = C.lineSoft; x.lineWidth = 1.5; x.setLineDash([5,6]);
    x.beginPath(); x.moveTo(P+pad2,gy(0)); x.lineTo(P+chW-pad2,gy(0)); x.stroke();
    x.setLineDash([]);
    x.beginPath(); x.moveTo(gx(0),gy(0));
    eq.forEach((v,i)=>x.lineTo(gx(i),gy(v)));
    x.lineTo(gx(eq.length-1),gy(0)); x.closePath();
    x.fillStyle = withAlpha(C.accent,.14); x.fill();
    x.beginPath();
    eq.forEach((v,i)=> i?x.lineTo(gx(i),gy(v)):x.moveTo(gx(i),gy(v)));
    x.strokeStyle = C.accent; x.lineWidth = 3.5; x.lineJoin = "round"; x.stroke();
    const last = eq[eq.length-1];
    x.beginPath(); x.arc(gx(eq.length-1),gy(last),8,0,7);
    x.fillStyle = last>=0?C.up:C.down; x.fill();
    x.strokeStyle = C.panel; x.lineWidth = 3; x.stroke();
  }else{
    x.fillStyle = C.faint; x.font = "400 20px "+SANS;
    x.fillText("Мало сделок для графика", P+26, y+chH/2);
  }
  y += chH + 40;

  /* ---------- выводы ---------- */
  x.fillStyle = C.faint; x.font = "500 18px "+MONO;
  x.fillText("ЧТО ПОКАЗАЛ МЕСЯЦ", P, y); y += 28;

  shown.forEach((l,i)=>{
    const ly = y+i*52;
    x.fillStyle = i%2 ? C.bg : C.panel;
    roundRect(x,P,ly,SHARE_W-P*2,46,8); x.fill();
    x.fillStyle = C.dim; x.font = "400 22px "+SANS;
    x.fillText(l[0], P+18, ly+30);
    x.fillStyle = C.faint; x.font = "400 19px "+SANS;
    x.fillText(l[1], P+300, ly+30);
    const v = fmtR(l[2]);
    x.font = "600 24px "+MONO;
    const vw = x.measureText(v).width;
    x.fillStyle = l[2]>0.0001?C.up : l[2]<-0.0001?C.down : C.be;
    x.fillText(v, SHARE_W-P-18-vw, ly+30);
  });
  y += shown.length*52 + 26;

  /* ---------- подвал ---------- */
  x.strokeStyle = C.line; x.lineWidth = 2;
  x.beginPath(); x.moveTo(P,SHARE_H-92); x.lineTo(SHARE_W-P,SHARE_H-92); x.stroke();
  x.fillStyle = C.faint; x.font = "400 19px "+MONO;
  x.fillText("Trading Journal", P, SHARE_H-52);
  const per = st.n ? "на сделку "+fmtR(st.net/st.n) : "";
  const pw = x.measureText(per).width;
  x.fillText(per, SHARE_W-P-pw, SHARE_H-52);

  return cv;
}

/* ---------- окно «поделиться» ---------- */
async function openShare(ym){
  openModal('<div class="m-head"><h2>Картинка за месяц</h2><button class="x" onclick="closeModal()">×</button></div>'+
    '<div class="m-body"><div class="sharewrap" id="shareWrap"><div class="empty">Рисую…</div></div></div>'+
    '<div class="m-foot"><button class="btn primary" id="copyImg">Скопировать картинку</button>'+
    '<button class="btn" id="dlImg">Скачать файлом</button>'+
    '<span class="sp"></span><span class="hint" id="shareMsg"></span></div>');
  let cv;
  try{ cv = await buildMonthImage(ym); }
  catch(e){ $("#shareWrap").innerHTML='<div class="empty">Не получилось нарисовать: '+esc(e.message)+"</div>"; return; }
  const wrap = $("#shareWrap");
  wrap.innerHTML = "";
  cv.style.width = "100%"; cv.style.height = "auto"; cv.style.display = "block";
  cv.style.borderRadius = "8px";
  wrap.appendChild(cv);

  const msg = t => { const m=$("#shareMsg"); if(m) m.textContent=t; };
  $("#copyImg").onclick = async () => {
    try{
      const blob = await new Promise(r=>cv.toBlob(r,"image/png"));
      await navigator.clipboard.write([new ClipboardItem({"image/png":blob})]);
      msg("Скопировано — вставь в Telegram через Ctrl+V");
    }catch(e){ msg("Копирование недоступно, сохрани файлом"); }
  };
  $("#dlImg").onclick = () => {
    const a = document.createElement("a");
    a.href = cv.toDataURL("image/png");
    a.download = "stats-"+ym+".png";
    a.click(); msg("Файл сохранён");
  };
}
