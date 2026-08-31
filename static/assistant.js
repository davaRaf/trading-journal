/* Помічник журналу: питання по своїх угодах і розбір помилок.
   Панель — той самий Sheet, що й у формі угоди: Escape, свайп, однакове тло. */
"use strict";

const Assistant = (function(){
  const HINTS = [
    "Який у мене вінрейт цього тижня?",
    "Де я найбільше зливаю?",
    "Як перестати відігруватися після стопа?",
    "Що робити, коли не тримаю угоду до цілі?",
  ];
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
        "<p>Питай звичайними словами — про свої угоди рахую по журналу, " +
        "про торгівлю загалом просто розповім.</p>" +
        '<div class="as-hints">' + HINTS.map(h =>
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
      log.push({who:"ai", text: r.answer || "Порожня відповідь."});
    }catch(e){
      log.push({who:"ai", text: "Не вийшло запитати: " + e.message});
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
    log.push({who:"me", text:"Подивись, що я роблю не так"});
    paint();
    try{
      const r = await api("POST", "/api/assistant/review", {history});
      const facts = (r.facts || []).map(f => "• " + f).join("\n");
      log.push({who:"ai", text: r.text
        ? r.text + (facts ? "\n\n" + facts : "")
        : (facts || "Поки що зачіпок немає — журнал рівний.")});
    }catch(e){
      log.push({who:"ai", text: "Не вийшло зібрати розбір: " + e.message});
    }
    busy = false;
    paint();
  }

  function open(){
    const h =
      '<div class="m-head"><h2>Помічник</h2>' +
        '<button class="x" onclick="closeModal()" aria-label="Закрити">×</button></div>' +
      '<div class="m-body as-body">' +
        '<div class="as-log" aria-live="polite"></div>' +
      "</div>" +
      '<div class="m-foot as-foot">' +
        '<textarea class="as-input" rows="3" placeholder="Спитати про журнал або про торгівлю…" ' +
          'aria-label="Питання до помічника"></textarea>' +
        '<div class="as-actions">' +
          '<button class="btn as-review" type="button" data-tip="Знайти збої в роботі: серії стопів, поспіх, ризик">Розбір помилок</button>' +
          '<span class="sp"></span>' +
          '<button class="btn primary as-send" type="button">Спитати</button>' +
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

  return { open, reset: () => { log = []; } };
})();

window.Assistant = Assistant;
function openAssistant(){ Assistant.open(); }
