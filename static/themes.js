/* ============================================================
   Оформлення: вибір теми.

   Дев'ять готових наборів плюс своя, зібрана з двох кольорів.
   Тема — це data-skin на <html>; самі кольори живуть у themes.css.
   Разом зі шкіркою ставимо data-theme: від нього залежать правила,
   написані до появи тем.
   ============================================================ */
(function(){

const KEY  = "statsai_skin";
const SEED = "statsai_skin_custom";

function THEMES(){ return [
  {id:"night",    name:T.thNight,       base:"dark",  bg:"#050505", panel:"#0d0d0e",
   line:"#26262a", accent:"#40e094", up:"#40e094", down:"#ff6e60", be:"#efc258"},
  {id:"graphite", name:T.thGraphite,    base:"dark",  bg:"#101012", panel:"#17171a",
   line:"#2c2c31", accent:"#f0a13c", up:"#59c98a", down:"#ef6a5e", be:"#e0b352"},
  {id:"midnight", name:T.thMidnight,   base:"dark",  bg:"#070b14", panel:"#0d1421",
   line:"#22304a", accent:"#38bdf8", up:"#34d399", down:"#fb7185", be:"#fbbf24"},
  {id:"wine",     name:T.thWine,      base:"dark",  bg:"#120a12", panel:"#1b101c",
   line:"#352036", accent:"#f472b6", up:"#6ee7b7", down:"#fb7185", be:"#fcd34d"},
  {id:"pine",     name:T.thPine,      base:"dark",  bg:"#06110d", panel:"#0c1a14",
   line:"#1b3328", accent:"#a3e635", up:"#4ade80", down:"#f87171", be:"#facc15"},

  {id:"day",      name:T.thDay,      base:"light", bg:"#f2f4f8", panel:"#ffffff",
   line:"#dde3ec", accent:"#2b62e3", up:"#128a53", down:"#c94430", be:"#9c7514"},
  {id:"paper",    name:T.thPaper,     base:"light", bg:"#f6f2ea", panel:"#fffdf8",
   line:"#e3dbcc", accent:"#c2410c", up:"#15803d", down:"#b91c1c", be:"#a16207"},
  {id:"fog",      name:T.thFog,     base:"light", bg:"#eef1f5", panel:"#ffffff",
   line:"#d9dfe7", accent:"#475569", up:"#0f766e", down:"#be123c", be:"#a16207"},
  {id:"sand",     name:T.thSand,     base:"light", bg:"#f4f1e8", panel:"#fffefa",
   line:"#ded8c6", accent:"#4d7c0f", up:"#3f6212", down:"#9f1239", be:"#92400e"},
]; }

const DEFAULT_SEED = {base:"dark", bg:"#0b0f14", accent:"#7dd3fc"};

function seed(){
  try{ return Object.assign({}, DEFAULT_SEED, JSON.parse(localStorage.getItem(SEED) || "{}")); }
  catch(e){ return Object.assign({}, DEFAULT_SEED); }
}
function current(){
  try{ return localStorage.getItem(KEY) || "night"; }catch(e){ return "night"; }
}

/* ---------- застосування ---------- */
function apply(id){
  const root = document.documentElement;
  if (id === "custom"){
    const s = seed();
    root.style.setProperty("--seed-bg", s.bg);
    root.style.setProperty("--seed-accent", s.accent);
    /* текст і лінії виводимо з бази: на темному — світлі, на світлому — темні */
    root.style.setProperty("--seed-ink", s.base === "dark" ? "#f4f5f7" : "#171b24");
    root.setAttribute("data-theme", s.base);
  } else {
    const t = THEMES().find(x => x.id === id) || THEMES()[0];
    id = t.id;
    ["--seed-bg","--seed-accent","--seed-ink"].forEach(v => root.style.removeProperty(v));
    root.setAttribute("data-theme", t.base);
  }
  root.setAttribute("data-skin", id);
  try{ localStorage.setItem(KEY, id); }catch(e){}
  if (window.Ticker && typeof render === "function") render();
}

/* ---------- вікно ---------- */
function swatch(t){
  return '<div class="th-prev" style="background:' + t.bg + '">'
    + '<div class="sheet" style="background:' + t.panel + ';border:1px solid ' + t.line + '"></div>'
    + '<div class="bar" style="background:' + t.accent + '"></div>'
    + '<div class="dots"><i style="background:' + t.up + '"></i>'
    + '<i style="background:' + t.down + '"></i>'
    + '<i style="background:' + t.be + '"></i></div></div>';
}

function card(t, on){
  return '<button class="th-card' + (on ? " on" : "") + '" onclick="__skin.set(\'' + t.id + '\')">'
    + swatch(t)
    + '<div class="nm">' + esc(t.name) + (on ? "<i>"+T.thSelected+"</i>" : "") + "</div></button>";
}

function customCard(on){
  const s = seed();
  return '<button class="th-card' + (on ? " on" : "") + '" onclick="__skin.set(\'custom\')">'
    + swatch({bg:s.bg, panel:s.bg, line:s.accent, accent:s.accent,
              up:s.accent, down:s.accent, be:s.accent})
    + '<div class="nm">'+T.thCustom+'' + (on ? "<i>"+T.thSelected+"</i>" : "") + "</div></button>";
}

function draw(){
  const now = current();
  const s = seed();
  const group = (title, list) =>
    '<div class="nt-sub">' + title + "</div>"
    + '<div class="th-grid">' + list.map(t => card(t, t.id === now)).join("") + "</div>";

  const h = '<div class="m-head"><h2>'+T.thModalTitle+'</h2>'
    + '<button class="x" onclick="closeModal()">×</button></div>'
    + '<div class="m-body"><div class="nt th-grp">'
    + group(T.thDarkGroup,  THEMES().filter(t => t.base === "dark"))
    + group(T.thLightGroup, THEMES().filter(t => t.base === "light"))
    + '<div class="nt-sub">'+T.thCustom+'</div>'
    + '<div class="th-grid">' + customCard(now === "custom") + "</div>"
    + '<div class="th-custom">'
    +   '<div class="th-pick"><span>'+T.thBase+'</span><div class="th-base">'
    +     '<button class="' + (s.base === "dark" ? "on" : "") + '" onclick="__skin.seed(\'base\',\'dark\')">'+T.thBaseDark+'</button>'
    +     '<button class="' + (s.base === "light" ? "on" : "") + '" onclick="__skin.seed(\'base\',\'light\')">'+T.thBaseLight+'</button>'
    +   "</div></div>"
    +   '<div class="th-pick"><span>'+T.thBg+'</span>'
    +     '<input type="color" value="' + s.bg + '" oninput="__skin.seed(\'bg\', this.value)"></div>'
    +   '<div class="th-pick"><span>'+T.thAccent+'</span>'
    +     '<input type="color" value="' + s.accent + '" oninput="__skin.seed(\'accent\', this.value)"></div>'
    +   '<p class="nt-note" style="flex:1 1 180px">'+T.thNoteHint+"</p>"
    + "</div></div></div>"
    + '<div class="m-foot"><span class="sp"></span>'
    + '<button class="btn primary" onclick="closeModal()">'+T.ckDone+'</button></div>';
  openModal(h);
}

/* ---------- ручки ---------- */
window.__skin = {
  open: draw,
  set(id){ apply(id); draw(); },
  seed(field, value){
    const s = seed();
    s[field] = value;
    try{ localStorage.setItem(SEED, JSON.stringify(s)); }catch(e){}
    apply("custom");
    /* перемальовуємо тільки при зміні основи: інакше повзунок кольору
       зникає з-під пальця, поки його тягнеш */
    if (field === "base") draw();
    else {
      const box = document.getElementById("modalBox");
      const mark = box && box.querySelectorAll(".th-card");
      if (mark) mark.forEach(c => c.classList.toggle("on",
        c.getAttribute("onclick").indexOf("'custom'") > 0));
    }
  },
};

apply(current());

})();
