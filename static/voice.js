/* ---------------- Голосове введення ---------------- */
/*
  Мікрофон усередині поля (правий нижній кут) — у «Як заходив» і в «Думки
  про угоду». Людина диктує, текст дописується в кінець поля.

  Пишемо MediaRecorder-ом і шлемо файл на сервер (/api/voice), а не беремо
  браузерне розпізнавання (SpeechRecognition). Причина — Safari: там
  SpeechRecognition обрізає запис на хвилині й нерідко віддає огризок, а
  MediaRecorder працює як усюди. Ціна рішення — запис їде на сервер і
  назад, тобто текст з'являється не під час мови, а за секунду після
  «Стоп».

  Текст дописуємо в кінець, а не замінюємо поле: надиктувати опис часто
  виходить за два-три підходи, і другий не має стирати перший.

  Поки пишемо, кільце навколо кнопки дихає за справжньою громкістю
  (AudioContext), а не блимає по таймеру: людині треба бачити, що її чують
  саме зараз, інакше «пишеться» й «пишеться тишу» виглядають однаково.
*/
const Voice = (function(){
  /* Довше не пишемо: це опис входу, а не подкаст. Межа ще й тримає ціну
     одного запису в межах копійок. */
  const MAX_SEC = 120;

  let rec = null, chunks = [], stream = null, timer = 0, began = 0;
  let active = "", busy = false;
  let ac = null, raf = 0;

  function can(){
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia
              && window.MediaRecorder);
  }

  /* Chrome і Firefox пишуть webm/opus, Safari — mp4/aac. Питаємо сам
     браузер, який формат він вміє: вгадувати по його назві означає
     ламатись на кожному новому. */
  function mime(){
    const want = ["audio/webm;codecs=opus", "audio/webm",
                  "audio/mp4", "audio/ogg;codecs=opus"];
    for(const m of want){
      try{ if(MediaRecorder.isTypeSupported(m)) return m; }catch(e){}
    }
    return "";
  }

  const ICON = '<svg class="micico" viewBox="0 0 24 24" aria-hidden="true">'+
    '<path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3Z"/>'+
    '<path d="M6 11v1a6 6 0 0 0 12 0v-1M12 19v2"/></svg>';

  /* Кнопка лежить усередині поля, тому віддаємо її рядком одразу за
     textarea (форма угоди збирається рядком, app.js). Браузер без
     мікрофона не отримує нічого: кнопки, яка не може працювати, краще
     не показувати. */
  /* opts.join — чим приклеювати надиктоване до того, що вже є: у полях на
     кілька значень це кома, інакше дві помилки злиплись би в одну. */
  function btn(id, opts){
    if(!can()) return "";
    opts = opts || {};
    /* title і aria-label обов'язкові: у спокої кнопка — лише іконка, і без
       них ні людина при наведенні, ні читач екрана не знають, що вона. */
    return '<button type="button" class="micbtn" '+
           'id="mic_'+id+'" data-join="'+(opts.join || " ")+'" '+
           'title="'+T.voiceStart+'" aria-label="'+T.voiceStart+'" '+
           'onclick="Voice.toggle(\''+id+'\')">'+ICON+
           '<span class="mictxt">'+T.voiceStart+'</span></button>';
  }

  function hint(id){ return '<span class="vhint" id="vh_'+id+'"></span>'; }

  function say(id, text){
    const el = document.getElementById("vh_" + id);
    if(el) el.textContent = text || "";
  }

  function wrap(id){
    const el = document.getElementById(id);
    return el && el.closest ? el.closest(".vwrap") : null;
  }

  function paint(id, state, sec){
    const b = document.getElementById("mic_" + id);
    if(!b) return;
    b.classList.toggle("on", state === "rec");
    b.classList.toggle("wait", state === "busy");
    b.disabled = state === "busy";
    /* Запис скінчився — знімаємо мітку живого рівня й гасимо кільце,
       інакше наступний запис почався б із чужої громкості. */
    if(state !== "rec"){
      b.classList.remove("live");
      b.style.setProperty("--lv", "0");
    }
    /* Поле світиться, поки пишемо: видно, куди саме поїде текст, коли
       на екрані два мікрофони. */
    const w = wrap(id);
    if(w) w.classList.toggle("rec", state === "rec");
    /* Другий мікрофон на час запису глухий — щоб не починати другий
       запис і не плутати, в яке поле приїде текст. */
    document.querySelectorAll(".micbtn").forEach(o => {
      if(o !== b) o.classList.toggle("off", state === "rec" || state === "busy");
    });
    const label = state === "rec" ? T.voiceStop
                : state === "busy" ? T.voiceBusy : T.voiceStart;
    b.title = label;
    b.setAttribute("aria-label", label);
    const t = b.querySelector(".mictxt");
    if(!t) return;
    if(state === "rec"){
      /* Разом із «Стоп», а не лише цифрами: червоне з таймером показує, що
         пишемо, але не те, що буде від натискання. */
      const s = sec || 0;
      t.textContent = T.voiceStop + " " + Math.floor(s / 60) + ":" +
                      String(s % 60).padStart(2, "0");
    }else{
      t.textContent = label;
    }
  }

  /* Кільце навколо кнопки за справжньою громкістю: voice.js ставить --lv,
     css робить із нього товщину кільця. Не вийшло (браузер не дав
     AudioContext) — кнопка лишається без класу live, і css дихає сама
     рівним темпом: це все одно краще за мертву кнопку. */
  function meter(id){
    const host = document.getElementById("mic_" + id);
    if(!host) return;
    let ctx;
    try{
      ctx = new (window.AudioContext || window.webkitAudioContext)();
    }catch(e){ return; }
    ac = ctx;
    /* Safari відкриває контекст «спящим», і без resume аналізатор
       віддає рівну тишу. */
    try{ if(ctx.state === "suspended") ctx.resume(); }catch(e){}
    let an;
    try{
      const src = ctx.createMediaStreamSource(stream);
      an = ctx.createAnalyser();
      an.fftSize = 256;
      src.connect(an);
    }catch(e){ return; }
    host.classList.add("live");
    const buf = new Uint8Array(an.fftSize);
    let smooth = 0;
    const loop = () => {
      if(!rec) return;                 /* запис уже спинили */
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for(let i = 0; i < buf.length; i++){
        const d = buf[i] - 128;
        sum += d * d;
      }
      /* Підсилюємо втричі: звичайна мова біля мікрофона ноутбука дає
         rms близько 0.1, і без множника смужки майже не ворушились би. */
      const lv = Math.min(1, Math.sqrt(sum / buf.length) / 128 * 3.2);
      /* Вгору беремо одразу, вниз — плавно: інакше кільце сіпається на
         кожній павзі між словами. */
      smooth = lv > smooth ? lv : smooth * .82 + lv * .18;
      host.style.setProperty("--lv", smooth.toFixed(3));
      raf = requestAnimationFrame(loop);
    };
    loop();
  }

  function release(){
    if(timer){ clearInterval(timer); timer = 0; }
    if(raf){ cancelAnimationFrame(raf); raf = 0; }
    if(ac){ try{ ac.close(); }catch(e){} ac = null; }
    if(stream){ stream.getTracks().forEach(t => t.stop()); stream = null; }
    rec = null; began = 0;
  }

  function toggle(id){
    if(busy) return;
    if(rec){
      /* Клік по чужому мікрофону під запис — нічого: інакше текст поїхав
         би не в те поле, яке світиться. */
      if(id === active) stop();
      return;
    }
    start(id);
  }

  async function start(id){
    const m = mime();
    try{
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
    }catch(e){
      /* Відмова в доступі й відсутній мікрофон — для людини різні речі:
         перше лікується дозволом у браузері, друге — ні. */
      stream = null;
      return say(id, e && e.name === "NotAllowedError" ? T.voiceDenied : T.voiceNoMic);
    }
    say(id, "");
    chunks = [];
    try{
      rec = new MediaRecorder(stream, m ? {mimeType: m} : undefined);
    }catch(e){
      release();
      return say(id, T.voiceFailed);
    }
    active = id;
    rec.ondataavailable = e => { if(e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => send(id);
    rec.start();
    began = Date.now();
    paint(id, "rec", 0);
    meter(id);
    timer = setInterval(() => {
      const s = Math.round((Date.now() - began) / 1000);
      /* Дійшли до межі — спиняємось самі, інакше забутий відкритим
         мікрофон поїхав би на сервер цілою годиною. */
      if(s >= MAX_SEC){ say(id, T.voiceMax); return stop(); }
      paint(id, "rec", s);
    }, 300);
  }

  function stop(){
    if(!rec) return;
    try{ rec.stop(); }catch(e){}
    if(timer){ clearInterval(timer); timer = 0; }
  }

  async function send(id){
    const type = (chunks[0] && chunks[0].type) || mime() || "audio/webm";
    const blob = new Blob(chunks, {type});
    chunks = [];
    release();
    active = "";
    /* Натиснули «Стоп» одразу після «Диктувати» — писати нічого. */
    if(blob.size < 1200){
      paint(id, "idle");
      return say(id, T.voiceShort);
    }
    busy = true;
    paint(id, "busy");
    try{
      const b64 = await toB64(blob);
      const got = await api("POST", "/api/voice",
                            {audio: b64, mime: type, lang: LANG});
      insert(id, (got && got.text) || "");
      say(id, "");
    }catch(e){
      say(id, why(e));
    }
    busy = false;
    paint(id, "idle");
  }

  function toB64(blob){
    return new Promise((ok, no) => {
      const fr = new FileReader();
      /* readAsDataURL, а не байт за байтом: на двох хвилинах запису
         ручний цикл по байтах підвішує сторінку, а тут усе робить сам
         браузер. Відрізаємо голову "data:audio/webm;base64,". */
      fr.onload = () => ok(String(fr.result).split(",")[1] || "");
      fr.onerror = () => no(new Error("read"));
      fr.readAsDataURL(blob);
    });
  }

  function why(e){
    const map = {no_voice: T.voiceOff, bad_audio: T.voiceNoWords,
                 too_many: T.voiceTooMany, voice_failed: T.voiceFailed,
                 too_big: T.voiceLong};
    if(e && e.code && map[e.code]) return map[e.code];
    /* Гість і чужий журнал кидають свої мітки — їм api() вже показав
       своє вікно, і другий рядок тут був би зайвим. */
    if(e && (e.message === "guest" || e.message === "pub")) return "";
    return T.voiceFailed;
  }

  function insert(id, text){
    const el = document.getElementById(id);
    if(!el) return;
    text = (text || "").trim();
    if(!text) return say(id, T.voiceNoWords);
    const b = document.getElementById("mic_" + id);
    const join = (b && b.dataset.join) || " ";
    /* Хвіст прибираємо разом із роздільником: у полі на кілька значень
       після «＋» уже лежить «помилка, », і без цього вийшло б «, , ». */
    const had = el.value.replace(/[\s,]+$/, "");
    el.value = had ? had + join + text : text;
    /* Поле слухає oninput: від нього залежать підписи під скрінами
       (entryTyped) і збереження чернетки. Присвоєння value події не
       дає — надсилаємо її самі. */
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.focus();
    try{ el.selectionStart = el.selectionEnd = el.value.length; }catch(e){}
  }

  return {can, btn, hint, toggle};
})();
/* Через window, а не самим const: форма угоди перевіряє window.Voice, а
   const у звичайному <script> властивістю window не стає (як ShotTap). */
window.Voice = Voice;
