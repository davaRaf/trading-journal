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

  process.exit(bad ? 1 : 0);
})();
