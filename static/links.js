/* ============================================================
   Зв'язки в «Аналітиці».

   Розріз по одному полю показує, що US100 в мінусі. Але мінус
   там не завжди й не скрізь — він в одній сесії, за однією
   моделлю. Щоб це побачити, доводилось перебирати поля руками.

   Тут перебираємо за людину: беремо осмислені пари полів,
   рахуємо кожне сполучення й показуємо ті, що справді щось
   вирішують. Дрібні вибірки відкидаємо — на трьох угодах
   висновків не буває.
   ============================================================ */
(function(){

/* Які пари полів має сенс дивитися. Пари на кшталт «результат ×
   помилки» пропущені: там залежність очевидна й нічого не пояснює. */
const COMBOS = [
  ["pair","session"], ["pair","entry_model"], ["pair","position"],
  ["session","entry_model"], ["session","position"],
  ["setup","session"], ["setup","entry_model"],
  ["bias","direction_type"], ["pair","direction_type"],
  ["entry_model","direction_type"],
];

const SHOW = 6;         // скільки показуємо з кожного боку

function label(k){
  const d = (typeof DIMS === "function") && DIMS().find(x => x.k === k);
  return d ? d.label : k;
}

/* Поріг вибірки: на дрібних числах відсоток нічого не означає.
   Беремо 3% від усіх угод, але не менше п'яти. */
function minSample(total){
  return Math.max(5, Math.round(total * 0.03));
}

function collect(list){
  const min = minSample(list.length);
  const out = [];
  for (const [a, b] of COMBOS){
    const buckets = new Map();
    for (const t of list){
      const va = fieldVal(t, a), vb = fieldVal(t, b);
      if (!va || !vb) continue;
      const key = va + " · " + vb;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(t);
    }
    for (const [name, arr] of buckets){
      if (arr.length < min) continue;
      const st = calc(arr);
      out.push({name, a, b, n: arr.length, st});
    }
  }
  return {rows: out, min};
}

function row(x){
  const wr = x.st.wr;
  return '<div class="lk-row">'
    + '<span class="nm">' + esc(x.name) + "</span>"
    + '<span class="of">' + esc(label(x.a)) + " · " + esc(label(x.b)) + "</span>"
    + '<span class="n">' + x.n + "</span>"
    + '<span class="wr">' + fmtPct(wr) + "</span>"
    + '<span class="net ' + clsR(x.st.net) + '">' + fmtR(x.st.net) + "</span>"
    + "</div>";
}

function block(title, rows){
  return '<div class="lk-col"><div class="lk-t">' + esc(title) + "</div>"
    + '<div class="lk-head"><span>' + esc(T.lkCombo) + '</span><span>' + esc(T.lkFields) + '</span>'
    + "<span>" + esc(T.kCount) + "</span><span>" + esc(T.kWinRate) + "</span><span>" + esc(T.kNetPct) + "</span></div>"
    + (rows.length ? rows.map(row).join("")
        : '<div class="lk-empty">' + esc(T.lkEmptyRow) + "</div>")
    + "</div>";
}

/* ---------- те, що вставляється в розділ ---------- */
function html(list){
  if (!list || list.length < 12) return "";
  const {rows, min} = collect(list);
  if (!rows.length){
    return '<div class="card lk"><h3>' + esc(T.lkTitle) + "</h3>"
      + '<div class="in"><div class="empty">' + esc(T.lkEmptyCard.replace("%d", min)) + "</div></div></div>";
  }

  const byNet = rows.slice().sort((x, y) => y.st.net - x.st.net);
  const good = byNet.filter(x => x.st.net > 0).slice(0, SHOW);
  const bad  = byNet.filter(x => x.st.net < 0).slice(-SHOW).reverse();

  return '<div class="card lk"><h3>' + esc(T.lkTitle)
    + '<i class="lk-hint">' + T.lkNote.replace("%d", min) + "</i></h3>"
    + '<div class="in">'
    + '<div class="lk-cols">'
    +   block(T.lkWorks, good)
    +   block(T.lkEats, bad)
    + "</div></div></div>";
}

window.__links = {html};

})();
