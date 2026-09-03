/* ============================================================
   Помічник, який дивиться сам.

   Дві речі, які він робить без запиту:

     * звіряє щойно записану угоду з описаною ТС і каже, якщо вона
       розійшлася з правилами (сервер: ts_check.py);
     * час від часу питає щось по журналу — щоб не бути мовчазною
       кнопкою в кутку.

   Приличия важливіші за розумність: не одразу після заходу, не частіше
   ніж раз на кілька годин, не більше двох разів на день і ніколи поверх
   відкритої форми. Відхилення від ТС — виняток: воно про те, що людина
   зробила щойно, і чекати кілька годин безглуздо.
   ============================================================ */
(function(){

const KEY = "tj_nudge";
const PAUSE = 60 * 1000;             // скільки мовчимо після заходу
const GAP = 4 * 60 * 60 * 1000;      // не частіше, ніж раз на чотири години
const PER_DAY = 2;                   // і не більше двох разів на день

function state(){
  try{
    const v = JSON.parse(localStorage.getItem(KEY) || "{}");
    return (v && typeof v === "object") ? v : {};
  }catch(e){ return {}; }
}

function keep(v){
  try{ localStorage.setItem(KEY, JSON.stringify(v)); }catch(e){}
}

function today(){
  const d = new Date();
  return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
}

/* Чи можна зараз заговорити. Окремою функцією, щоб правило було одне
   на всі приводи, а не розсипане по місцях виклику. */
function mayTalk(){
  if(window.Pub && Pub.on) return false;          // чужий журнал — не наш дім
  if(window.Guest && Guest.on) return false;      // гостю ще нема про що казати
  if(document.querySelector(".pnl-wrap")) return false;
  const modal = document.getElementById("modal");
  if(modal && !modal.hidden) return false;
  const s = state();
  if(s.day === today() && (s.count || 0) >= PER_DAY) return false;
  if(s.last && Date.now() - s.last < GAP) return false;
  return true;
}

function noted(){
  const s = state();
  const day = today();
  keep({last: Date.now(), day: day, count: s.day === day ? (s.count || 0) + 1 : 1});
}

/* ---------------- звірка угоди з ТС ---------------- */

/* Підписи до кодів відхилень: сервер рахує, а називає це сторінка —
   інакше фрази довелось би тримати трьома мовами на боці сервера. */
function fact(it){
  const tpl = T["tc_" + it.code];
  if(!tpl) return "";
  return tpl.replace("%w", it.want || "").replace("%g", it.got || "");
}

/* Звіряти нема за що: у ТС порожні всі поля, з яких беруться правила,
   або описані самі моделі, а в угоді це поле не заповнене. Кажемо про це
   раз на день — інакше це перетворюється на щоденне бурчання. */
const HINT_KEY = "tj_tshint";

function thin(hint){
  if(!hint) return;
  let last = "";
  try{ last = localStorage.getItem(HINT_KEY) || ""; }catch(e){}
  const day = new Date().toISOString().slice(0, 10);
  if(last === day) return;
  try{ localStorage.setItem(HINT_KEY, day); }catch(e){}
  Assistant.say(T["tc_" + hint] || "", {
    cap: T.tcCap,
    actions: [{label: T.tcFill, main: true, run: () => { location.hash = "ts"; }}],
  });
}

async function afterTrade(id){
  if(!id || DEMO) return;
  if(window.Pub && Pub.on) return;
  let r;
  try{
    r = await api("POST", "/api/ts/check", {id: id, lang: LANG});
  }catch(e){ return; }                 // немає ТС, немає ключа — просто тиша
  const items = (r && r.items) || [];
  if(!items.length){ thin(r && r.hint); return; }
  const facts = items.map(fact).filter(Boolean);
  Assistant.say(r.text || facts.shift() || "", {
    cap: T.tcCap,
    facts: facts,
    actions: [{label: T.tcAsk, main: true, run: () => Assistant.bring(T.tcAskQ)}],
  });
}

/* ---------------- питання від помічника ---------------- */

/* Модель переказує привід своїми словами, але може й мовчати — немає
   ключа або не відповіла. Тоді фразу бере сторінка: приводи наперед
   відомі, а тексти до них лежать трьома мовами. */
function words(r){
  if(r.text) return r.text;
  const tpl = T["nd_" + r.code];
  if(!tpl) return "";
  const fill = r.fill || {};
  return tpl.replace("%n", fill.n != null ? fill.n : "")
            .replace("%s", fill.net != null ? fill.net : "");
}

async function ask(){
  if(DEMO || !mayTalk()) return false;
  let r;
  try{
    r = await api("POST", "/api/assistant/nudge", {lang: LANG});
  }catch(e){ return false; }
  if(!r || !r.code || !mayTalk()) return false;
  const text = words(r);
  if(!text) return false;
  const acts = [];
  if(r.ask) acts.push({label: T.tcAsk, main: true, run: () => Assistant.bring(r.ask)});
  if(r.view) acts.push({label: T.ndOpen, run: () => { location.hash = r.view; }});
  Assistant.say(text, {cap: T.ndCap, actions: acts});
  noted();
  return true;
}

window.Watch = {
  afterTrade: afterTrade,
  ask: ask,
  mayTalk: mayTalk,
  noted: noted,
};

/* Перше слово — не одразу: людина щойно зайшла й дивиться свої цифри. */
setTimeout(ask, PAUSE);

})();
