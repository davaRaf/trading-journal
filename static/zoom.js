/* ============================================================
   Лупа для скрінів у перегляді на весь екран.

   Одна й та сама поведінка всюди, де скрін відкривається великим:
   у застосунку (#lightbox — угоди, розбір дня, «Моя ТС», чужий журнал)
   і на сторінці за посиланням (.big у share.html).

     колесо миші        — наблизити/віддалити навколо курсора
     клік по картинці   — наблизити у 2.5 раза в цю точку; ще клік — назад
     тягнути            — посунути наближений скрін
     щипок двома пальцями — на телефоні

   Клік по картинці більше не закриває перегляд — закриває клік повз
   неї, хрестик або Escape. Стан живе на самій картинці (img.__zoom):
   зміна скріна чи закриття скидають його через Zoom.reset(img).
   ============================================================ */
window.Zoom = (function(){
  const MIN = 1, MAX = 6, TAP = 2.5;

  function attach(img){
    if (!img || img.__zoom) return img && img.__zoom;
    const st = {s: 1, x: 0, y: 0, ptrs: new Map(), drag: null, pinch: null, moved: false};
    img.style.touchAction = "none";
    img.draggable = false;

    /* центр картинки в розкладці — масштаб навколо центру його не рушить,
       тож із поточного прямокутника віднімаємо лише зсув */
    const center = () => {
      const r = img.getBoundingClientRect();
      return {x: r.left + r.width / 2 - st.x, y: r.top + r.height / 2 - st.y};
    };
    /* не даємо картинці втекти за край: коли вона більша за екран,
       край не заходить усередину; коли менша — стоїть по центру */
    const clampT = () => {
      const w = img.offsetWidth * st.s, h = img.offsetHeight * st.s;
      const lx = Math.max(0, (w - innerWidth) / 2), ly = Math.max(0, (h - innerHeight) / 2);
      st.x = Math.max(-lx, Math.min(lx, st.x));
      st.y = Math.max(-ly, Math.min(ly, st.y));
    };
    const apply = () => {
      /* Анімація появи (motion.css: .lightbox.m-in img — mZoom, fill both)
         тримає свій transform:none поверх нашого, і лупа не рухала б
         картинку. Вона вже дограла — знімаємо клас без видимих змін. */
      const anim = img.closest(".m-in");
      if (anim) anim.classList.remove("m-in");
      clampT();
      img.style.transform = st.s === 1 ? "" : "translate(" + st.x + "px," + st.y + "px) scale(" + st.s + ")";
      img.style.cursor = st.s === 1 ? "zoom-in" : (st.drag ? "grabbing" : "grab");
      img.classList.toggle("zoomed", st.s !== 1);
    };
    const reset = () => { st.s = 1; st.x = 0; st.y = 0; st.drag = null; st.pinch = null; apply(); };
    /* наблизити так, щоб точка екрана p лишилась на тому ж місці картинки */
    const zoomAt = (p, s2) => {
      s2 = Math.max(MIN, Math.min(MAX, s2));
      if (s2 === 1){ reset(); return; }
      const c = center();
      const ux = (p.x - c.x - st.x) / st.s, uy = (p.y - c.y - st.y) / st.s;
      st.s = s2;
      st.x = p.x - c.x - s2 * ux;
      st.y = p.y - c.y - s2 * uy;
      apply();
    };

    img.addEventListener("wheel", e => {
      e.preventDefault(); e.stopPropagation();
      zoomAt({x: e.clientX, y: e.clientY}, st.s * Math.exp(-e.deltaY * 0.0015));
    }, {passive: false});

    img.addEventListener("pointerdown", e => {
      e.preventDefault();
      img.setPointerCapture(e.pointerId);
      st.ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
      st.moved = false;
      if (st.ptrs.size === 1){
        st.drag = {px: e.clientX, py: e.clientY, x: st.x, y: st.y};
      } else if (st.ptrs.size === 2){
        const [a, b] = [...st.ptrs.values()];
        st.pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), s: st.s};
        st.drag = null;
      }
      apply();
    });
    img.addEventListener("pointermove", e => {
      if (!st.ptrs.has(e.pointerId)) return;
      st.ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
      if (st.pinch && st.ptrs.size >= 2){
        const [a, b] = [...st.ptrs.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        st.moved = true;
        zoomAt({x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}, st.pinch.s * d / st.pinch.d);
      } else if (st.drag && st.s > 1){
        const dx = e.clientX - st.drag.px, dy = e.clientY - st.drag.py;
        if (Math.abs(dx) + Math.abs(dy) > 3) st.moved = true;
        st.x = st.drag.x + dx; st.y = st.drag.y + dy;
        apply();
      }
    });
    const up = e => {
      st.ptrs.delete(e.pointerId);
      if (st.ptrs.size < 2) st.pinch = null;
      if (st.ptrs.size === 0) st.drag = null;
      apply();
    };
    img.addEventListener("pointerup", up);
    img.addEventListener("pointercancel", up);

    /* клік — лупа, а не закриття; після тягання чи щипка кліком не рахуємо */
    img.addEventListener("click", e => {
      e.stopPropagation();
      if (st.moved){ st.moved = false; return; }
      if (st.s === 1) zoomAt({x: e.clientX, y: e.clientY}, TAP);
      else reset();
    });
    img.addEventListener("dblclick", e => { e.preventDefault(); e.stopPropagation(); });

    img.__zoom = {reset};
    return img.__zoom;
  }

  function reset(img){ if (img && img.__zoom) img.__zoom.reset(); }

  return {attach, reset};
})();
