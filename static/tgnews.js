/* ============================================================
   Смужка над робочою областю: новини журналу — у Telegram-каналі.

   #main застосунок перемальовує цілком, тому смужка стоїть не в ньому,
   а над ним: #main загортається в колонку, і смужка — перший її рядок.
   Закрив хрестиком — більше не показується (localStorage).
   ============================================================ */
(function(){

const URL = "https://t.me/+gJ1ze8dCC6UzNDMy";
const KEY = "tj_tgnews_closed";

try{ if (localStorage.getItem(KEY)) return; }catch(e){}

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
  try{ localStorage.setItem(KEY, "1"); }catch(e){}
  bar.remove();
});

const realApply = window.applyLang;
if (typeof realApply === "function"){
  window.applyLang = function(){ const r = realApply.apply(this, arguments); paint(); return r; };
}

})();
