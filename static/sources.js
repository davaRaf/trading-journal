/* ============================================================
   Звідки про нас дізнались — розділ у «Налаштуваннях» для власників.

   Відповіді люди дають на першому екрані після входу (Source в app.js).
   Тут сервер їх рахує: по кожному джерелу — скільки всього і скільки за
   останні 7 днів, плюс скільки ще не відповіли. Хто не адмін — сервер
   каже 403, і розділу просто нема; нічого ховати на клієнті не треба.
   ============================================================ */
(function(){

let stat = null;      /* null — не адмін або ще не читали */

const NAMES = {blackswan: "BlackSwan", instagram: "Instagram", tiktok: "TikTok"};
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function load(){
  stat = null;
  try{ stat = await api("GET", "/api/admin/sources"); }
  catch(e){ stat = null; }          /* 403 — не наш розділ */
}

function label(id){
  if (!id) return T.srNone;
  if (id === "other") return T.hbOther;
  return NAMES[id] || id;
}

function section(){
  if (!stat || !stat.rows) return "";
  const max = Math.max(1, ...stat.rows.map(r => r.n));
  const rows = stat.rows.map(r =>
    '<div class="sr-row' + (r.id ? "" : " none") + '">'
    + '<span class="sr-nm">' + esc(label(r.id)) + "</span>"
    + '<span class="sr-n">' + r.n + (r.week ? ' <i>+' + r.week + " " + esc(T.srWeek) + "</i>" : "") + "</span>"
    + '<span class="sr-bar"><i style="width:' + Math.round(r.n / max * 100) + '%"></i></span>'
    + "</div>").join("");
  return '<div class="sr">'
    + '<p class="sr-lead">' + esc(T.srTotal) + " <b>" + stat.total + "</b> · " + esc(T.srAnswered) + " <b>" + stat.answered + "</b></p>"
    + rows + "</div>";
}

window.__sources = {load: load, section: section};

})();
