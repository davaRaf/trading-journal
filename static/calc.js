/* ============================================================
   Калькулятор ризику й лотів.

   Рахує головне питання перед входом: скільки брати, щоб втратити
   рівно стільки, скільки дозволив собі втратити.

       лоти = (депозит × ризик%) / (дистанція до стопу × вартість пункту)

   Вартість пункту в різних брокерів різна, тому вона тут не зашита:
   підставляємо звичне значення, але його можна виправити — і ми
   запам'ятаємо його для цього інструмента.
   ============================================================ */
(function(){

const KEY = "statsai_calc";

/* крок — це «один пункт» для інструмента, ціна — скільки коштує рух
   на один пункт при обсязі 1 лот */
const PRESETS = [
  {id:"US100",  name:"US100",  step:1,      price:1,   note:"індекс, CFD"},
  {id:"GER40",  name:"GER40",  step:1,      price:1,   note:"індекс, CFD"},
  {id:"ES500",  name:"ES500",  step:1,      price:1,   note:"індекс, CFD"},
  {id:"XAUUSD", name:"XAUUSD", step:0.01,   price:1,   note:"1 лот = 100 унцій"},
  {id:"EURUSD", name:"EURUSD", step:0.0001, price:10,  note:"1 лот = 100 000"},
  {id:"GBPUSD", name:"GBPUSD", step:0.0001, price:10,  note:"1 лот = 100 000"},
  {id:"USDJPY", name:"USDJPY", step:0.01,   price:6.7, note:"залежить від курсу"},
  {id:"BTCUSD", name:"BTCUSD", step:1,      price:1,   note:"1 лот = 1 BTC"},
];

const DEF = {balance:10000, risk:1, pair:"US100", entry:"", stop:"", rr:2, lotStep:0.01};

function load(){
  try{ return Object.assign({}, DEF, JSON.parse(localStorage.getItem(KEY) || "{}")); }
  catch(e){ return Object.assign({}, DEF); }
}
function save(s){ try{ localStorage.setItem(KEY, JSON.stringify(s)); }catch(e){} }

let S2 = load();

function preset(id){
  return PRESETS.find(p => p.id === id) || {id:id, name:id, step:1, price:1, note:""};
}
/* виправлену вартість пункту тримаємо окремо на кожен інструмент */
function pointPrice(id){
  const own = (S2.prices || {})[id];
  return (own != null && own !== "") ? num(own) : preset(id).price;
}
function num(v){
  const n = parseFloat(String(v == null ? "" : v).replace(",", "."));
  return isFinite(n) ? n : null;
}
function r2(n){ return Math.round(n * 100) / 100; }

/* ---------- рахунок ---------- */
function compute(){
  const p = preset(S2.pair);
  const step = num(S2.step) || p.step;
  const bal = num(S2.balance), risk = num(S2.risk);
  const entry = num(S2.entry), stop = num(S2.stop);
  const vpp = pointPrice(S2.pair);
  const lotStep = num(S2.lotStep) || 0.01;

  const out = {step, vpp, lotStep, money:null, dist:null, lots:null,
               exact:null, real:null, tp:null, profit:null, side:""};
  if (bal != null && risk != null) out.money = bal * risk / 100;
  if (entry != null && stop != null && entry !== stop){
    out.dist = Math.abs(entry - stop) / step;
    out.side = entry > stop ? "Long" : "Short";
  }
  if (out.money != null && out.dist && vpp > 0){
    out.exact = out.money / (out.dist * vpp);
    out.lots = Math.floor(out.exact / lotStep) * lotStep;      // вниз, щоб не перебрати ризик
    out.lots = Math.round(out.lots * 1e6) / 1e6;
    out.real = out.lots * out.dist * vpp;
  }
  const rr = num(S2.rr);
  if (out.dist && rr && entry != null){
    const move = out.dist * step * rr;
    out.tp = out.side === "Long" ? entry + move : entry - move;
    if (out.real != null) out.profit = out.real * rr;
  }
  return out;
}

/* ---------- вікно ---------- */
function fmtMoney(v){
  if (v == null) return "—";
  return (v < 0 ? "−" : "") + Math.abs(v).toLocaleString("uk-UA",
    {minimumFractionDigits:2, maximumFractionDigits:2});
}
function fmtNum(v, d){
  if (v == null) return "—";
  return v.toLocaleString("uk-UA", {minimumFractionDigits:d, maximumFractionDigits:d});
}

function field(label, key, opts){
  opts = opts || {};
  return '<label class="ck-f"><span>' + esc(label) + "</span>"
    + '<input inputmode="decimal" autocomplete="off" data-k="' + key + '"'
    + ' value="' + esc(S2[key] == null ? "" : S2[key]) + '"'
    + (opts.ph ? ' placeholder="' + esc(opts.ph) + '"' : "")
    + ' oninput="__calc.set(\'' + key + '\', this.value)">'
    + (opts.suf ? '<i>' + esc(opts.suf) + "</i>" : "") + "</label>";
}

function draw(){
  const c = compute();
  const p = preset(S2.pair);
  const over = c.money != null && c.real != null && c.real > c.money + 1e-9;

  const pairs = PRESETS.map(x =>
    '<button class="ck-pair' + (x.id === S2.pair ? " on" : "") + '"'
    + ' onclick="__calc.pair(\'' + x.id + '\')">' + esc(x.name) + "</button>").join("");

  /* ціну пункту не дублюємо: вона нижче полем, яке можна виправити */
  const rows = [
    ["Сума ризику", fmtMoney(c.money)],
    ["Дистанція до стопу", c.dist == null ? "—" : fmtNum(c.dist, c.dist < 10 ? 1 : 0)
      + " пункт" + (c.dist >= 2 ? "ів" : "")],
  ];

  const h = '<div class="m-head"><h2>Калькулятор ризику</h2>'
    + '<button class="x" onclick="closeModal()">×</button></div>'
    + '<div class="m-body"><div class="ck">'

    + '<div class="ck-pairs">' + pairs
    +   '<button class="ck-pair' + (PRESETS.some(x => x.id === S2.pair) ? "" : " on")
    +   '" onclick="__calc.own()">своє…</button></div>'

    + '<div class="ck-grid">'
    +   field("Депозит", "balance", {suf:"$"})
    +   field("Ризик", "risk", {suf:"%"})
    +   field("Ціна входу", "entry", {ph:"напр. 23150"})
    +   field("Ціна стопу", "stop", {ph:"напр. 23110"})
    + "</div>"

    /* головна цифра */
    + '<div class="ck-out' + (c.lots ? "" : " off") + '">'
    +   '<div class="ck-lots"><b>' + (c.lots ? fmtNum(c.lots, 2) : "—") + "</b>"
    +     "<span>лотів</span></div>"
    +   '<div class="ck-side">' + (c.side ? '<i class="' + (c.side === "Long" ? "up" : "down")
    +     '">' + c.side + "</i>" : "")
    +     (c.exact ? '<small>точно ' + fmtNum(c.exact, 4) + ", округлили вниз</small>" : "")
    +   "</div></div>"

    + '<div class="ck-rows">' + rows.map(r =>
        '<div class="ck-r"><span>' + esc(r[0]) + "</span><b>" + esc(r[1]) + "</b></div>").join("")
    +   '<div class="ck-r"><span>Втратиш при стопі</span><b class="' + (over ? "warn" : "")
    +     '">' + fmtMoney(c.real) + "</b></div>"
    + "</div>"

    + '<div class="ck-tp">'
    +   '<div class="ck-grid ck-grid-2">'
    +     field("Плановий RR", "rr", {suf:"R"})
    +     '<label class="ck-f"><span>Ціна пункту</span>'
    +       '<input inputmode="decimal" autocomplete="off" value="' + esc(c.vpp) + '"'
    +       ' oninput="__calc.price(this.value)"><i>$</i></label>'
    +   "</div>"
    +   '<div class="ck-rows">'
    +     '<div class="ck-r"><span>Ціна тейку</span><b>'
    +       (c.tp == null ? "—" : fmtNum(c.tp, c.step < 1 ? 4 : 1)) + "</b></div>"
    +     '<div class="ck-r"><span>Заробиш при тейку</span><b class="up">'
    +       (c.profit == null ? "—" : "+" + fmtMoney(c.profit)) + "</b></div>"
    +   "</div>"
    + "</div>"

    + '<p class="nt-note">Ціна пункту в різних брокерів різна — перевір у свого '
    +   "й виправ, якщо не збігається. Для «" + esc(p.name) + "» "
    +   (p.note ? "звично: " + esc(p.note) + ". " : "")
    +   "Ми запам'ятаємо виправлене.</p>"
    + "</div></div>"
    + '<div class="m-foot"><button class="btn ghost" onclick="__calc.clear()">Очистити</button>'
    + '<span class="sp"></span>'
    + '<button class="btn primary" onclick="closeModal()">Готово</button></div>';

  openModal(h);
}

/* Перемальовуємо лише цифри: якщо перебирати все вікно на кожну літеру,
   курсор вилітає з поля. */
function refresh(){
  const box = document.getElementById("modalBox");
  if (!box || !box.querySelector(".ck")) return draw();
  const c = compute();
  const set = (sel, val) => { const n = box.querySelector(sel); if (n) n.textContent = val; };
  const over = c.money != null && c.real != null && c.real > c.money + 1e-9;

  set(".ck-lots b", c.lots ? fmtNum(c.lots, 2) : "—");
  box.querySelector(".ck-out").classList.toggle("off", !c.lots);
  const side = box.querySelector(".ck-side");
  if (side) side.innerHTML = (c.side ? '<i class="' + (c.side === "Long" ? "up" : "down") + '">'
      + c.side + "</i>" : "")
    + (c.exact ? '<small>точно ' + fmtNum(c.exact, 4) + ", округлили вниз</small>" : "");

  const rs = box.querySelectorAll(".ck > .ck-rows .ck-r b");
  if (rs.length >= 3){
    rs[0].textContent = fmtMoney(c.money);
    rs[1].textContent = c.dist == null ? "—" : fmtNum(c.dist, c.dist < 10 ? 1 : 0)
      + " пункт" + (c.dist >= 2 ? "ів" : "");
    rs[2].textContent = fmtMoney(c.real);
    rs[2].classList.toggle("warn", over);
  }
  const tp = box.querySelectorAll(".ck-tp .ck-r b");
  if (tp.length >= 2){
    tp[0].textContent = c.tp == null ? "—" : fmtNum(c.tp, c.step < 1 ? 4 : 1);
    tp[1].textContent = c.profit == null ? "—" : "+" + fmtMoney(c.profit);
  }
}

window.__calc = {
  open(){ S2 = load(); draw(); },
  set(k, v){ S2[k] = v; save(S2); refresh(); },
  pair(id){ S2.pair = id; S2.step = preset(id).step; save(S2); draw(); },
  own(){
    const v = prompt("Назва інструмента", S2.pair || "");
    if (!v) return;
    S2.pair = v.trim().toUpperCase();
    save(S2); draw();
  },
  price(v){
    S2.prices = S2.prices || {};
    S2.prices[S2.pair] = v;
    save(S2); refresh();
  },
  clear(){
    const keep = {balance:S2.balance, risk:S2.risk, pair:S2.pair,
                  prices:S2.prices, lotStep:S2.lotStep};
    S2 = Object.assign({}, DEF, keep, {entry:"", stop:""});
    save(S2); draw();
  },
};

})();
