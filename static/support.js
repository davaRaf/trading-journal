/* ============================================================
   Вікно «Підтримка»: як з нами зв'язатись.

   Окрема кнопка в бічній панелі, над налаштуваннями: писати нам
   ходять не тоді, коли міняють мову, і ховати контакти всередині
   іншого вікна — зайвий клік у момент, коли щось не працює.
   Усередині — пошта й два Телеграми: клік по них одразу відкриває чат.

   Свого стану вікно не тримає: усі контакти лежать у CONTACTS нижче,
   тому додати чи прибрати рядок можна тільки там, не чіпаючи розмітку.
   ============================================================ */
(function(){

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* value — те, що людина бачить у рядку (пошта, нік у Телеграмі).
   link — куди веде кнопка «Написати»: t.me/<нік> відкриває саме чат із
   полем вводу, і в застосунку, і в браузері.

   Discord тут був і поїхав: посилання на профіль (discord.com/users/<id>)
   застосунок відкриває головним екраном «Друзі», а не листуванням —
   личка з незнайомцем у Discord взагалі не має адреси, канал з'являється
   лише після першого контакту. Телеграм таких обмежень не має.

   Немає link — кнопка копіює нік замість переходу.
   Порожнє value — рядок просто не малюється. */
const CONTACTS = [
  /* Кнопка веде не в mailto:, а у веб-Gmail, одразу у вікно нового
     листа з підставленим адресатом (view=cm — compose, fs=1 —
     повноекранне вікно). Причина: mailto: відкриває поштову програму,
     призначену в системі, а в Windows її часто просто немає — клік не
     робив нічого. Веб-Gmail відкривається в будь-якому браузері, а
     кому зручніше своя програма — тому лишається сама адреса
     посиланням mailto: під назвою рядка. */
  {kind: "mail",     key: "suEmail",     value: "statsai.journal@gmail.com",
   link: "https://mail.google.com/mail/?view=cm&fs=1&to=statsai.journal@gmail.com"},
  {kind: "telegram", key: "suTelegram",  value: "@danylo_mf",
   link: "https://t.me/danylo_mf"},
  {kind: "telegram", key: "suTelegram2", value: "@david_rafaelian",
   link: "https://t.me/david_rafaelian"},

  /* Соцмережі йдуть окремою групою: це не підтримка, а «де нас читати».
     sep — підпис-роздільник перед рядком, cta — своя назва кнопки
     (у мережу не «пишуть», її відкривають). */
  {kind: "instagram", key: "socIg", value: "@statsai_trading_journal",
   link: "https://www.instagram.com/statsai_trading_journal",
   sep: "suSocial", cta: "suOpen", nm: "Instagram"},
  {kind: "tiktok", key: "socTt", value: "@statsai_trading_journal",
   link: "https://www.tiktok.com/@statsai_trading_journal",
   cta: "suOpen", nm: "TikTok"},
];

const IC = {
  mail: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.7"/><path d="M4 8l7.1 5a1.6 1.6 0 001.8 0L20 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  /* Той самий літачок, що й у «Підключеннях» бічної панелі — щоб
     Телеграм у двох місцях виглядав однаково. */
  telegram: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M21 4L3 11l6 2.2L19 6.5l-7.5 8.3.4 5.2 2.6-3.6 4.2 3.1L21 4z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  instagram: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.7"/><circle cx="17.2" cy="6.8" r="1.1" fill="currentColor"/></svg>',
  tiktok: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M14 3v11.2a3.3 3.3 0 11-2.6-3.22" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 3.4c.5 2.4 2.3 4 4.7 4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
};

const isUrl = v => /^https?:\/\//i.test(String(v || ""));

function row(c){
  /* t.me відкриваємо новою вкладкою: Телеграм перехопить посилання й
     покаже свій застосунок одразу на чаті.

     Пошта веде у веб-Gmail (див. CONTACTS вище), а сама адреса під
     назвою лишається посиланням mailto: — для тих, у кого поштова
     програма таки призначена. Рядок без посилання взагалі — кнопка
     «Скопіювати». */
  const act = isUrl(c.link)
    ? '<a class="btn su-act" href="' + esc(c.link) + '" target="_blank" rel="noopener">' + esc(T[c.cta] || T.suWrite) + "</a>"
    : '<button type="button" class="btn su-act" data-su-copy="' + esc(c.value) + '">' + esc(T.suCopy) + "</button>";
  const val = c.kind === "mail"
    ? '<a class="su-val" href="mailto:' + esc(c.value) + '">' + esc(c.value) + "</a>"
    : '<i class="su-val">' + esc(c.value) + "</i>";
  /* Назва рядка: у контактів вона перекладається, у соцмереж це власна
     назва сервісу — беремо nm як є. */
  const nm = c.nm || T[c.key] || c.key;
  const sep = c.sep ? '<div class="su-sep">' + esc(T[c.sep] || c.sep) + "</div>" : "";
  return sep + '<div class="su-row su-' + esc(c.kind) + '">'
    + '<span class="su-ic">' + IC[c.kind] + "</span>"
    + '<span class="su-text"><b class="su-nm">' + esc(nm) + "</b>"
    + val + "</span>"
    + act + "</div>";
}

function body(){
  const rows = CONTACTS.filter(c => c.value).map(row).join("");
  return '<div class="m-body su">'
    + '<p class="pp-lead">' + esc(T.suLead) + "</p>"
    + '<div class="su-list">' + rows + "</div></div>";
}

/* Кнопки «Скопіювати» вішаємо після відмальовки: розмітка щоразу нова,
   старі обробники разом з нею зникають. */
function wire(){
  document.querySelectorAll("[data-su-copy]").forEach(b => {
    b.onclick = async () => {
      const v = b.getAttribute("data-su-copy");
      try{ await navigator.clipboard.writeText(v); }
      catch(e){
        const t = document.createElement("textarea");
        t.value = v; document.body.appendChild(t); t.select();
        document.execCommand("copy"); t.remove();
      }
      b.textContent = T.suCopied;
    };
  });
}

function open(){
  openModal(
    '<div class="m-head"><h2>' + esc(T.suTitle) + "</h2>"
    + '<button class="x" onclick="closeModal()" aria-label="' + esc(T.mrClose) + '">×</button></div>'
    + body()
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn" onclick="closeModal()">' + esc(T.mrClose) + "</button></div>");
  wire();
}

window.__support = {open: open};

})();
