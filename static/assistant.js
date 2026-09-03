/* Помічник журналу: питання по своїх угодах і розбір помилок.
   Панель — той самий Sheet, що й у формі угоди: Escape, свайп, однакове тло. */
"use strict";

const Assistant = (function(){
  function HINTS(){ return [
    T.asHint1, T.asHint2, T.asHint3, T.asHint4,
  ]; }
  let log = [];          // {who:"me"|"ai", text}
  let busy = false;

  const esc = s => String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

  /* модель відповідає звичайним текстом: абзаци лишаємо, решту екрануємо */
  function fmt(text){
    return esc(text).trim().split(/\n{2,}/).map(p =>
      "<p>" + p.replace(/\n/g, "<br>") + "</p>").join("");
  }

  function bodyHtml(){
    if(!log.length){
      return '<div class="as-empty">' +
        "<p>" + T.asIntro + "</p>" +
        '<div class="as-hints">' + HINTS().map(h =>
          '<button type="button" class="as-hint" data-q="' + esc(h) + '">' + esc(h) + "</button>"
        ).join("") + "</div></div>";
    }
    return log.map(m => m.who === "me"
      ? '<div class="as-msg me"><div class="as-bubble">' + esc(m.text) + "</div></div>"
      : '<div class="as-msg ai"><div class="as-bubble">' + fmt(m.text) + "</div></div>"
    ).join("") + (busy
      ? '<div class="as-msg ai"><div class="as-bubble as-wait"><i></i><i></i><i></i></div></div>'
      : "");
  }

  function paint(){
    const box = document.querySelector(".as-log");
    if(!box) return;
    box.innerHTML = bodyHtml();
    box.scrollTop = box.scrollHeight;      // остання відповідь завжди на очах
    box.querySelectorAll(".as-hint").forEach(b =>
      b.onclick = () => send(b.dataset.q));
    const send_btn = document.querySelector(".as-send");
    const field = document.querySelector(".as-input");
    if(send_btn) send_btn.disabled = busy;
    if(field) field.disabled = busy;
  }

  async function send(text){
    text = (text || "").trim();
    if(!text || busy) return;
    const history = log.slice(-8);      // розмова триває: модель бачить попередні репліки
    log.push({who:"me", text});
    busy = true;
    const field = document.querySelector(".as-input");
    if(field){ field.value = ""; field.style.height = ""; }
    paint();
    try{
      const r = await api("POST", "/api/assistant/ask", {question: text, history});
      log.push({who:"ai", text: r.answer || T.asEmptyAnswer});
    }catch(e){
      log.push({who:"ai", text: T.asAskFailed + e.message});
    }
    busy = false;
    paint();
    const f = document.querySelector(".as-input");
    if(f) f.focus();
  }

  async function review(){
    if(busy) return;
    const history = log.slice(-8);   // за нею помічник впізнає мову розмови
    busy = true;
    log.push({who:"me", text:T.asReviewMsg});
    paint();
    try{
      const r = await api("POST", "/api/assistant/review", {history});
      const facts = (r.facts || []).map(f => "• " + f).join("\n");
      log.push({who:"ai", text: r.text
        ? r.text + (facts ? "\n\n" + facts : "")
        : (facts || T.asNothingFound)});
    }catch(e){
      log.push({who:"ai", text: T.asReviewFailed + e.message});
    }
    busy = false;
    paint();
  }

  function open(){
    const h =
      '<div class="m-head"><h2>' + T.asTitle + '</h2>' +
        '<button class="x" onclick="closeModal()" aria-label="' + T.mrClose + '">×</button></div>' +
      '<div class="m-body as-body">' +
        '<div class="as-log" aria-live="polite"></div>' +
      "</div>" +
      '<div class="m-foot as-foot">' +
        '<textarea class="as-input" rows="3" placeholder="' + T.asInputPh + '" ' +
          'aria-label="' + T.asInputAria + '"></textarea>' +
        '<div class="as-actions">' +
          '<button class="btn as-review" type="button" data-tip="' + T.asReviewTip + '">' + T.asReviewBtn + '</button>' +
          '<span class="sp"></span>' +
          '<button class="btn primary as-send" type="button">' + T.asAskBtn + '</button>' +
        "</div>" +
      "</div>";
    Sheet.open(h, {cls:"as-panel"});
    paint();

    const field = document.querySelector(".as-input");
    const btn = document.querySelector(".as-send");
    if(btn) btn.onclick = () => send(field ? field.value : "");
    const rev = document.querySelector(".as-review");
    if(rev) rev.onclick = review;
    if(field){
      /* Enter відправляє, Shift+Enter — новий рядок */
      field.onkeydown = e => {
        if(e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(field.value); }
      };
      field.oninput = () => {           // поле росте під текст, але не безмежно
        field.style.height = "auto";
        field.style.height = Math.min(field.scrollHeight, 200) + "px";
      };
      setTimeout(() => field.focus(), 60);
    }
  }

  /* ---------- репліка: коли помічник каже сам ----------
     Не сповіщення й не модалка: фраза виїжджає над кнопкою, живе
     недовго й зникає. Нічого не блокує — людина може її просто не
     помітити, і це нормально. */
  let sayTimer = null;
  let audio = null;

  /* Коротке «дзінь» на два тони. Файлом тягнути звук заради 150 мс не
     варто, тому складаємо його тут же. */
  function ctx(){
    try{
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if(!Ctx) return null;
      audio = audio || new Ctx();
      return audio;
    }catch(e){ return null; }
  }

  /* Браузер не дає звучати, поки людина нічого не натиснула, і створений
     до того контекст лишається сплячим — саме через це репліка виїжджала
     мовчки. Тому будимо його на першу ж дію: до появи репліки він уже
     готовий. */
  ["pointerdown", "keydown"].forEach(ev =>
    document.addEventListener(ev, () => {
      const a = ctx();
      if(a && a.state === "suspended") a.resume();
    }, {passive: true}));

  function tone(a, hz, at, dur, peak){
    const t = a.currentTime + at;
    const osc = a.createOscillator();
    const vol = a.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(hz, t);
    vol.gain.setValueAtTime(0.0001, t);
    vol.gain.exponentialRampToValueAtTime(peak, t + 0.015);
    vol.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(vol).connect(a.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  }

  function ping(){
    const a = ctx();
    if(!a) return "no-audio";
    const play = () => { tone(a, 700, 0, 0.16, 0.14); tone(a, 940, 0.08, 0.18, 0.1); };
    /* сплячий контекст не рахує час, тому граємо вже після пробудження */
    if(a.state === "suspended"){
      a.resume().then(play).catch(() => {});
      return "resuming";
    }
    play();
    return a.state;
  }

  /* Маскот на мить усміхається: репліка має виглядати як його слова. */
  function grin(){
    const btn = document.getElementById("asFabBtn");
    if(!btn) return;
    btn.dataset.em = "happy";
    setTimeout(() => { if(btn.dataset.em === "happy") delete btn.dataset.em; }, 1400);
  }

  function hush(){
    const box = document.querySelector(".as-say");
    if(!box) return;
    clearTimeout(sayTimer);
    box.classList.remove("in");
    setTimeout(() => box.remove(), 240);   // під час анімації зникнення
  }

  /* text — головна фраза, opts.facts — короткі рядки під нею,
     opts.actions — до двох кнопок {label, main, run}. */
  function say(text, opts){
    opts = opts || {};
    if(!text && !(opts.facts || []).length) return;
    hush();
    const box = document.createElement("div");
    box.className = "as-say";
    box.innerHTML =
      '<button type="button" class="x" aria-label="' + esc(T.mrClose) + '">×</button>'
      + (opts.cap ? '<span class="cap">' + esc(opts.cap) + "</span>" : "")
      + '<p class="tx">' + esc(text || "") + "</p>"
      + ((opts.facts || []).length
          ? '<ul class="facts">' + opts.facts.map(f => "<li>" + esc(f) + "</li>").join("") + "</ul>"
          : "")
      + '<div class="acts"></div>';
    document.body.appendChild(box);

    const acts = box.querySelector(".acts");
    (opts.actions || []).slice(0, 2).forEach(a => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = a.label;
      if(a.main) b.className = "main";
      b.onclick = () => { hush(); if(a.run) a.run(); };
      acts.appendChild(b);
    });
    if(!acts.children.length) acts.remove();
    box.querySelector(".x").onclick = hush;

    requestAnimationFrame(() => box.classList.add("in"));
    ping();
    grin();
    /* мовчазне зникнення: довгий текст читають довше */
    const life = Math.min(40000, 9000 + (text || "").length * 55);
    sayTimer = setTimeout(hush, life);
  }

  /* Питання в чат від імені людини — коли вона натиснула «розібратись». */
  function bring(question){
    hush();
    open();
    send(question);
  }

  return { open, say, hush, bring, sound: ping, reset: () => { log = []; } };
})();

window.Assistant = Assistant;

/* маскот на кнопці стежить очима за курсором: зсуваємо тільки внутрішню
   групу .as-fab-face, обмежуючи зсув, щоб очі не вилазили за межі "екрана" */
(function(){
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const MAX = 6;          // граничний зсув в одиницях viewBox іконки (0..40)
  const REACH = 140;      // px від кнопки, на якому зсув вже максимальний
  let mx = null, my = null, raf = null;

  function apply(){
    raf = null;
    const btn = document.getElementById("asFabBtn");
    const face = btn && btn.querySelector(".as-fab-face");
    if (!btn || !face || mx == null) return;
    const r = btn.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const dx = mx - cx, dy = my - cy;
    const len = Math.hypot(dx, dy) || 1;
    const k = Math.min(1, len / REACH);
    const ox = (dx / len) * MAX * k, oy = (dy / len) * MAX * k;
    face.style.transform = "translate(" + ox.toFixed(2) + "px," + oy.toFixed(2) + "px)";
  }

  document.addEventListener("mousemove", e => {
    mx = e.clientX; my = e.clientY;
    if (!raf) raf = requestAnimationFrame(apply);
  }, {passive:true});
})();

/* час від часу маскот показує вираз обличчя: happy / wink / surprised / yawn,
   тримає його якийсь час і повертається до нейтрального (позіхання — довше за решту) */
(function(){
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const HOLD = {happy:1100, wink:1100, surprised:1100, yawn:2100};
  const EMOTIONS = Object.keys(HOLD);

  function schedule(){
    const delay = 6000 + Math.random() * 9000; // раз на 6-15с
    setTimeout(() => {
      const btn = document.getElementById("asFabBtn");
      if (btn){
        const em = EMOTIONS[Math.floor(Math.random() * EMOTIONS.length)];
        btn.dataset.em = em;
        setTimeout(() => { delete btn.dataset.em; }, HOLD[em]);
      }
      schedule();
    }, delay);
  }
  schedule();
})();
function openAssistant(){ Assistant.open(); }
