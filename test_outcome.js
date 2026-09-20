/* Скип и тейк рукой в подсчётах. Запуск: node test_outcome.js
   Проверяем ровно то, что легко сломать: скип не должен попадать никуда,
   где делят на количество сделок, а тейк рукой обязан считаться победой. */
const fs = require("fs");

/* берём из app.js только счётную часть — она не трогает DOM */
const src = fs.readFileSync("static/app.js", "utf8");
const from = src.indexOf("const RES_LABEL=");
const to = src.indexOf("function sortAsc(");
const code = src.slice(from, to);
const T = {resHand:"TP рукой", resSkip:"скип"};
const r1 = v => Math.round(v*10)/10;
eval(code);

let bad = 0;
function check(name, cond){
  console.log("  " + (cond ? "ok  " : "ПАДАЕТ") + "  " + name);
  if(!cond) bad++;
}

const trades = [
  {result:"Win",  rr:2,   risk:1},              // +2
  {result:"WinM", rr:1,   risk:1, rr_plan:3},   // +1, недобрал 2
  {result:"Loss", rr:2,   risk:1},              // -1
  {result:"Skip"},                              // ничего
  {result:"Skip"}
];
const st = calc(trades);

check("скипы не в счётчике сделок", st.n === 3);
check("скипы посчитаны отдельно", st.skips === 2);
check("тейк рукой — победа", st.wins === 2);
check("win rate без скипов", Math.round(st.wr) === 67);
check("итог не изменился от скипов", r1(st.net) === 2);
check("выходов рукой", st.hands === 1);
check("недобрал по факту", r1(st.handOut) === 2);
check("скип в деньгах ноль", netR({result:"Skip", risk:5, rr:3}) === 0);
check("тейк рукой считается как тейк", netR({result:"WinM", rr:2, risk:1.5}) === 3);
check("без плана недобора нет", handLost({result:"WinM", rr:2, risk:1}) === 0);
check("план ниже факта — не минус", handLost({result:"WinM", rr:3, risk:1, rr_plan:2}) === 0);

const only = calc([{result:"Skip"},{result:"Skip"}]);
check("день из одних скипов не делит на ноль", only.n === 0 && only.wr === null && only.skips === 2);

check("плашка тейка рукой отличается", resCls("WinM") === "win hand");
check("плашка скипа своя", resCls("Skip") === "skip");
check("скип узнаётся", isSkip({result:"Skip"}) && !isSkip({result:"Win"}));

console.log(bad ? "\nсломано: " + bad : "\nвсё сходится");
process.exit(bad ? 1 : 0);
