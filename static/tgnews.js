/* ============================================================
   Смужка над робочою областю: новини журналу — у Telegram-каналі.

   #main застосунок перемальовує цілком, тому смужка стоїть не в ньому,
   а над ним: #main загортається в колонку, і смужка — перший її рядок.
   Перейшов за посиланням у канал — смужка більше не показується ніколи.
   Закрив хрестиком, не перейшовши, — ховається до кінця дня, наступного
   дня з'являється знову. Обидва стани живуть у localStorage цього браузера.
   ============================================================ */
(function(){

const URL = "https://t.me/+gJ1ze8dCC6UzNDMy";
const KEY = "tj_tgnews_closed";     // дата закриття хрестиком, за місцевим часом
const KEY_GO = "tj_tgnews_opened";  // перейшов у канал

function today(){
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-" + String(d.getDate()).padStart(2,"0");
}

try{
  if (localStorage.getItem(KEY_GO)) return;
  if (localStorage.getItem(KEY) === today()) return;
}catch(e){}

const main = document.getElementById("main");
if (!main) return;

const col = document.createElement("div");
col.className = "tgn-col";
main.parentNode.insertBefore(col, main);

const bar = document.createElement("div");
bar.className = "tgn";
bar.setAttribute("role", "region");
bar.innerHTML =
  '<span class="tgn-ic" aria-hidden="true"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">'
  + '<path d="M21.5 3.5L2.8 10.7c-1 .4-1 1.9.1 2.2l4.6 1.4 1.8 5.6c.3.9 1.4 1.1 2 .4l2.6-2.6 4.7 3.5c.8.6 1.9.1 2.1-.9L23 4.9c.2-1-.7-1.8-1.5-1.4z"/></svg></span>'
  + '<p class="tgn-txt"><b></b> <span></span></p>'
  + '<a class="tgn-cta" href="' + URL + '" target="_blank" rel="noopener"></a>'
  + '<button class="tgn-x" type="button"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
  + '<path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>';

col.appendChild(bar);
col.appendChild(main);

function paint(){
  const t = window.T || {};
  bar.querySelector(".tgn-txt b").textContent = t.tgNewsLead || "";
  bar.querySelector(".tgn-txt span").textContent = t.tgNewsText || "";
  bar.querySelector(".tgn-cta").textContent = (t.tgNewsCta || "") + " →";
  bar.querySelector(".tgn-x").setAttribute("aria-label", t.tgNewsClose || "");
  bar.setAttribute("aria-label", "Telegram");
}
paint();

bar.querySelector(".tgn-x").addEventListener("click", function(){
  try{ localStorage.setItem(KEY, today()); }catch(e){}
  bar.remove();
});

/* перехід у канал: і звичайний клік, і середня кнопка миші (нова вкладка) */
function opened(e){
  if (e.type === "auxclick" && e.button !== 1) return;
  try{ localStorage.setItem(KEY_GO, "1"); }catch(err){}
  bar.remove();
}
const cta = bar.querySelector(".tgn-cta");
cta.addEventListener("click", opened);
cta.addEventListener("auxclick", opened);

const realApply = window.applyLang;
if (typeof realApply === "function"){
  window.applyLang = function(){ const r = realApply.apply(this, arguments); paint(); return r; };
}

})();
