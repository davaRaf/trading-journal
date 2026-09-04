/* ============================================================
   Репліка з новинами дня.

   Той самий список, що бот шле в Телеграм (news_msg.py), тільки словами
   сторінки: помічник каже його сам, час від часу, і показує лише те, що
   ще попереду — про новину, яка вже вийшла, нагадувати нема сенсу.

   Манери спільні з рештою реплік (static/watch.js): не одразу після
   заходу, не поверх відкритого вікна, не в чужому журналі й не частіше,
   ніж дозволяє загальний ліміт розмовності.
   ============================================================ */
(function(){

const KEY = "tj_newsay";
const WAIT = 90 * 1000;             // скільки мовчимо після заходу
const AGAIN = 2 * 60 * 60 * 1000;   // як часто перевіряємо в довгій сесії
const PER_DAY = 2;                  // більше двох нагадувань на день — це вже нудьга
const ROWS = 4;                     // скільки новин показуємо поіменно

const FLAG = {USD:"🇺🇸", EUR:"🇪🇺", GBP:"🇬🇧", JPY:"🇯🇵", CHF:"🇨🇭",
              CAD:"🇨🇦", AUD:"🇦🇺", NZD:"🇳🇿", CNY:"🇨🇳", ALL:"🌍"};

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

function mine(){                     // свій ліміт, окремо від решти приводів
  const s = state();
  return !(s.day === today() && (s.count || 0) >= PER_DAY);
}

function noted(){
  const s = state();
  const day = today();
  keep({day: day, count: s.day === day ? (s.count || 0) + 1 : 1});
  if (window.Watch && Watch.noted) Watch.noted();   // ліміт розмовності спільний
}

function hh(d){
  return String(d.getHours()).padStart(2, "0") + ":"
       + String(d.getMinutes()).padStart(2, "0");
}

/* «1 новина», «2 новини», «5 новин» — і те саме іншими мовами */
function word(n){
  if (LANG === "en") return n === 1 ? T.nsWord1 : T.nsWord2;
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return T.nsWord1;
  if (a >= 2 && a <= 4 && !(b >= 12 && b <= 14)) return T.nsWord2;
  return T.nsWord5;
}

/* Важливі новини, які сьогодні ще попереду. */
async function ahead(){
  let data;
  try{
    const res = await fetch("/api/calendar");
    if (!res.ok) return [];
    data = await res.json();
  }catch(e){ return []; }

  const now = new Date();
  return (data.events || [])
    .map(e => ({...e, _d: new Date(e.date)}))
    .filter(e => !isNaN(e._d)
              && (e.impact || "").toLowerCase() === "high"
              && e._d > now
              && e._d.toDateString() === now.toDateString())
    .sort((a, b) => a._d - b._d);
}

async function tell(){
  if (typeof DEMO !== "undefined" && DEMO) return;
  if (!mine()) return;
  if (window.Watch && Watch.mayTalk && !Watch.mayTalk()) return;

  const list = await ahead();
  if (!list.length) return;
  if (window.Watch && Watch.mayTalk && !Watch.mayTalk()) return;   // поки ходили — могло змінитись

  const facts = list.slice(0, ROWS).map(e =>
    hh(e._d) + "  " + (FLAG[(e.country || "").toUpperCase()] || "🏳️")
    + " " + (e.country || "") + " — " + (e.title || ""));
  if (list.length > ROWS)
    facts.push(T.nsMore.replace("{n}", list.length - ROWS));

  Assistant.say(
    T.nsSay.replace("{n}", list.length)
           .replace("{w}", word(list.length))
           .replace("{t}", hh(list[0]._d)),
    {cap: T.ndCap, facts: facts,
     actions: [{label: T.ndOpen, run: () => { location.hash = "#news"; }}]});
  noted();
}

setTimeout(tell, WAIT);
setInterval(tell, AGAIN);

window.NewSay = {tell: tell};

})();
