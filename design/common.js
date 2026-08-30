/* Общие утилиты для трёх вариантов дизайна.
   Данные считаются в data.js по тем же формулам, что и в app.py/app.js. */
const $ = s => document.querySelector(s);
const MON  = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
const MONF = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const WD = ["пн","вт","ср","чт","пт","сб","вс"];

const fmt  = v => (v > 0 ? "+" : "") + v.toFixed(2) + "%";
const fmt1 = v => (v > 0 ? "+" : "") + v.toFixed(1) + "%";
const sign = v => v > 0.0001 ? "pos" : v < -0.0001 ? "neg" : "be";
const tagOf = r => r === "Win" ? "TP" : r === "Loss" ? "SL" : r.replace("-", "−");

/* Полный набор показателей — тот же, что в базовой версии журнала */
function metrics(st){
  return [
    ["Сделок",        st.n,                                  ""],
    ["Win Rate",      st.wr == null ? "·" : st.wr + "%",     ""],
    ["Итог, %",       fmt(st.net),                           sign(st.net)],
    ["Средний RR",    st.avgRR ?? "·",                       ""],
    ["Profit Factor", st.pf ?? "·",                          ""],
    ["TP / SL / BE",  st.wins + " / " + st.loss + " / " + st.be, ""],
    ["BE− / BE+",     st.bem + " / " + st.bep,               ""],
    ["Средний риск",  (st.avgRisk ?? "·") + "%",             ""],
  ];
}

/* Сглаженная кривая по точкам */
function smooth(pts){
  let d = "M" + pts[0][0] + "," + pts[0][1];
  for (let i = 1; i < pts.length; i++){
    const [px, py] = pts[i - 1], [cx, cy] = pts[i], mx = (px + cx) / 2;
    d += " C" + mx + "," + py + " " + mx + "," + cy + " " + cx + "," + cy;
  }
  return d;
}

/* Кривая эквити по календарным датам */
function equitySVG(el, {W = 640, H = 180, pad = 10, stroke = "rgba(255,255,255,.72)", fill = "rgba(255,255,255,.18)", grid = true} = {}){
  const vals = D.eq, days = D.days, dmax = days[days.length - 1] || 364;
  const max = Math.max(...vals, 0), min = Math.min(...vals, 0);
  const x = i => days[i] / dmax * W;
  const y = v => H - pad - (v - min) / ((max - min) || 1) * (H - pad * 2);
  const d = smooth(vals.map((v, i) => [x(i), y(v)]));
  const last = vals.length - 1;
  const lines = grid ? [0, .25, .5, .75, 1].map(p =>
    '<line x1="0" y1="' + (pad + p * (H - pad * 2)) + '" x2="' + W + '" y2="' + (pad + p * (H - pad * 2)) +
    '" stroke="rgba(255,255,255,.055)" stroke-width="1" vector-effect="non-scaling-stroke"/>').join("") : "";
  el.setAttribute("viewBox", "0 0 " + W + " " + H);
  el.innerHTML =
    '<defs><linearGradient id="ge' + el.id + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + fill + '"/><stop offset="100%" stop-color="rgba(255,255,255,0)"/>' +
    '</linearGradient></defs>' + lines +
    '<path d="' + d + ' L' + x(last) + ',' + H + ' L' + x(0) + ',' + H + ' Z" fill="url(#ge' + el.id + ')"/>' +
    '<path d="' + d + '" fill="none" stroke="' + stroke + '" stroke-width="1.7" vector-effect="non-scaling-stroke"/>' +
    '<circle cx="' + x(last) + '" cy="' + y(vals[last]) + '" r="3" fill="#fff" opacity=".85"/>';
  return {min, max};
}

/* Столбики результата по месяцам */
function monthBarsSVG(el, {W = 240, H = 52, gap = 5} = {}){
  const vals = D.mon.map(m => m[1]);
  const max = Math.max(...vals.map(Math.abs));
  const bw = (W - gap * (vals.length - 1)) / vals.length;
  const zero = H * .62;
  el.setAttribute("viewBox", "0 0 " + W + " " + H);
  el.innerHTML = vals.map((v, i) => {
    const h = Math.max(2, Math.abs(v) / max * (v > 0 ? zero - 3 : H - zero - 3));
    return '<rect x="' + (i * (bw + gap)) + '" y="' + (v >= 0 ? zero - h : zero) + '" width="' + bw +
           '" height="' + h + '" rx="2.5" fill="rgba(255,255,255,' + (v >= 0 ? .46 : .24) + ')"/>';
  }).join("") +
  '<line x1="0" y1="' + zero + '" x2="' + W + '" y2="' + zero + '" stroke="rgba(255,255,255,.10)" stroke-width="1" vector-effect="non-scaling-stroke"/>';
}

/* Календарь месяца — квадратики дней, как в базовой версии */
function calendarHTML({compact = false} = {}){
  const cells = [];
  for (let i = 0; i < D.first; i++) cells.push('<div class="day empty"></div>');
  for (const g of D.grid){
    if (!g.n){
      cells.push('<div class="day"><span class="dn">' + g.d + '</span></div>');
      continue;
    }
    const cls = sign(g.r);
    const tags = compact
      ? '<span class="dots">' + g.tags.map(t => '<i class="' + (t === "Win" ? "w" : t === "Loss" ? "l" : "b") + '"></i>').join("") + '</span>'
      : '<span class="tags">' + g.tags.map(t =>
          '<b class="' + (t === "Win" ? "w" : t === "Loss" ? "l" : "b") + '">' + tagOf(t) + '</b>').join("") + '</span>';
    cells.push('<div class="day ' + cls + '"><span class="dn">' + g.d + '</span>' + tags +
               '<span class="dr">' + (Math.abs(g.r) < .005 ? "0%" : fmt1(g.r)) + '</span></div>');
  }
  return '<div class="cal-wd">' + WD.map(w => "<span>" + w + "</span>").join("") + "</div>" +
         '<div class="cal">' + cells.join("") + "</div>";
}

/* подписи оси X — только месяцы, по которым есть сделки */
function xLabels(el){
  el.style.gridTemplateColumns = "repeat(" + D.mon.length + ",1fr)";
  el.innerHTML = D.mon.map(m => "<span>" + MON[+m[0].slice(5,7) - 1] + "</span>").join("");
}

/* Лента последних дней — компактные квадратики для дашборда */
function stripHTML(){
  const [Y, M] = D.curYm.split("-").map(Number);
  return D.strip.map(g => {
    const wd = WD[(new Date(Y, M - 1, g.d).getDay() + 6) % 7];
    if (!g.n) return '<div class="day"><span class="wd">' + wd + '</span><span class="dn">' + g.d + '</span></div>';
    const tags = '<span class="tags">' + g.tags.map(t =>
      '<b class="' + (t === "Win" ? "w" : t === "Loss" ? "l" : "b") + '">' + tagOf(t) + '</b>').join("") + '</span>';
    return '<div class="day ' + sign(g.r) + '"><span class="wd">' + wd + '</span><span class="dn">' + g.d + '</span>' +
           tags + '<span class="dr">' + (Math.abs(g.r) < .005 ? "0%" : fmt1(g.r)) + '</span></div>';
  }).join("");
}

/* Столбики результата по месяцам — компактно, для шапки дашборда */
function monthSparkSVG(el, {W = 260, H = 72, gap = 6} = {}){
  const vals = D.mon.map(m => m[1]);
  const max = Math.max(...vals.map(Math.abs));
  const bw = (W - gap * (vals.length - 1)) / vals.length;
  const zero = H * .58;
  el.setAttribute("viewBox", "0 0 " + W + " " + H);
  el.innerHTML = vals.map((v, i) => {
    const h = Math.max(3, Math.abs(v) / max * (v > 0 ? zero - 12 : H - zero - 12));
    const lab = '<text x="' + (i * (bw + gap) + bw / 2) + '" y="' + (H - 1) +
      '" text-anchor="middle" font-family="monospace" font-size="8" fill="rgba(255,255,255,.32)">' +
      MON[+D.mon[i][0].slice(5,7) - 1] + '</text>';
    return '<rect x="' + (i * (bw + gap)) + '" y="' + (v >= 0 ? zero - h : zero) + '" width="' + bw +
           '" height="' + h + '" rx="3" fill="rgba(255,255,255,' + (v >= 0 ? .45 : .22) + ')"/>' + lab;
  }).join("") +
  '<line x1="0" y1="' + zero + '" x2="' + W + '" y2="' + zero + '" stroke="rgba(255,255,255,.09)" stroke-width="1"/>';
}

const monthTitle = () => MONF[+D.curYm.slice(5, 7) - 1] + " " + D.curYm.slice(0, 4);
