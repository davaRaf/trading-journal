/* Звірка ТС із журналом. Запуск: node test_against.js

   Звірка рахувала по всьому, що лежить у журналі: скіпи, угоди «в роботі»,
   угоди без RR. Через це цифри в кожному рядку були чужі — людина бачила
   «усі 41 угода не в моїй сесії», хоча торгувала рівно в своє вікно
   (22.09.2026). Перевіряємо не «порахувало», а «порахувало по тому, по
   чому й має»: без скіпів, без відкритих, з базою з тих угод, де потрібне
   поле взагалі заповнене. */
const fs = require("fs");
const src = fs.readFileSync("static/ts.js", "utf8");

function block(from){
  const b = src.indexOf("{", from);
  let d = 0;
  for (let j = b; j < src.length; j++){
    if (src[j] === "{") d++;
    else if (src[j] === "}"){ d--; if (d === 0) return src.slice(b, j + 1); }
  }
  throw new Error("не закрився блок");
}
function grab(name){
  const i = src.indexOf("function " + name + "(");
  if (i < 0) throw new Error("не знайшов " + name);
  return "function " + name + src.slice(src.indexOf("(", i), src.indexOf("{", i)) + block(i);
}

/* словник беремо з самого файлу, щоб підписи були справжні */
const DICT = eval("(" + block(src.indexOf("const DICT")) + ")");
const esc = s => String(s == null ? "" : s);
const r1 = v => Math.round(v * 10) / 10;
const fmtR = v => (v > 0 ? "+" : "") + r1(v) + "%";
const isWin = t => ["Win", "WinM", "BE-"].indexOf(t.result) >= 0;
const isSkip = t => t.result === "Skip";
const isOpen = t => t.result === "Open";
const netR = t => {
  const risk = (t.risk != null && !isNaN(t.risk)) ? t.risk : 1;
  if (isWin(t)) return risk * (t.rr != null ? t.rr : 0);
  if (t.result === "Loss") return -risk;
  return 0;
};
const T = {btTsNote: ""};
global.window = {LANG: "ru"};
let TS = {}, S = {trades: []};
const D = () => DICT.ru;

eval(grab("dayMap"));
eval(grab("nWord"));
eval(grab("realList"));
eval(grab("against"));

let bad = 0;
function check(name, cond){
  console.log("  " + (cond ? "ok  " : "ПАДАЄ") + "  " + name);
  if (!cond) bad++;
}
const plain = h => h.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const row = (h, word) => plain(h.split('<div class="r">').find(x => x.indexOf(word) >= 0) || "рядка немає");
const day = (n, hhmm) => "2026-09-" + String(n).padStart(2, "0") + "T" + hhmm;

/* ---- скіпи й «в роботі» — не угоди -------------------------------------- */
TS = {maxtrades: "3", risk: {per: "1"}, windows: [{name: "Лондон", time: "09:00 – 12:00"}]};
S = {trades: [
  {date: day(1, "10:00"), result: "Win", risk: 1, session: "Лондон"},
  {date: day(1, "11:00"), result: "Loss", risk: 1, session: "Лондон"},
  {date: day(1, "15:00"), result: "Skip", risk: 5, session: "Нью-Йорк"},
  {date: day(1, "16:00"), result: "Skip", risk: 5, session: "Нью-Йорк"},
  {date: day(1, "17:00"), result: "Skip", risk: 5, session: "Нью-Йорк"},
  {date: day(1, "18:00"), result: "Skip", risk: 5, session: "Нью-Йорк"},
  {date: day(1, "19:00"), result: "Open", risk: 5, session: "Нью-Йорк"},
  {date: day(2, "10:30"), result: "Win", risk: 1, session: "Лондон"},
  {date: day(3, "10:30"), result: "Win", risk: 1, session: "Лондон"},
  {date: day(4, "10:30"), result: "Loss", risk: 1, session: "Лондон"},
]};
let h = against();
check("пʼять скіпів за день не ламають ліміт угод", row(h, "день").indexOf("0 дней") >= 0);
check("«більше за все» рахує лише справжні", row(h, "день").indexOf("больше всего 2") >= 0);
check("скіп поза вікном — не порушення вікна", row(h, "окн").indexOf("держишь") >= 0);
check("ризик скіпа не йде в перевищення", row(h, "иск").indexOf("держишь") >= 0);

/* ---- RR: база — ті угоди, де RR записаний ------------------------------- */
TS = {risk: {rr: "1.5"}};
const many = [];
for (let i = 0; i < 12; i++) many.push({date: day(i % 9 + 1, "10:00"), result: "Win", rr: 1.0});
for (let i = 0; i < 8; i++) many.push({date: day(i % 9 + 1, "11:00"), result: "Win", rr: 2.0});
for (let i = 0; i < 80; i++) many.push({date: day(i % 9 + 1, "12:00"), result: "Win", rr: null});
S = {trades: many};
h = against();
check("RR рахуємо з тих, де він є, а не з усіх угод",
      row(h, "RR").indexOf("8 / 20") >= 0);
check("і кажемо, скільки нижче мінімуму", row(h, "RR").indexOf("ниже минимума: 12") >= 0);
check("частки «від усіх» більше немає", row(h, "RR").indexOf("% всех") < 0);

S = {trades: [{rr: 2}, {rr: 3}, {rr: 1.5}, {rr: 4}, {rr: 2.2}, {rr: null}]};
check("рівно мінімум — не порушення", row(against(), "RR").indexOf("5 / 5") >= 0);
S = {trades: [{rr: null}, {rr: null}, {rr: null}, {rr: null}, {rr: null}, {rr: null}]};
check("жодного RR — рядка немає", against().indexOf("не ниже минимального") < 0);

/* ---- модель входу може бути записана як сетап --------------------------- */
TS = {models: [{name: "BOS"}], setups: [{name: "FVG континуация"}], risk: {}};
S = {trades: [
  {date: day(1, "10:00"), result: "Win", entry_model: "BOS"},
  {date: day(2, "10:00"), result: "Win", entry_model: "FVG континуация"},
  {date: day(3, "10:00"), result: "Loss", entry_model: "bos"},
  {date: day(4, "10:00"), result: "Win", entry_model: "FVG КОНТИНУАЦИЯ"},
  {date: day(5, "10:00"), result: "Loss", entry_model: "навмання"},
]};
h = against();
check("сетап вважається своїм, а не чужим", row(h, "одел").indexOf("4 / 5") >= 0);
check("чужа модель усе одно видно", row(h, "одел").indexOf("навмання 1") >= 0);

/* ---- вікна: назва сесії іншою мовою ------------------------------------- */
TS = {windows: [{name: "London", time: "09:00 – 12:00"}], risk: {}};
S = {trades: [
  {date: day(1, "10:00"), result: "Win", session: "Лондон"},
  {date: day(2, "10:30"), result: "Win", session: "Лондон"},
  {date: day(3, "11:00"), result: "Loss", session: "Лондон"},
  {date: day(4, "11:30"), result: "Win", session: "Лондон"},
  {date: day(5, "10:15"), result: "Win", session: "Лондон"},
]};
check("«London» у ТС і «Лондон» у журналі — те саме вікно",
      row(against(), "окн").indexOf("5 / 5") >= 0);

TS = {windows: [{name: "New York", time: "15:30 – 18:00"}], risk: {}};
S = {trades: [
  {date: day(1, "16:00"), result: "Win", session: "Нью-Йорк"},
  {date: day(2, "16:30"), result: "Win", session: "НЬЮ-ЙОРК"},
  {date: day(3, "17:00"), result: "Loss", session: "ny"},
  {date: day(4, "17:30"), result: "Win", session: "Нью Йорк"},
  {date: day(5, "16:15"), result: "Win", session: "Нью-Йорк"},
]};
check("«New York», «Нью-Йорк», «ny» — теж одне вікно",
      row(against(), "окн").indexOf("5 / 5") >= 0);

/* сесію часто пишуть скороченням */
TS = {windows: [{name: "NY", time: ""}, {name: "LO", time: ""}], risk: {}};
S = {trades: [
  {date: "2026-09-01", result: "Win", session: "Нью-Йорк"},
  {date: "2026-09-02", result: "Win", session: "Лондон"},
  {date: "2026-09-03", result: "Loss", session: "ny"},
  {date: "2026-09-04", result: "Win", session: "LO"},
  {date: "2026-09-05", result: "Win", session: "ЛОН"},
]};
check("вікна «NY» і «LO» впізнають і повні назви, і скорочення",
      row(against(), "окн").indexOf("5 / 5") >= 0);

TS = {windows: [{name: "London", time: ""}, {name: "New York", time: ""}], risk: {}};
S = {trades: [
  {date: "2026-09-01", result: "Win", session: "LO"},
  {date: "2026-09-02", result: "Win", session: "NY"},
  {date: "2026-09-03", result: "Loss", session: "НЙ"},
  {date: "2026-09-04", result: "Win", session: "лон"},
  {date: "2026-09-05", result: "Win", session: "Нью-Йорк"},
]};
check("і навпаки: у ТС повні назви, у журналі скорочення",
      row(against(), "окн").indexOf("5 / 5") >= 0);

/* скорочення звіряємо рівно: слово, що просто починається на «lo», — не Лондон */
TS = {windows: [{name: "London", time: ""}], risk: {}};
S = {trades: [
  {date: "2026-09-01", result: "Win", session: "Лондон"},
  {date: "2026-09-02", result: "Win", session: "Лондон"},
  {date: "2026-09-03", result: "Loss", session: "Local range"},
  {date: "2026-09-04", result: "Win", session: "Лондон"},
  {date: "2026-09-05", result: "Win", session: "Лондон"},
]};
h = against();
check("слово на «lo» не стає Лондоном", row(h, "окн").indexOf("5 / 5") < 0);
check("незнайому назву не записуємо в порушення — просто не судимо її",
      row(h, "окн").indexOf("4 / 4") >= 0);

/* ---- «00:00» — не вхід опівночі, а угода без часу ----------------------- */
TS = {windows: [{name: "London", time: "09:00 – 12:00"}], risk: {}};
S = {trades: [
  {date: "2026-05-21T00:00", result: "Win", session: "LONDON"},
  {date: "2026-05-18T00:00", result: "Loss", session: "LONDON"},
  {date: "2026-05-15T00:00", result: "Win", session: "LONDON"},
  {date: "2026-09-21T11:11", result: "Win", session: "LONDON"},
  {date: "2026-09-16T10:30", result: "Win", session: "LONDON"},
]};
check("угоди без часу, але зі своєю сесією — у вікні, всі пʼять",
      row(against(), "окн").indexOf("5 / 5") >= 0);

/* вікно назване по-своєму: звіряти нема з чим, судимо лише ті, де є час */
TS = {windows: [{name: "09:00 - 12:00 killzone", time: "09:00 – 12:00"}], risk: {}};
S = {trades: [
  {date: "2026-05-21T00:00", result: "Win", session: "LONDON"},
  {date: "2026-05-18T00:00", result: "Loss", session: "LONDON"},
  {date: "2026-05-15T00:00", result: "Win", session: "LONDON"},
  {date: "2026-09-21T11:11", result: "Win", session: "LONDON"},
  {date: "2026-09-16T10:30", result: "Win", session: "LONDON"},
]};
h = against();
check("з незнайомим вікном судимо лише дві угоди, де записано час",
      row(h, "окн").indexOf("2 / 2") >= 0);
check("і опівнічні в порушення не йдуть", row(h, "окн").indexOf("вне окон") < 0);

/* справжній вхід о 00:00 у нічне вікно — за назвою все одно зарахуємо */
TS = {windows: [{name: "Asia", time: "00:00 – 09:00"}], risk: {}};
S = {trades: [
  {date: "2026-05-21T00:00", result: "Win", session: "Азия"},
  {date: "2026-05-18T00:00", result: "Loss", session: "Азия"},
  {date: "2026-05-15T00:00", result: "Win", session: "Азия"},
  {date: "2026-05-14T02:00", result: "Win", session: "Азия"},
  {date: "2026-05-13T03:00", result: "Win", session: "Азия"},
]};
check("нічна сесія не постраждала: назва збіглась — усі пʼять у вікні",
      row(against(), "окн").indexOf("5 / 5") >= 0);

/* вхід справді поза вікном лишається порушенням */
TS = {windows: [{name: "London", time: "09:00 – 12:00"}], risk: {}};
S = {trades: [
  {date: day(1, "10:00"), result: "Win", session: "Лондон"},
  {date: day(2, "10:30"), result: "Win", session: "Лондон"},
  {date: day(3, "16:00"), result: "Loss", session: "Нью-Йорк"},
  {date: day(4, "17:00"), result: "Win", session: "Нью-Йорк"},
  {date: day(5, "10:15"), result: "Win", session: "Лондон"},
]};
check("вхід поза вікном за часом — порушення",
      row(against(), "окн").indexOf("3 / 5") >= 0);

/* часу немає — віримо назві */
TS = {windows: [{name: "Лондон", time: ""}], risk: {}};
S = {trades: [
  {date: "2026-09-01", result: "Win", session: "Лондон"},
  {date: "2026-09-02", result: "Win", session: "Лондон"},
  {date: "2026-09-03", result: "Loss", session: "Азія"},
  {date: "2026-09-04", result: "Win", session: "Лондон"},
  {date: "2026-09-05", result: "Win", session: "Лондон"},
]};
check("без часу звіряємо за назвою", row(against(), "окн").indexOf("4 / 5") >= 0);

/* ---- денний ліміт ловиться, як і ловився -------------------------------- */
TS = {risk: {day: "2%"}};
S = {trades: [
  {date: day(1, "10:00"), result: "Loss", risk: 1.5},
  {date: day(1, "11:00"), result: "Loss", risk: 1.5},
  {date: day(2, "10:00"), result: "Win", risk: 1, rr: 2},
  {date: day(3, "10:00"), result: "Win", risk: 1, rr: 2},
  {date: day(4, "10:00"), result: "Loss", risk: 1},
]};
check("день із втратою 3% при ліміті 2% спіймано",
      row(against(), "лимит").indexOf("1 день") >= 0);

/* ---- замало справжніх угод — звірка мовчить ----------------------------- */
TS = {risk: {rr: "2"}};
S = {trades: [
  {date: day(1, "10:00"), result: "Win", rr: 3},
  {date: day(2, "10:00"), result: "Skip"}, {date: day(3, "10:00"), result: "Skip"},
  {date: day(4, "10:00"), result: "Skip"}, {date: day(5, "10:00"), result: "Skip"},
  {date: day(6, "10:00"), result: "Open"},
]};
check("одна справжня угода з шести — звірки немає",
      against().indexOf("Мало сделок") >= 0);

console.log(bad ? "\nзламано: " + bad : "\nусе сходиться");
process.exit(bad ? 1 : 0);
