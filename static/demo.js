/* ============================================================
   Демо-режим.

   Когда журнал открыт без app.py (например, на Vercel), сделки
   хранятся прямо в браузере посетителя — в localStorage.
   У каждого своя песочница: правки видны только ему и не уходят
   ни на какой сервер.

   Модуль повторяет тот же набор запросов, что и app.py, поэтому
   остальной код работает без изменений.
   ============================================================ */
(function () {
  const KEY   = "tj_demo_trades";
  const SEED  = "/static/demo-data.json";
  const FIELDS = ["pair","date","session","position","entry_model","bias","setup","direction_type",
                  "result","rr","risk","entry_details","notes","mistakes","comments"];

  let trades = [];
  let counter = Date.now();
  let warnedQuota = false;

  function newId() { return "d" + (++counter); }

  /* приведение сделки к той же форме, что делает сервер */
  function cleanTrade(body, id) {
    const t = { id: id };
    for (const k of FIELDS) t[k] = body[k] != null ? body[k] : "";
    for (const k of ["rr", "risk"]) {
      const raw = String(t[k]).trim();
      const v = parseFloat(raw);
      t[k] = raw === "" || isNaN(v) ? null : v;
    }
    t.screenshots = (body.screenshots || []).map(s => ({ tf: s.tf || "", data: s.data || "", file: s.file || "" }))
                                            .filter(s => s.data || s.file);
    if (body.hidden) t.hidden = true;
    return t;
  }

  /* Скриншоты — крупные картинки, а места в браузере всего несколько мегабайт.
     Если не влезло, сохраняем сделки без картинок и честно предупреждаем. */
  function persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify(trades));
      return;
    } catch (e) {
      for (const t of trades) t.screenshots = [];
      try { localStorage.setItem(KEY, JSON.stringify(trades)); } catch (e2) {}
      if (!warnedQuota) {
        warnedQuota = true;
        alert(T.dmQuotaAlert);
      }
    }
  }

  async function init() {
    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) {}
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) { trades = parsed; return; }
      } catch (e) {}
    }
    const res = await fetch(SEED, { cache: "no-store" });
    if (!res.ok) throw new Error("demo seed " + res.status);
    trades = freshenMonth(shiftToToday(await res.json()));
    persist();
  }

  /* Приклади записані колись і з часом опиняються в минулому: людина
     заходить, а «місяць» і «квартал» порожні — виходить, ніби журнал
     нічого не рахує. Тому при першому завантаженні зсуваємо всі дати так,
     щоб остання угода була вчорашньою. Проміжки між угодами лишаються ті
     самі, тож картина не змінюється — просто вона завжди свіжа. */
  function shiftToToday(list) {
    const days = list.map(t => String(t.date || "").slice(0, 10)).filter(Boolean).sort();
    if (!days.length) return list;
    const last = new Date(days[days.length - 1] + "T00:00:00");
    const target = new Date();
    target.setHours(0, 0, 0, 0);
    target.setDate(target.getDate() - 1);
    const shift = Math.round((target - last) / 86400000);
    if (!shift) return list;
    for (const t of list) {
      const raw = String(t.date || "");
      if (raw.length < 10) continue;
      const d = new Date(raw.slice(0, 10) + "T00:00:00");
      if (isNaN(d)) continue;
      d.setDate(d.getDate() + shift);
      t.date = d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
             + raw.slice(10);
    }
    return list;
  }

  /* Зсув лишає поточний місяць майже порожнім, якщо сьогодні його початок:
     людина відкриває «Місяць» і бачить нулі — виходить, ніби статистика не
     працює. Тому останні угоди розкладаємо по днях, які вже минули цього
     місяця. Днів мало — угоди стають щільніші, але для журналу, де по три
     угоди на день, це звична картина. */
  function freshenMonth(list) {
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const last = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (last < first) return list;                     // сьогодні перше число
    const span = Math.round((last - first) / 86400000);

    const edge = new Date(last);
    edge.setDate(edge.getDate() - 30);
    const recent = list.filter(t => new Date(String(t.date).slice(0, 10) + "T00:00:00") > edge)
                       .sort((a, b) => String(a.date).localeCompare(String(b.date)));
    if (recent.length < 2) return list;

    recent.forEach((t, i) => {
      const d = new Date(first);
      d.setDate(d.getDate() + Math.round(i * span / (recent.length - 1)));
      t.date = dateStr(d, t.date);
    });

    /* Місяць, з якого ми забрали ці угоди, лишився б напівпорожнім — на
       графіку року видно провал. Тому решту рівномірно розтягуємо до
       кінця минулого місяця: проміжки лишаються пропорційними. */
    const rest = list.filter(t => recent.indexOf(t) < 0)
                     .sort((a, b) => String(a.date).localeCompare(String(b.date)));
    if (rest.length > 1){
      const from = day(rest[0].date), to = day(rest[rest.length - 1].date);
      const room = new Date(first); room.setDate(0);          // останній день минулого місяця
      const was = (to - from) / 86400000, now2 = (room - from) / 86400000;
      if (was > 0 && now2 > was){
        for (const t of rest){
          const d = new Date(from);
          d.setDate(d.getDate() + Math.round((day(t.date) - from) / 86400000 * now2 / was));
          t.date = dateStr(d, t.date);
        }
      }
    }
    return list;
  }

  function day(v){ return new Date(String(v).slice(0, 10) + "T00:00:00"); }
  function dateStr(d, src){
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
         + String(src).slice(10);
  }

  function pad2(n) { return n < 10 ? "0" + n : String(n); }

  function reset() {
    try { localStorage.removeItem(KEY); } catch (e) {}
    location.reload();
  }

  /* тот же контракт, что у app.py: method + url + тело */
  async function handle(method, url, body) {
    const path = url.split("?")[0];

    if (method === "GET" && path === "/api/trades") return trades.slice();

    if (method === "POST" && path === "/api/trades") {
      if (!body || !String(body.pair || "").trim()) throw new Error("API 400");
      const t = cleanTrade(body, newId());
      trades.push(t); persist();
      return t;
    }

    if (method === "POST" && path === "/api/import") {
      const items = Array.isArray(body) ? body : (body && body.trades) || [];
      let added = 0;
      for (const it of items) {
        if (!it || typeof it !== "object") continue;
        trades.push(cleanTrade(it, newId())); added++;
      }
      persist();
      return { ok: true, added: added };
    }

    const m = path.match(/^\/api\/trades\/([\w-]+)$/);
    if (m) {
      const id = m[1];
      const i = trades.findIndex(t => t.id === id);
      if (i < 0) throw new Error("API 404");
      if (method === "PUT") {
        const t = cleanTrade(body || {}, id);
        trades[i] = t; persist();
        return t;
      }
      if (method === "DELETE") {
        trades.splice(i, 1); persist();
        return { ok: true };
      }
    }

    throw new Error("API 404");
  }

  window.DemoStore = { init, handle, reset };
})();
