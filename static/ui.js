/* Компоненты интерфейса, перенесённые из React-библиотек на чистый JS.
   Источники поведения: Magic UI (Number Ticker), shadcn/ui (Tooltip, Sheet,
   Drawer, Pagination), Bklit UI (Profit/Loss Line).
   Здесь нет сборки и зависимостей — журнал остаётся статикой. */
"use strict";

/* ================= Magic UI · Number Ticker =================
   Число отсчитывается до своего значения: при первом заходе
   и при каждом переходе между разделами. */
const Ticker = (function(){
  const SEL = ".ovw .sum .big, .ovw .stats .val, .ovw .chart-lab .v, .ovw .chart-lab .dd,"+
              ".ovw .sec-lab .wsum, .ovw .day .dr, .kpi .v, .chip b, .plline .v, .arow .netr";
  const DUR = 1100;               /* столько же длится пружина Magic UI */
  const STEP = 55;                /* сдвиг соседних чисел, чтобы шли волной */
  /* «просадка −8.00%» → префикс, число, хвост */
  const RE = /^([^\d]*?)([+\-−]?\d[\d  ]*(?:[.,]\d+)?)(.*)$/s;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  function parse(txt){
    const m = RE.exec(txt);
    if(!m) return null;
    const raw = m[2].replace(/[  ]/g,"").replace("−","-").replace(",",".");
    const to = parseFloat(raw);
    if(isNaN(to)) return null;
    const dot = raw.indexOf(".");
    return { pre:m[1], to, dec: dot<0?0:raw.length-dot-1, sign:m[2][0]==="+",
             minus: m[2][0]==="−" ? "−" : "-", post:m[3] };
  }
  function fmt(p, v){
    const s = Math.abs(v).toFixed(p.dec);
    const sign = v<0 ? p.minus : (p.sign ? "+" : "");
    return p.pre + sign + s + p.post;
  }
  function ease(t){ return t===1 ? 1 : 1-Math.pow(2,-9*t); }   /* out-expo, как затухание пружины */

  function run(root, animate){
    const els = (root||document).querySelectorAll(SEL);
    if(!animate || still()) return;
    let i = 0;
    els.forEach(el=>{
      /* «1 / 7 / 2» и «BE− / BE+» — счётчики через дробь, их не крутим */
      if(el.textContent.indexOf("/") >= 0) return;
      const p = parse(el.textContent);
      if(!p || !isFinite(p.to)) return;
      const final = el.textContent;
      const delay = Math.min(i++, 12) * STEP;      /* длинные таблицы не ждут по очереди бесконечно */
      el.textContent = fmt(p, 0);
      const t0 = performance.now() + delay;
      let done = false;
      (function frame(now){
        const k = (now - t0) / DUR;
        if(done) return;
        if(k < 0){ requestAnimationFrame(frame); return; }
        if(k >= 1){ done = true; el.textContent = final; return; }
        el.textContent = fmt(p, p.to * ease(k));
        requestAnimationFrame(frame);
      })(performance.now());
      /* во вкладке без кадров rAF молчит — подстраховываемся таймером */
      setTimeout(()=>{ if(!done){ done = true; el.textContent = final; } }, delay + DUR + 250);
    });
  }
  return { run };
})();
window.Ticker = Ticker;   /* const не попадает в window — связываем явно */

/* ================= Bklit UI · Profit/Loss Line =================
   Линия прибыли/убытка: под курсором показывает день и накопленный итог. */
const PL = (function(){
  /* точки графиков, собранные при отрисовке: ключ — data-pl у обёртки */
  const data = {};
  function fmt(v){ return (v>0?"+":"")+v.toFixed(2)+"%"; }
  function day(iso){ return iso.slice(8,10)+"."+iso.slice(5,7); }

  /* графиков на странице может быть несколько (год на «Огляді», месяц у журналі):
     точки лежат на самом элементе, а не в общем состоянии */
  function mount(root){
    (root || document).querySelectorAll(".plwrap").forEach(one);
  }

  function one(wrap){
    const pts = wrap._pts || data[wrap.dataset.pl];
    if(!pts || !pts.length || wrap._plBound) return;
    wrap._pts = pts;
    wrap._plBound = true;
    const svg = wrap.querySelector("svg");
    const cur = svg.querySelector(".plcursor");
    const dot = svg.querySelector(".plhover");
    const tip = wrap.querySelector(".pltip");

    /* из экранных координат в систему графика и обратно — работает при любом масштабе svg */
    const toLocal = e => {
      const m = svg.getScreenCTM(); if(!m) return null;
      const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
      return p.matrixTransform(m.inverse());
    };
    const toScreen = (x,y) => {
      const m = svg.getScreenCTM(); const p = svg.createSVGPoint(); p.x = x; p.y = y;
      return p.matrixTransform(m);
    };

    wrap.addEventListener("pointermove", e=>{
      const loc = toLocal(e); if(!loc) return;
      let best = pts[0], bd = Infinity;
      for(const p of pts){ const d = Math.abs(p.x - loc.x); if(d < bd){ bd = d; best = p; } }
      cur.setAttribute("x1", best.x); cur.setAttribute("x2", best.x);
      dot.setAttribute("x1", best.x); dot.setAttribute("x2", best.x);
      dot.setAttribute("y1", best.y); dot.setAttribute("y2", best.y);
      dot.setAttribute("stroke", best.v < 0 ? "var(--down)" : "var(--up)");
      cur.hidden = false; dot.hidden = false;
      /* индикатор строки красится по знаку — indicatorColor из ChartTooltip */
      const ink = best.v < 0 ? "var(--down)" : "var(--up)";
      tip.innerHTML = '<span class="i" style="background:'+ink+'"></span>'+
        '<span class="d">'+day(best.d)+'</span><span class="v '+
        (best.v>0.0001?"pos":best.v<-0.0001?"neg":"")+'">'+fmt(best.v)+"</span>";
      const sc = toScreen(best.x, best.y), box = wrap.getBoundingClientRect();
      tip.hidden = false;
      const half = tip.offsetWidth/2;
      let left = sc.x - box.left;
      left = Math.max(half, Math.min(box.width - half, left));      /* не вылезает за края */
      tip.style.left = left+"px";
      tip.style.top  = Math.max(4, sc.y - box.top - 42)+"px";
    });
    wrap.addEventListener("pointerleave", ()=>{
      cur.hidden = true; dot.hidden = true; tip.hidden = true;
    });
  }
  /* перед новой отрисовкой старые точки не нужны — иначе реестр растёт бесконечно */
  function reset(){ for(const k in data) delete data[k]; }
  return { mount, reset, data };
})();
window.PL = PL;

/* ================= shadcn/ui · Tooltip =================
   Подсказка у иконок, показателей и действий: атрибут data-tip="текст".
   Одна плашка на страницу, показывается с задержкой, как в оригинале. */
const Tip = (function(){
  const DELAY = 220;
  let box = null, timer = null, cur = null;

  function ensure(){
    if(box) return box;
    box = document.createElement("div");
    box.className = "tipbox";
    box.hidden = true;
    document.body.appendChild(box);
    return box;
  }
  function place(el){
    const b = ensure(), r = el.getBoundingClientRect();
    b.textContent = el.dataset.tip;
    b.hidden = false; b.classList.remove("in");
    const w = b.offsetWidth, h = b.offsetHeight;
    let left = r.left + r.width/2 - w/2;
    left = Math.max(8, Math.min(innerWidth - w - 8, left));
    let top = r.top - h - 8;
    b.classList.toggle("below", top < 8);               /* сверху не влезает — показываем снизу */
    if(top < 8) top = r.bottom + 8;
    b.style.left = left+"px"; b.style.top = top+"px";
    requestAnimationFrame(()=>b.classList.add("in"));
  }
  function hide(){
    clearTimeout(timer); cur = null;
    if(box){ box.classList.remove("in"); box.hidden = true; }
  }
  function show(el){
    if(cur === el) return;
    clearTimeout(timer); cur = el;
    timer = setTimeout(()=>place(el), DELAY);
  }
  function mount(){
    if(mount.done) return; mount.done = true;
    const find = e => e.target.closest && e.target.closest("[data-tip]");
    document.addEventListener("pointerover", e=>{ const el = find(e); el ? show(el) : hide(); });
    document.addEventListener("pointerdown", hide);
    document.addEventListener("focusin", e=>{ const el = find(e); if(el) show(el); });
    document.addEventListener("focusout", hide);
    window.addEventListener("scroll", hide, true);
  }
  return { mount, hide };
})();
window.Tip = Tip;

/* ================= shadcn/ui · Pagination =================
   Страницы длинного списка: «‹ Назад · 1 2 … 9 10 · Далі ›». */
const Pagi = (function(){
  const SIZE = 15;                                  /* строк на страницу */

  function pageOf(key){ return (typeof S !== "undefined" && S.pages && S.pages[key]) || 1; }
  function slice(list, key){
    const pages = Math.max(1, Math.ceil(list.length / SIZE));
    const p = Math.min(pageOf(key), pages);
    return { items: list.slice((p-1)*SIZE, p*SIZE), page:p, pages:pages };
  }
  /* 1 … 4 5 6 … 12 — соседи текущей плюс края */
  function numbers(p, pages){
    const out = [];
    for(let i=1;i<=pages;i++){
      if(i===1 || i===pages || Math.abs(i-p)<=1) out.push(i);
      else if(out[out.length-1] !== "…") out.push("…");
    }
    return out;
  }
  function html(key, p, pages){
    if(pages < 2) return "";
    const go = n => 'onclick="Pagi.go(\'' + key + '\',' + n + ')"';
    const btn = n => typeof n === "number"
      ? '<button class="pg num'+(n===p?" on":"")+'" '+go(n)+'>'+n+"</button>"
      : '<span class="pg gap">…</span>';
    return '<nav class="pagi" aria-label="Сторінки">'+
      '<button class="pg step" '+(p>1?go(p-1):'disabled')+'>‹ Назад</button>'+
      numbers(p, pages).map(btn).join("")+
      '<button class="pg step" '+(p<pages?go(p+1):'disabled')+'>Далі ›</button></nav>';
  }
  function go(key, n){
    if(typeof S === "undefined") return;
    S.pages = S.pages || {};
    S.pages[key] = n;
    render();
    const card = document.querySelector('[data-pagi="'+key+'"]');
    if(card) card.scrollIntoView({block:"nearest", behavior:"smooth"});
  }
  return { SIZE, slice, html, go };
})();
window.Pagi = Pagi;

/* ================= shadcn/ui · Sheet и Drawer =================
   Sheet выезжает справа (детали сделки), Drawer — снизу (форма угоди).
   Общий движок: затемнение, Esc, клик мимо, у Drawer — потяг вниз, как в vaul. */
const Panel = (function(){
  let wrap = null, box = null, closing = false, onClose = null;

  function build(side, cls){
    wrap = document.createElement("div");
    wrap.className = "pnl-wrap";
    wrap.dataset.side = side;
    wrap.innerHTML = '<div class="pnl-ov"></div><aside class="pnl '+(cls||"")+
      '" role="dialog" aria-modal="true"></aside>';
    box = wrap.querySelector(".pnl");
    if(side === "bottom") box.insertAdjacentHTML("afterbegin", '<div class="pnl-grab"><i></i></div>');
    document.body.appendChild(wrap);
    wrap.querySelector(".pnl-ov").addEventListener("click", close);
    document.addEventListener("keydown", esc);
    if(side === "bottom") drag();
  }
  function esc(e){ if(e.key === "Escape" && wrap){ e.stopPropagation(); close(); } }

  /* потяг вниз закрывает нижнюю панель */
  function drag(){
    const grab = box.querySelector(".pnl-grab");
    let y0 = null, dy = 0;
    grab.addEventListener("pointerdown", e=>{
      y0 = e.clientY; dy = 0; grab.setPointerCapture(e.pointerId);
      box.style.transition = "none";
    });
    grab.addEventListener("pointermove", e=>{
      if(y0 === null) return;
      dy = Math.max(0, e.clientY - y0);
      box.style.transform = "translateY("+dy+"px)";
    });
    const end = ()=>{
      if(y0 === null) return;
      y0 = null; box.style.transition = "";
      if(dy > 110) close(); else box.style.transform = "";
    };
    grab.addEventListener("pointerup", end);
    grab.addEventListener("pointercancel", end);
  }

  function open(html, opts){
    opts = opts || {};
    if(wrap) destroy();
    closing = false; onClose = opts.onClose || null;
    build(opts.side || "right", opts.cls);
    box.insertAdjacentHTML("beforeend", html);
    document.body.style.overflow = "hidden";
    requestAnimationFrame(()=>wrap && wrap.classList.add("in"));
    const f = box.querySelector("[autofocus]"); if(f) f.focus();
    return box;
  }
  function destroy(){
    document.removeEventListener("keydown", esc);
    if(wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap);
    wrap = null; box = null;
    document.body.style.overflow = "";
  }
  function close(){
    if(!wrap || closing) return;
    closing = true;
    const cb = onClose; onClose = null;
    wrap.classList.remove("in");
    const w = wrap;
    setTimeout(()=>{ if(w === wrap) destroy(); }, 260);
    if(cb) cb();
  }
  return { open, close, isOpen: ()=>!!wrap, box: ()=>box };
})();
const Sheet  = { open:(html,o)=>Panel.open(html, Object.assign({side:"right"},  o)), close:Panel.close };
const Drawer = { open:(html,o)=>Panel.open(html, Object.assign({side:"bottom"}, o)), close:Panel.close };
window.Panel = Panel; window.Sheet = Sheet; window.Drawer = Drawer;

/* ================= shadcn/ui · Date Picker =================
   Календарь в поповере: один день или период. Месяцы и дни недели берём
   из журнала, чтобы подписи были те же самые. */
const DatePicker = (function(){
  let pop = null, anchor = null, cfg = null, view = null, sel = null;

  const iso = d => d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
  const parse = s => { const [y,m,d] = String(s).split("-").map(Number); return new Date(y, m-1, d); };
  const human = s => s ? s.slice(8,10)+"."+s.slice(5,7)+"."+s.slice(0,4) : "";

  function grid(){
    const Y = view.getFullYear(), M = view.getMonth();
    const first = (new Date(Y,M,1).getDay()+6)%7;
    const dim = new Date(Y,M+1,0).getDate();
    const prev = new Date(Y,M,0).getDate();
    const today = iso(new Date());
    let h = WDS.map(w=>'<span class="dp-wd">'+w+"</span>").join("");
    for(let i=first;i>0;i--) h += '<span class="dp-day off">'+(prev-i+1)+"</span>";
    for(let d=1;d<=dim;d++){
      const key = Y+"-"+String(M+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");
      const cls = [];
      if(cfg.mode === "range"){
        if(sel.from === key || sel.to === key) cls.push("on");
        else if(sel.from && sel.to && key > sel.from && key < sel.to) cls.push("in");
      }else if(sel.day === key) cls.push("on");
      if(key === today) cls.push("today");
      h += '<button class="dp-day '+cls.join(" ")+'" data-d="'+key+'">'+d+"</button>";
    }
    return h;
  }
  function paint(){
    pop.querySelector(".dp-title").textContent = MONTHS[view.getMonth()]+" "+view.getFullYear();
    pop.querySelector(".dp-grid").innerHTML = grid();
    const foot = pop.querySelector(".dp-foot");
    if(foot){
      const txt = sel.from || sel.to ? (human(sel.from)||"…")+" — "+(human(sel.to)||"…") : "Період не вибрано";
      foot.querySelector(".dp-val").textContent = txt;
    }
  }
  function place(){
    const r = anchor.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    let left = Math.min(Math.max(8, r.left), innerWidth - w - 8);
    let top = r.bottom + 6;
    if(top + h > innerHeight - 8) top = Math.max(8, r.top - h - 6);
    pop.style.left = left+"px"; pop.style.top = top+"px";
  }
  function pick(key){
    if(cfg.mode === "range"){
      if(!sel.from || (sel.from && sel.to)){ sel = {from:key, to:""}; paint(); return; }
      sel.to = key;
      if(sel.to < sel.from){ const t = sel.from; sel.from = sel.to; sel.to = t; }
      paint();
      cfg.onPick({from:sel.from, to:sel.to});
      close();
    }else{
      sel.day = key; paint();
      cfg.onPick(key);
      close();
    }
  }
  function outside(e){ if(pop && !pop.contains(e.target) && e.target !== anchor) close(); }
  function key(e){ if(e.key === "Escape"){ e.stopPropagation(); close(); } }

  function open(el, opts){
    if(pop && anchor === el){ close(); return; }
    close();
    anchor = el; cfg = opts;
    sel = opts.mode === "range"
      ? { from:(opts.value&&opts.value.from)||"", to:(opts.value&&opts.value.to)||"" }
      : { day: opts.value || "" };
    const startFrom = (opts.mode === "range" ? sel.from : sel.day) || iso(new Date());
    view = parse(startFrom); view.setDate(1);
    pop = document.createElement("div");
    pop.className = "dpop";
    pop.innerHTML =
      '<div class="dp-head"><button class="dp-nav" data-m="-1">‹</button>'+
      '<span class="dp-title"></span><button class="dp-nav" data-m="1">›</button></div>'+
      '<div class="dp-grid"></div>'+
      (opts.mode === "range"
        ? '<div class="dp-foot"><span class="dp-val"></span><button class="dp-clear">Скинути</button></div>'
        : '<div class="dp-foot"><span class="dp-val">&nbsp;</span><button class="dp-clear">Сьогодні</button></div>');
    document.body.appendChild(pop);
    paint(); place();
    requestAnimationFrame(()=>pop && pop.classList.add("in"));
    pop.addEventListener("click", e=>{
      const nav = e.target.closest(".dp-nav");
      if(nav){ view.setMonth(view.getMonth() + (+nav.dataset.m)); paint(); return; }
      const day = e.target.closest(".dp-day[data-d]");
      if(day){ pick(day.dataset.d); return; }
      if(e.target.closest(".dp-clear")){
        if(cfg.mode === "range"){ sel = {from:"",to:""}; cfg.onPick({from:"",to:""}); }
        else cfg.onPick(iso(new Date()));
        close();
      }
    });
    setTimeout(()=>{
      document.addEventListener("pointerdown", outside);
      document.addEventListener("keydown", key);
    }, 0);
  }
  function close(){
    document.removeEventListener("pointerdown", outside);
    document.removeEventListener("keydown", key);
    if(pop && pop.parentNode) pop.parentNode.removeChild(pop);
    pop = null; anchor = null;
  }
  return { open, close, human };
})();
window.DatePicker = DatePicker;

/* ================= shadcn/ui · Attachment =================
   Перетаскивание картинок в слоты таймфреймов и в общую зону.
   Клик и Ctrl+V работают как раньше — это добавка, а не замена. */
const Attach = (function(){
  function stop(e){ e.preventDefault(); e.stopPropagation(); }
  function mount(root, onFiles){
    const zones = (root||document).querySelectorAll("[data-drop]");
    zones.forEach(z=>{
      z.addEventListener("dragenter", e=>{ stop(e); z.classList.add("dragover"); });
      z.addEventListener("dragover",  e=>{ stop(e); e.dataTransfer.dropEffect = "copy"; z.classList.add("dragover"); });
      z.addEventListener("dragleave", e=>{ stop(e); if(!z.contains(e.relatedTarget)) z.classList.remove("dragover"); });
      z.addEventListener("drop", e=>{
        stop(e); z.classList.remove("dragover");
        const files = [...(e.dataTransfer.files||[])].filter(f=>/^image\//.test(f.type));
        if(files.length) onFiles(files, z.dataset.drop || null);
      });
    });
  }
  return { mount };
})();
window.Attach = Attach;
