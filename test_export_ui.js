/* Розділ «Копія журналу»: що саме пропонують забрати.

   Доти кнопка була одна й віддавала весь журнал одним JSON — разом із
   бектестом. Людина, яка прогнала стратегію на історії, не могла взяти
   самий прогін: ні окремо, ні таблицею.

   Перевіряємо дві речі, які найлегше зламати непомітно:
     * адресу вивантаження — порожній `run` мусить лишитись у ній, бо це
       «Без журналу», а не «без звуження»;
     * сам розділ — у бектесті поруч стоїть блок прогону, у реальній
       торгівлі його немає.

   Запуск: node test_export_ui.js */
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync("static/backup.js", "utf8");

let bad = 0;
function check(name, ok, got){
  if (!ok) bad++;
  console.log((ok ? "  ok  " : "ПОМИЛКА") + "  " + name +
              (ok || got === undefined ? "" : "  → " + got));
}

/* Беремо з файла самі функції, які перевіряємо: модуль — IIFE, і цілком
   він тут не підніметься, бо чекає на вікно й налаштування. */
function grab(names){
  const out = [];
  for (const n of names){
    const at = src.indexOf("function " + n + "(");
    if (at < 0) throw new Error("не знайшли function " + n);
    let i = src.indexOf("{", at), deep = 0;
    for (; i < src.length; i++){
      if (src[i] === "{") deep++;
      else if (src[i] === "}" && --deep === 0){ i++; break; }
    }
    out.push(src.slice(at, i));
  }
  return out.join("\n\n");
}

const T = {bkLead: "лід", bkGet: "Скачать журнал", bkCsv: "Таблицей (CSV)",
  bkBtTitle: "Бэктест отдельно", bkBtLead: "лід бектесту",
  bkBtOpen: "Открытый журнал:", bkBtBlank: "Без журнала",
  bkBtRun: "Этот прогон", bkBtAll: "Весь бэктест"};

const box = {T: T, btOn: () => false,
  esc: (s) => String(s == null ? "" : s)
          .replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])),
  note: () => "<!--note-->"};
/* У браузері `window.__btj` і просто `__btj` — одне й те саме.
   У пісочниці це довелось би розводити, тому вікном робимо сам контекст. */
box.window = box;
box.global = box;
box.__btj = null;
vm.createContext(box);
vm.runInContext(grab(["url", "get", "onBt", "btPart", "inner"]), box);

/* ---- адреса ---- */
const url = box.url;
check("без параметрів — те саме вивантаження, що було",
      url("") === "/api/export", url(""));
check("таблиця просить формат", url("csv") === "/api/export?fmt=csv", url("csv"));
check("бектест цілком", url("", "bt") === "/api/export?kind=bt", url("", "bt"));
/* Назва прогону — те, що людина написала руками: там бувають і пробіли,
   і знак питання, і амперсанд. У адресі все це має бути закодоване. */
check("назва прогону кодується",
      url("csv", "bt", "US100 & Co?") ===
      "/api/export?fmt=csv&kind=bt&run=US100%20%26%20Co%3F",
      url("csv", "bt", "US100 & Co?"));
/* «Без журналу» — окремий прогін, а не «усі»: параметр лишається, хоч і
   порожній. Якби його прибрали, кнопка віддавала б увесь бектест. */
check("порожня назва лишається в адресі",
      url("", "bt", "") === "/api/export?kind=bt&run=", url("", "bt", ""));

/* ---- розділ ---- */
let html = box.inner();
check("у реальній торгівлі два формати поруч",
      html.indexOf('href="/api/export"') >= 0 &&
      html.indexOf('href="/api/export?fmt=csv"') >= 0);
check("і жодного слова про бектест", html.indexOf(T.bkBtTitle) < 0);

box.btOn = () => true;
box.__btj = {shown: () => ({name: "US100 березень", blank: false})};
html = box.inner();
check("у бектесті з'являється блок прогону", html.indexOf(T.bkBtTitle) >= 0);
check("видно, який журнал відкритий", html.indexOf("US100 березень") >= 0);
check("прогін забирається і файлом, і таблицею",
      html.indexOf("kind=bt&run=US100%20%D0%B1%D0%B5%D1%80%D0%B5%D0%B7%D0%B5%D0%BD%D1%8C") >= 0 &&
      html.indexOf("fmt=csv&kind=bt&run=US100%20%D0%B1%D0%B5%D1%80%D0%B5%D0%B7%D0%B5%D0%BD%D1%8C") >= 0);
check("а поруч — увесь бектест",
      html.indexOf('href="/api/export?kind=bt"') >= 0 &&
      html.indexOf('href="/api/export?fmt=csv&kind=bt"') >= 0);
check("весь журнал нікуди не подівся",
      html.indexOf('href="/api/export"') >= 0);

/* Журнал без назви: угоди без підпису збираються в «Без журналу», і він
   теж мусить забиратись окремо. */
box.__btj = {shown: () => ({name: "", blank: true})};
html = box.inner();
check("«Без журналу» названий словом, а не порожнечею",
      html.indexOf(T.bkBtBlank) >= 0);
check("і забирається окремим вивантаженням",
      html.indexOf('href="/api/export?kind=bt&run="') >= 0);

/* Жодного журналу не відкрито — блок лишається, але без кнопок прогону. */
box.__btj = {shown: () => null};
html = box.inner();
check("без відкритого журналу лишається тільки весь бектест",
      html.indexOf(T.bkBtTitle) >= 0 && html.indexOf(T.bkBtRun) < 0);

console.log(bad ? "\nЄ ПОМИЛКИ: " + bad : "\nВСЕ ДОБРЕ");
process.exit(bad ? 1 : 0);
