/* ============================================================
   Профіль — перший розділ вікна «Налаштування» (static/settings.js).

   Фото, нік і цифри про звичку вести журнал: скільки з нами, угоди,
   торгові дні, серія днів підряд, розбори дня, карта активності за
   12 тижнів, улюблені інструменти й відмітки.

   Нік міняють прямо на місці: натиснув на нього або на олівець — він
   стає полем із ✓ і ✕. Фото перед збереженням людина сама кадрує в
   редакторі (зсув і масштаб), браузер шле квадрат 256×256; сервер —
   /api/me/avatar, /api/me/nick, /api/me/profile в app.py.
   ============================================================ */
(function(){

let data = null;          // {user, stats}
let editing = false;
let draft = "";
let checkTimer = null, checkSeq = 0;
let busy = false;
let allPresets = false;   // розгорнутий повний список готових аватарок

/* Готові аватарки — помічник StatsAI у різних настроях: static/avatars/<назва>.svg. Порядок — як у наборі:
   перші п'ять видно одразу, решта — за кнопкою «Усі аватарки».
   Сервер приймає тільки ці назви (AVATAR_PRESETS в app.py). */
const PRESETS = ["wink", "shades", "surprised", "focused", "laugh",
                 "sleepy", "love", "stars", "sly", "bull",
                 "bear", "headphones", "cap", "tongue", "robot"];
const PRESET_V = 1;
const PRESET_SHOWN = 5;

const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const $id = id => document.getElementById(id);
const NICK_RE = /^[A-Za-z0-9_.-]{3,24}$/;

const ICON = {
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  check:  '<path d="m5 12.5 4.5 4.5L19 7"/>',
  x:      '<path d="M6 6l12 12M18 6 6 18"/>',
  flag:   '<path d="M7 21V4M7 4h11l-2 4 2 4H7"/>',
  stack:  '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  flame:  '<path d="M12 3c1 4 5 5.5 5 10a5 5 0 0 1-10 0c0-2.5 1.5-3.5 2-5 1 1.5 2 2 2 2 .5-2 0-4.5 1-7z"/>',
  book:   '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5z"/><path d="M4 19.5A1.5 1.5 0 0 0 5.5 21H20v-3"/>',
};
const ic = n => '<svg class="me-ic" viewBox="0 0 24 24" aria-hidden="true">' + ICON[n] + "</svg>";

async function load(){
  try{ data = await api("GET", "/api/me/profile"); }
  catch(e){ data = null; }
  editing = false;
  calShift = 0;              // відкрили профіль — календар на поточному місяці
  return data;
}

function user(){ return data && data.user; }

/* Аватар: фото або перша буква ніка. Той самий і в меню, і в профілі. */
function avatar(size){
  const u = user();
  if (!u) return "";
  if (u.avatar)
    return '<img class="me-av" style="--s:' + size + 'px" src="' + esc(u.avatar) + '" alt="">';
  return '<span class="me-av" style="--s:' + size + 'px" aria-hidden="true">'
    + esc((u.nickname || "?").charAt(0).toUpperCase()) + "</span>";
}

function locale(){ return ({uk: "uk-UA", ru: "ru-RU", en: "en-GB"})[LANG] || "uk-UA"; }
function dayMonth(iso){
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00");
  return isNaN(d) ? "" : d.toLocaleDateString(locale(), {day: "numeric", month: "long"});
}

/* ------------------------------------------------------------ розмітка */

function nickBlock(){
  const u = user();
  if (!editing)
    return '<button type="button" class="me-nick" id="meNickEdit" aria-label="' + esc(T.meEditNick) + '">'
      + '<span>' + esc(u.nickname) + "</span>" + ic("pencil") + "</button>";
  return '<div class="me-nick-edit" data-own-esc>'
    +   '<div class="me-nick-f" id="meNickBox"><input id="meNickIn" value="' + esc(draft) + '" maxlength="24"'
    +     ' spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="' + esc(T.meNick) + '"></div>'
    +   '<button type="button" class="me-ib ok" id="meNickSave" aria-label="' + esc(T.meSave) + '">' + ic("check") + "</button>"
    +   '<button type="button" class="me-ib" id="meNickCancel" aria-label="' + esc(T.meCancel) + '">' + ic("x") + "</button>"
    + "</div>"
    + '<small class="me-nick-msg" id="meNickMsg" aria-live="polite" hidden></small>';
}

function tiles(s){
  const tile = (n, label, hot) => '<div class="me-tile' + (hot ? " hot" : "") + '"><b>' + esc(n) + "</b><span>" + esc(label) + "</span></div>";
  return '<div class="me-tiles">'
    + tile(s.with_us, T.meWithUs)
    + tile(s.trades, T.meTrades)
    + tile(s.days, T.meDays)
    + tile(s.streak, T.meStreak, s.streak > 0)
    + tile(s.reviews, T.meReviews)
    + "</div>";
}

/* Що саме було того дня — рядком для підказки: «15 вересня · угоди 3 ·
   розбір дня». Порожній день так і каже, що записів не було. */
function cellTip(iso, rec){
  const when = dayMonth(iso);
  const parts = [];
  if (rec && rec.t) parts.push(T.meHeatTrades + " " + rec.t);
  if (rec && rec.r) parts.push(T.meHeatReview);
  if (rec && rec.s) parts.push(T.meHeatShares + " " + rec.s);
  return when + " · " + (parts.length ? parts.join(" · ") : T.meHeatNone);
}

/* ---- календар активності ----
   Власник обрав звичайний календар місяця замість сітки квадратиків
   (16.09.2026): такий календар людина вже бачила в журналі, і пояснювати
   нічого не треба. Місяці гортаються стрілками — до першого запису. */

let calShift = 0;             // 0 — поточний місяць, -1 — попередній

const iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
  + "-" + String(d.getDate()).padStart(2, "0");

function calMonth(s){
  const t = new Date((s.today || "") + "T12:00:00");
  const base = isNaN(t) ? new Date() : t;
  return new Date(base.getFullYear(), base.getMonth() + calShift, 1);
}

function cal(s){
  const log = s.log || {};
  const today = s.today || iso(new Date());
  const first = new Date((s.log_from || today) + "T12:00:00");
  const m = calMonth(s);
  const year = m.getFullYear(), mon = m.getMonth();
  const wd = T.meCalWd || ["", "", "", "", "", "", ""];

  /* далі поточного місяця вперед і раніше першого запису назад — нікуди */
  const cur = new Date((s.today || "") + "T12:00:00");
  const canNext = calShift < 0;
  const canPrev = new Date(year, mon, 1) > new Date(first.getFullYear(), first.getMonth(), 1);

  const start = new Date(year, mon, 1);
  const lead = (start.getDay() + 6) % 7;        // тиждень із понеділка
  const cells = [];
  let done = 0, total = 0;
  for (let i = 0; i < 42; i++){
    const day = new Date(year, mon, 1 - lead + i);
    const key = iso(day);
    const own = day.getMonth() === mon;
    const rec = log[key];
    const ahead = key > today;
    if (own && !ahead) total++;
    if (own && rec) done++;
    const cls = ["c"];
    if (!own) cls.push("me-out");
    if (ahead) cls.push("me-fut");
    if (rec) cls.push(rec.n >= 3 ? "on hi" : "on");
    if (key === today) cls.push("me-now");
    cells.push('<span class="' + cls.join(" ") + '" title="' + esc(cellTip(key, rec)) + '">'
      + day.getDate() + "</span>");
    if (i >= 34 && (i + 1) % 7 === 0 && new Date(year, mon, 1 - lead + i + 1).getMonth() !== mon) break;
  }
  const name = (T.months || [])[mon] || "";
  const btn = (dir, on, label) => '<button type="button" class="me-cal-nav" data-cal="' + dir + '"'
    + (on ? "" : " disabled") + ' aria-label="' + esc(label) + '">'
    + '<svg class="me-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="'
    + (dir < 0 ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6") + '"/></svg></button>';

  return '<div class="me-cal">'
    + '<div class="me-cal-h"><b>' + esc(name + " " + year) + "</b>"
    +   '<span class="me-cal-navs">' + btn(-1, canPrev, T.meCalPrev) + btn(1, canNext, T.meCalNext) + "</span></div>"
    + '<div class="me-cal-grid">'
    +   wd.map(d => '<span class="wd">' + esc(d) + "</span>").join("")
    +   cells.join("")
    + "</div>"
    + '<p class="me-cal-sum">' + esc(String(T.meCalSum || "").replace("%1", done).replace("%2", total)) + "</p>"
    + "</div>";
}

function pairs(s){
  if (!s.pairs.length) return '<p class="me-empty">' + esc(T.meNoPairs) + "</p>";
  const top = s.pairs[0][1] || 1;
  return '<ul class="me-pairs">' + s.pairs.map(([n, c]) =>
    "<li><span>" + esc(n) + '</span><i style="--w:' + Math.max(4, Math.round(c / top * 100)) + '%"></i><em>' + c + "</em></li>").join("") + "</ul>";
}

function badges(s){
  const b = (on, icon, title, sub) => '<li class="me-bd' + (on ? "" : " off") + '"><span class="me-bd-i">' + ic(icon) + "</span>"
    + "<span><b>" + esc(title) + "</b><small>" + esc(sub) + "</small></span></li>";
  const left = (need, have) => T.bdLeft.replace("%d", Math.max(0, need - have));
  return '<ul class="me-badges">'
    + b(!!s.first, "flag", T.bdFirst, s.first ? dayMonth(s.first) : T.bdFirstHow)
    + b(!!s.hundredth, "stack", T.bdHundred, s.hundredth ? dayMonth(s.hundredth) : left(100, s.trades))
    + b(s.best_streak >= 7, "flame", T.bdStreak, s.best_streak >= 7 ? T.bdBest.replace("%d", s.best_streak) : left(7, s.best_streak))
    + b(s.reviews >= 50, "book", T.bdReviews, s.reviews >= 50 ? T.bdDone : left(50, s.reviews))
    + "</ul>";
}

function pane(){
  if (!user()) return "";
  const s = data.stats;
  return ''
    + '<div class="me-head">'
    +   '<div class="me-av-wrap">' + avatar(76)
    +     '<button type="button" class="me-cam" id="mePhotoCam" aria-label="' + esc(user().avatar ? T.meChange : T.meUpload) + '">' + ic("camera") + "</button></div>"
    +   '<div class="me-who">' + nickBlock()
    +     '<div class="me-acts"><button type="button" class="btn" id="mePhoto">' + esc(user().avatar ? T.meChange : T.meUpload) + "</button>"
    +       (user().avatar ? '<button type="button" class="btn" id="mePhotoDel">' + esc(T.meRemove) + "</button>" : "")
    +       '<span class="me-photo-msg" id="mePhotoMsg" role="alert"></span></div>'
    +     '<input type="file" id="meFile" accept="image/png,image/jpeg,image/webp,image/gif" hidden>'
    +   "</div>"
    + "</div>"
    + presetsBlock()
    + '<div class="me-block"><h4 class="me-h">' + esc(T.meStats) + "</h4>" + tiles(s) + "</div>"
    + '<div class="me-two">'
    +   '<div class="me-card"><h4 class="me-h">' + esc(T.meHeat) + "</h4>" + cal(s) + "</div>"
    +   '<div class="me-card"><h4 class="me-h">' + esc(T.mePairs) + "</h4>" + pairs(s) + "</div>"
    + "</div>"
    + '<div class="me-block"><h4 class="me-h">' + esc(T.meBadges) + "</h4>" + badges(s) + "</div>";
}

/* Ряд готових аватарок під фото. Вибрана — з обведенням. */
function currentPreset(){
  const m = /\/static\/avatars\/([a-z]+)\.svg/.exec((user() && user().avatar) || "");
  return m ? m[1] : "";
}
function presetsBlock(){
  const cur = currentPreset();
  const list = allPresets ? PRESETS : PRESETS.slice(0, PRESET_SHOWN);
  return '<div class="me-pick">'
    + '<div class="me-pick-h"><span>' + esc(T.mePresets) + "</span>"
    +   '<button type="button" class="me-pick-more" id="mePresetMore" aria-expanded="' + allPresets + '">'
    +     esc(allPresets ? T.meLessPresets : T.meAllPresets + " · " + PRESETS.length) + "</button></div>"
    + '<div class="me-pick-grid">'
    + list.map(id => '<button type="button" class="me-pre" data-preset="' + id + '" aria-pressed="' + (id === cur) + '"'
        + ' aria-label="' + esc(T["av_" + id] || id) + '" title="' + esc(T["av_" + id] || id) + '">'
        + '<img src="/static/avatars/' + id + ".svg?v=" + PRESET_V + '" alt="" width="52" height="52" loading="lazy"></button>').join("")
    + "</div></div>";
}
async function setPreset(id){
  if (busy || id === currentPreset()) return;
  busy = true;
  photoMsg("");
  try{
    const d = await api("POST", "/api/me/avatar/preset", {id: id});
    data.user = d.user;
  }catch(e){ photoMsg(T.mePhotoErr); }
  busy = false;
  redraw();
}

/* ------------------------------------------------------------ дії */

function redraw(){
  if (window.__sideMe && user()) __sideMe.paint(user());
  if (window.__settings) __settings.redraw();
}

function nickMsg(state, text){
  const box = $id("meNickBox"), msg = $id("meNickMsg"), save = $id("meNickSave");
  if (box) box.className = "me-nick-f" + (state ? " " + state : "");
  if (msg){ msg.className = "me-nick-msg" + (state ? " " + state : ""); msg.textContent = text || ""; msg.hidden = !text; }
  if (save) save.disabled = state === "bad" || state === "wait";
}

/* Перевірка під час набору: спершу формат у браузері, потім — чи вільний
   (з паузою, щоб не смикати сервер на кожну літеру). */
function checkNick(){
  clearTimeout(checkTimer);
  const v = draft.trim();
  if (v === user().nickname) return nickMsg("", "");
  if (!NICK_RE.test(v)) return nickMsg("bad", T.meNickBad);
  nickMsg("wait", "");
  const seq = ++checkSeq;
  checkTimer = setTimeout(async () => {
    try{
      const r = await api("GET", "/api/me/nick-check?n=" + encodeURIComponent(v));
      if (seq !== checkSeq) return;
      if (r.code === "taken") nickMsg("bad", T.meNickTaken);
      else if (r.code === "bad") nickMsg("bad", T.meNickBad);
      else nickMsg("ok", T.meNickFree);
    }catch(e){ if (seq === checkSeq) nickMsg("", ""); }
  }, 350);
}

async function saveNick(){
  if (busy) return;
  const v = draft.trim();
  if (v === user().nickname){ editing = false; return redraw(); }
  if (!NICK_RE.test(v)) return nickMsg("bad", T.meNickBad);
  busy = true;
  try{
    const res = await fetch("/api/me/nick", {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({nickname: v}),
    });
    const d = await res.json().catch(() => ({}));
    busy = false;
    if (!res.ok) return nickMsg("bad", d.code === "taken" ? T.meNickTaken : d.code === "too_many" ? T.meNickWait : T.meNickBad);
    data.user = d.user;
    editing = false;
    redraw();
  }catch(e){
    busy = false;
    nickMsg("bad", T.pwErrGeneric);
  }
}

function photoMsg(text){ const n = $id("mePhotoMsg"); if (n) n.textContent = text || ""; }

/* ------------------------------------------------ редактор фото ----
   Після вибору файла — шар поверх вікна: фото в круглій рамці, його
   тягнуть мишею чи пальцем, масштаб — повзунком, кнопками − і +,
   колесом миші або щипком двома пальцями. Зберігається рівно те, що
   в колі: квадрат 256×256, webp (jpeg, якщо браузер webp не вміє).

   Геометрія: V — сторона рамки в пікселях екрана; s — масштаб (скільки
   пікселів екрана на піксель фото); x, y — де лівий верхній кут фото
   відносно рамки. Фото завжди закриває рамку цілком — порожніх країв
   у колі не буває. */
const crop = {img: null, url: "", V: 280, s: 1, min: 1, max: 4, x: 0, y: 0, pts: new Map(), pinch: null};

function cropClamp(){
  const w = crop.img.naturalWidth * crop.s, h = crop.img.naturalHeight * crop.s;
  crop.x = Math.min(0, Math.max(crop.V - w, crop.x));
  crop.y = Math.min(0, Math.max(crop.V - h, crop.y));
}

function cropPaint(){
  const im = $id("meCropImg"), zoom = $id("meCropZoom");
  if (!im) return;
  cropClamp();
  im.style.width = crop.img.naturalWidth * crop.s + "px";
  im.style.height = crop.img.naturalHeight * crop.s + "px";
  im.style.transform = "translate(" + crop.x + "px," + crop.y + "px)";
  if (zoom) zoom.value = String(Math.round((crop.s - crop.min) / (crop.max - crop.min) * 100));
}

/* масштаб навколо точки (px, py) у рамці: ця точка фото лишається під пальцем */
function cropZoomTo(s, px, py){
  s = Math.min(crop.max, Math.max(crop.min, s));
  if (px == null){ px = crop.V / 2; py = crop.V / 2; }
  const fx = (px - crop.x) / crop.s, fy = (py - crop.y) / crop.s;
  crop.s = s;
  crop.x = px - fx * s;
  crop.y = py - fy * s;
  cropPaint();
}

function cropReset(){
  crop.min = crop.V / Math.min(crop.img.naturalWidth, crop.img.naturalHeight);
  crop.max = crop.min * 5;
  crop.s = crop.min;
  crop.x = (crop.V - crop.img.naturalWidth * crop.s) / 2;
  crop.y = (crop.V - crop.img.naturalHeight * crop.s) / 2;
  cropPaint();
}

function cropClose(){
  const layer = $id("meCrop");
  if (layer) layer.remove();
  if (crop.url) URL.revokeObjectURL(crop.url);
  crop.img = null; crop.url = ""; crop.pts.clear(); crop.pinch = null;
  const cam = $id("mePhotoCam");
  if (cam) cam.focus();
}

function openCrop(file){
  if (!file) return;
  if ($id("meCrop")) cropClose();          // редактор завжди один
  photoMsg("");
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onerror = () => { URL.revokeObjectURL(url); photoMsg(T.mePhotoErr); };
  img.onload = () => {
    if ($id("meCrop")) cropClose();
    crop.img = img; crop.url = url;
    const box = document.querySelector(".modal-box");
    if (!box) return;
    const minus = '<path d="M5 12h14"/>', plus = '<path d="M12 5v14M5 12h14"/>';
    const svg = p => '<svg class="me-ic" viewBox="0 0 24 24" aria-hidden="true">' + p + "</svg>";
    box.insertAdjacentHTML("beforeend",
      '<div class="me-crop" id="meCrop" role="dialog" aria-modal="true" aria-label="' + esc(T.meCropTitle) + '" data-own-esc>'
      + '<div class="me-crop-in">'
      +   '<h3>' + esc(T.meCropTitle) + "</h3>"
      +   '<p class="me-crop-hint">' + esc(T.meCropHint) + "</p>"
      +   '<div class="me-crop-view" id="meCropView" tabindex="0" aria-label="' + esc(T.meCropHint) + '">'
      +     '<img id="meCropImg" alt="" draggable="false" src="' + url + '">'
      +     '<div class="me-crop-ring" aria-hidden="true"></div>'
      +   "</div>"
      +   '<div class="me-crop-zoom">'
      +     '<button type="button" class="me-ib" id="meCropOut" aria-label="' + esc(T.meZoomOut) + '">' + svg(minus) + "</button>"
      +     '<input type="range" id="meCropZoom" min="0" max="100" step="1" value="0" aria-label="' + esc(T.meZoom) + '">'
      +     '<button type="button" class="me-ib" id="meCropIn" aria-label="' + esc(T.meZoomIn) + '">' + svg(plus) + "</button>"
      +   "</div>"
      +   '<p class="me-crop-err" id="meCropErr" role="alert"></p>'
      +   '<div class="me-crop-acts">'
      +     '<button type="button" class="btn" id="meCropReset">' + esc(T.meCropReset) + "</button>"
      +     '<span class="sp"></span>'
      +     '<button type="button" class="btn" id="meCropCancel">' + esc(T.meCancel) + "</button>"
      +     '<button type="button" class="btn primary" id="meCropSave">' + esc(T.meCropSave) + "</button>"
      +   "</div>"
      + "</div></div>");
    const view = $id("meCropView");
    crop.V = view.clientWidth || 280;
    cropReset();
    wireCrop(view);
    view.focus();
  };
  img.src = url;
}

function wireCrop(view){
  const step = () => (crop.max - crop.min) / 10;
  $id("meCropZoom").oninput = e => cropZoomTo(crop.min + (crop.max - crop.min) * e.target.value / 100);
  $id("meCropIn").onclick = () => cropZoomTo(crop.s + step());
  $id("meCropOut").onclick = () => cropZoomTo(crop.s - step());
  $id("meCropReset").onclick = cropReset;
  $id("meCropCancel").onclick = cropClose;
  $id("meCropSave").onclick = cropSave;

  const at = e => { const r = view.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  view.addEventListener("wheel", e => {
    e.preventDefault();
    const [px, py] = at(e);
    cropZoomTo(crop.s * Math.exp(-e.deltaY * 0.0015), px, py);
  }, {passive: false});

  view.addEventListener("pointerdown", e => {
    view.setPointerCapture(e.pointerId);
    crop.pts.set(e.pointerId, at(e));
    if (crop.pts.size === 2){
      const [a, b] = [...crop.pts.values()];
      crop.pinch = {d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: crop.s};
    }
  });
  view.addEventListener("pointermove", e => {
    if (!crop.pts.has(e.pointerId)) return;
    const prev = crop.pts.get(e.pointerId), now = at(e);
    crop.pts.set(e.pointerId, now);
    if (crop.pts.size >= 2 && crop.pinch){
      const [a, b] = [...crop.pts.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      cropZoomTo(crop.pinch.s * d / (crop.pinch.d || 1), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    } else {
      crop.x += now[0] - prev[0];
      crop.y += now[1] - prev[1];
      cropPaint();
    }
  });
  const up = e => { crop.pts.delete(e.pointerId); if (crop.pts.size < 2) crop.pinch = null; };
  view.addEventListener("pointerup", up);
  view.addEventListener("pointercancel", up);

  /* клавіатура: стрілки — зсув, + і − — масштаб, Esc — скасувати */
  $id("meCrop").addEventListener("keydown", e => {
    if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); return cropClose(); }
    if (e.target !== view) return;
    const k = {ArrowLeft: [10, 0], ArrowRight: [-10, 0], ArrowUp: [0, 10], ArrowDown: [0, -10]}[e.key];
    if (k){ e.preventDefault(); crop.x += k[0]; crop.y += k[1]; cropPaint(); }
    if (e.key === "+" || e.key === "="){ e.preventDefault(); cropZoomTo(crop.s + step()); }
    if (e.key === "-"){ e.preventDefault(); cropZoomTo(crop.s - step()); }
  });
}

async function cropSave(){
  if (busy || !crop.img) return;
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.drawImage(crop.img, -crop.x / crop.s, -crop.y / crop.s, crop.V / crop.s, crop.V / crop.s, 0, 0, 256, 256);
  let out = c.toDataURL("image/webp", 0.88);
  if (!out.startsWith("data:image/webp")) out = c.toDataURL("image/jpeg", 0.9);
  busy = true;
  const btn = $id("meCropSave"); if (btn) btn.disabled = true;
  try{
    const d = await api("POST", "/api/me/avatar", {data: out});
    data.user = d.user;
    busy = false;
    cropClose();
    redraw();
  }catch(e){
    busy = false;
    if (btn) btn.disabled = false;
    const err = $id("meCropErr"); if (err) err.textContent = T.mePhotoErr;
  }
}

async function removePhoto(){
  if (busy) return;
  busy = true;
  try{
    const d = await api("POST", "/api/me/avatar/remove", {});
    data.user = d.user;
  }catch(e){ photoMsg(T.mePhotoErr); }
  busy = false;
  redraw();
}

function wire(){
  if (!user()) return;
  const edit = $id("meNickEdit");
  if (edit) edit.onclick = () => { editing = true; draft = user().nickname; redraw(); };
  const inp = $id("meNickIn");
  if (inp){
    setTimeout(() => { inp.focus(); inp.select(); }, 30);
    inp.oninput = () => { draft = inp.value; checkNick(); };
    inp.onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); saveNick(); }
      if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); editing = false; redraw(); }
    };
    checkNick();
  }
  const save = $id("meNickSave");
  if (save) save.onclick = saveNick;
  const cancel = $id("meNickCancel");
  if (cancel) cancel.onclick = () => { editing = false; redraw(); };

  const file = $id("meFile");
  const pick = () => { if (file){ file.value = ""; file.click(); } };
  ["mePhoto", "mePhotoCam"].forEach(id => { const b = $id(id); if (b) b.onclick = pick; });
  if (file) file.onchange = () => openCrop(file.files && file.files[0]);
  const del = $id("mePhotoDel");
  if (del) del.onclick = removePhoto;

  const more = $id("mePresetMore");
  if (more) more.onclick = () => { allPresets = !allPresets; redraw(); };
  document.querySelectorAll(".me-pre[data-preset]").forEach(b => { b.onclick = () => setPreset(b.dataset.preset); });
  wireCal();
}

/* Гортання місяців перемальовує сам календар, а не все вікно: інакше
   від кожної стрілки блимали б і фото, і плитки. */
function wireCal(){
  document.querySelectorAll(".me-cal-nav[data-cal]").forEach(b => {
    b.onclick = () => {
      if (b.disabled || !data || !data.stats) return;
      calShift += Number(b.dataset.cal);
      const box = document.querySelector(".me-cal");
      if (!box) return;
      box.outerHTML = cal(data.stats);
      wireCal();
    };
  });
}

window.__me = {load: load, pane: pane, wire: wire, avatar: avatar, user: user};

})();
