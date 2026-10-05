/* Чи дістається «Підписка» з телефону. Запуск: node _mobsub_test.js

   Скарга 01.10.2026: на телефоні розділу підписки «немає». Насправді він
   був, але плашка профілю в шторці відкривала одразу профіль, і список
   розділів лишався за стрілкою «назад». Перевіряємо саму розмітку, яку
   вікно віддає в openModal. */
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync("static/settings.js", "utf8");

const T = {stTitle:"Налаштування", stProfile:"Профіль", stProfileSub:"нік і фото",
  stGeneral:"Загальні", stLang:"Мова", subTitle:"Підписка", ppTitle:"Відкритий журнал",
  bkTitle:"Копія", mrClose:"Закрити", pwBack:"Назад", meFree:"Зараз безкоштовно",
  stTodo:"є що зробити"};

function run(phone, where){
  let shown = null;
  const el = () => ({onclick:null, setAttribute(){}, focus(){}, classList:{toggle(){}},
    insertBefore(){}, remove(){}, parentNode:null, firstChild:null});
  const ctx = {
    T,
    matchMedia: q => ({matches: phone && /max-width:\s*560px/.test(q), addEventListener(){}}),
    document: {addEventListener(){}, querySelector: () => null, getElementById: () => null},
    openModal: h => { shown = h; },
    closeModal(){},
    setTimeout,
    console,
  };
  ctx.window = ctx;
  ctx.__me = {load: async () => {}, user: () => ({nickname:"mobtest1"}), pane: () => "<p>профіль</p>",
    wire(){}, avatar: () => "<i class='av'></i>"};
  ctx.__sub = {load: async () => {}, section: () => "<div class='sub-plans'>тарифи</div>",
    wire(){}, state: () => ({active:false, plan:"free"})};
  vm.createContext(ctx);
  vm.runInContext(src, ctx, {filename: "settings.js"});
  return ctx.__settings.open(where).then(() => shown || "");
}

let bad = 0;
const ok2 = (c, msg) => { console.log((c ? "ok   " : "ПРОВАЛ ") + msg); if (!c) bad++; };
const ok = (c, msg) => { console.log((c ? "ok   " : "ПРОВАЛ ") + msg); if (!c) bad++; };

(async () => {
  const ph = await run(true, "profile");
  ok(/stx-list/.test(ph), "телефон, плашка профілю → список розділів");
  ok(ph.includes(T.subTitle), "телефон, у списку є «Підписка»");
  ok(!/stx-back/.test(ph), "телефон, це не окремий екран профілю зі стрілкою");

  const sub = await run(true, "subscription");
  ok(/stx-back/.test(sub) && !/stx-list/.test(sub), "телефон, платна стіна → одразу розділ підписки");
  ok(sub.includes("sub-plans"), "телефон, у розділі справді тарифи");

  const pc = await run(false, "profile");
  ok(/stx-nav/.test(pc) && pc.includes(T.subTitle), "комп'ютер: меню розділів із «Підпискою» на місці");
  ok(pc.includes("профіль"), "комп'ютер: справа одразу профіль, як було");

})();
process.on("exit", () => process.exitCode = bad ? 1 : 0);

/* ---- значок налаштувань біля плашки профілю (скарга 01.10.2026) ----
   З телефона не було видно, як зайти в налаштування: у шторці стояла лише
   плашка з ніком, а на налаштування вона не схожа. Перевіряємо, що значок
   є в розмітці, веде в список розділів, видний саме у шторці телефона й
   має підпис усіма трьома мовами. */
const html = fs.readFileSync("static/index.html", "utf8");
const css = fs.readFileSync("static/style.css", "utf8");
const mcss = fs.readFileSync("static/mobile.css", "utf8");
const i18n = fs.readFileSync("static/i18n.js", "utf8");

const me = html.slice(html.indexOf('<div class="side-me"'), html.indexOf('</header>'));
const gear = (me.match(/<button class="side-me-st"[^>]*>/) || [])[0] || "";

ok2(!!gear, "значок налаштувань стоїть у плашці профілю");
ok2(me.indexOf('side-me-who') < me.indexOf('side-me-st'), "значок праворуч від ніка, а не перед ним");
ok2(/onclick="__settings\.open\(\)"/.test(gear), "значок веде в список розділів, а не в профіль");
ok2(/aria-label=/.test(gear), "у значка є підпис для читача екрана");
ok2(/\.side-me-st\{display:none\}/.test(css), "на комп'ютері значка немає");
ok2(/\.mmenu-wrap \.mmenu \.side-me-st\{[^}]*display:grid/.test(mcss), "у шторці телефона значок видно");
ok2(/getElementById\("sideMeGear"\)/.test(i18n), "підпис значка перекладається разом з мовою");

/* stTip/stTitle — підписи значка; без них у когось буде «undefined» */
const dicts = i18n.slice(i18n.indexOf("const I18N = {"));
for (const lang of ["uk", "ru", "en"]){
  const i = dicts.indexOf("\n" + lang + ": {");
  const part = dicts.slice(i, dicts.indexOf("\n},", i));
  ok2(/\bstTip:/.test(part) && /\bstTitle:/.test(part), "є підписи налаштувань у словнику " + lang);
}
