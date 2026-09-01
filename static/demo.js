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
    trades = await res.json();
    persist();
  }

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
