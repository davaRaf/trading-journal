# -*- coding: utf-8 -*-
"""
Службова сторінка для власників: /admin і картка людини /admin/u/<нік>.

Раніше це були два довгі списки рядків «назва — число». Тепер — панель,
з якою приймають рішення: що змінилось за тиждень порівняно з минулим,
скільки людей реально користується (пише угоди чи розбори дня), де вони
відвалюються, чи повертаються на другий-третій тиждень, скільки привели
партнери і хто вже вперся в безкоштовний ліміт.

«Активність» — це запис угоди або розбору дня. Входів ми не зберігаємо,
тож інших слідів людини в базі немає.

Сторінки малюються тут цілком, на сервері: графіки — SVG, таблиця людей
сортується й фільтрується невеликим скриптом по вбудованих даних.
"""
import datetime
import html as _html
import json
from zoneinfo import ZoneInfo

import db

KYIV = ZoneInfo("Europe/Kyiv")
FREE_LIMIT = 20          # безкоштовних ручних угод до підписки (власник, 29.09.2026)


def billing_start():
    """З якого дня рахуються безкоштовні угоди — або None, якщо дати нема.

    Позначку «limits_started» ставить db._start_limits: подія, яка обнуляє
    лічильники всім і починає відлік наново. Її немає в базі, де колонки
    завелись одразу з двадцяткою: обнуляти там не було чого, ліміти діяли
    від першого дня, і дати «з якої рахуємо» просто не існує.

    Тому None тут означає «дати нема», а не «лімітів нема». Число беремо з
    лічильника біллінга в будь-якому разі, а дату, якщо вона є, пишемо
    поруч дрібним. Раніше сторінка на порожній позначці показувала «не
    запущен» і нулі — на бою, де ліміт давно працює, це була неправда.

    Руками дату можна проставити в meta «billing_start» (РРРР-ММ-ДД) або
    змінною оточення BILLING_START — на самі ліміти це не впливає.
    """
    import os
    raw = ""
    for key in ("limits_started", "billing_start"):
        try:
            raw = (db.meta_get(key, "") or "").strip()
        except Exception:
            raw = ""
        if raw:
            break
    raw = raw or os.environ.get("BILLING_START", "").strip()
    try:
        return datetime.date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def limits_at():
    """Та сама мить, але з годиною — межа, з якої рахуємо угоди в адмінці.

    Усе, записане до запуску лімітів, панель не показує: тієї хвилини
    лічильники обнулили всім, і старі угоди в ліміт не пішли. Якби картка
    рахувала журнал цілком, вона показувала б «30 вручну» там, де біллінг
    бачить п'ять, і поруч два числа про різне.

    Беремо саме відмітку з meta (там ISO з часом), а не дату з
    billing_start: угоди того ж дня, записані до викладки, теж лишились
    поза лімітом. Немає відмітки — немає й межі: рахуємо все, як раніше.
    """
    try:
        raw = (db.meta_get("limits_started", "") or "").strip()
    except Exception:
        raw = ""
    if raw:
        try:
            at = datetime.datetime.fromisoformat(raw)
            return at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    d = billing_start()
    return datetime.datetime.combine(d, datetime.time(), KYIV) if d else None


def _since(col="created_at"):
    """(хвіст WHERE, аргументи) — «тільки після запуску лімітів»."""
    at = limits_at()
    return (" AND %s >= %%s" % col, (at,)) if at else ("", ())


# ------------------------------------------------------------ дрібниці ----

PLAN_RU = {"month": "Месяц", "quarter": "Квартал", "year": "Год"}


def _access(u, free):
    """Крупна плашка вгорі картки: який у людини доступ зараз — щоб не
    шукати це в таблиці нижче після кожної видачі."""
    now = datetime.datetime.now(datetime.timezone.utc)
    sub = _sub(u, now)
    box = ('<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:16px 18px;'
           'margin-bottom:14px;border-radius:14px;border:1px solid %s;background:%s">'
           '<span style="font-size:22px;font-weight:700;color:%s">%s</span>'
           '<span style="color:var(--text);font-size:14.5px">%s</span></div>')
    if sub == "life":
        since = u.get("special_since")
        return box % ("#e3b341", "rgba(227,179,65,.10)", "#e3b341", "★ Special",
                      "полный доступ навсегда, без оплаты"
                      + (" · выдан %s" % since.strftime("%d.%m.%Y") if since else ""))
    if sub:
        until = u["paid_until"]
        left = max(0, (until - now).days)
        return box % ("var(--acc)", "rgba(64,224,148,.08)", "var(--acc)", "Подписка · " + PLAN_RU.get(sub, sub),
                      "до %s · осталось %d дн." % (until.astimezone(KYIV).strftime("%d.%m.%Y"), left))
    cap = u.get("free_trades_cap") or FREE_LIMIT
    return box % ("var(--line)", "transparent", "var(--dim)", "Бесплатный доступ",
                  "использовано %d из %d сделок" % (free, cap))


def _sub(u, now):
    """Чим людина зараз користується: month/quarter/year, life (Special) або ''."""
    if u.get("plan") == "life":
        return "life"
    until = u.get("paid_until")
    if until and until > now and u.get("plan") not in (None, "", "free"):
        return u["plan"]
    return ""


def e(x):
    return _html.escape("" if x is None else str(x), quote=True)


def _js(value):
    """Значення всередину <script>. Те саме, що json.dumps, але з "</"
    розірваним: інакше будь-який рядок із "</script>" закрив би тег."""
    return json.dumps(value, ensure_ascii=False, default=str).replace("</", "<\\/")


def _q(sql, args=None):
    """Запит, який не валить сторінку: таблиці може ще не бути (нова база),
    тоді показуємо нуль, а не 500."""
    try:
        with db.connect() as c:
            cur = c.execute(sql, args) if args is not None else c.execute(sql)
            return cur.fetchall()
    except Exception as ex:
        print("admin:", ex)
        return []


def _inits():
    for mod in ("day_store", "share_store", "ts_store", "oauth", "accounts_store"):
        try:
            __import__(mod).init()
        except Exception as ex:
            print("admin init", mod, ex)


def _today():
    return datetime.datetime.now(KYIV).date()


def _kdate(ts):
    return ts.astimezone(KYIV).date() if ts else None


def _monday(d):
    return d - datetime.timedelta(days=d.weekday())


def _ago(days):
    if days is None:
        return "—"
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    return "%d дн. назад" % days


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# ---------------------------------------------------------------- стиль ----

CSS = """
:root{--bg:#050505;--panel:#0d0d0e;--card:#111113;--line:rgba(255,255,255,.075);--soft:rgba(255,255,255,.045);
--text:#f2f2f3;--dim:#8f8f95;--faint:#5e5e64;--acc:#40e094;--down:#ff6e60;--be:#efc258;--blue:#6aa8ff;
--sans:"Geist","Segoe UI",system-ui,sans-serif;--mono:"Geist Mono","Cascadia Mono",Consolas,monospace}
*{box-sizing:border-box}
html{scrollbar-width:thin;scrollbar-color:#2a2a2e transparent}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.wrap{max-width:1200px;margin:0 auto;padding:22px 20px 70px}
.top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:20px}
.brand{font-weight:700;font-size:18px;letter-spacing:-.01em}
.brand b{color:var(--acc)}
.brand small{font-weight:400;color:var(--faint);font-size:13px;margin-left:8px}
.sp{flex:1}
.search{display:flex;align-items:center;gap:8px;min-width:280px;flex:0 1 380px;padding:0 12px;height:40px;
border:1px solid var(--line);border-radius:11px;background:var(--panel)}
.search input{flex:1;border:0;outline:0;background:transparent;color:var(--text);font:inherit}
.search svg{color:var(--faint);flex:none}
.stamp{color:var(--faint);font-size:12.5px}
h2{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);
font-weight:500;margin:0 0 12px}
.card{border:1px solid var(--line);border-radius:16px;background:var(--panel);padding:16px 18px}
.grid{display:grid;gap:12px}
.kpis{grid-template-columns:repeat(6,1fr);margin-bottom:12px}
.kpi{padding:14px 16px}
.kpi .l{font-size:12px;color:var(--dim);line-height:1.3;min-height:32px}
.kpi .v{font-family:var(--mono);font-size:28px;font-weight:600;letter-spacing:-.02em;line-height:1.1;margin-top:6px}
.kpi .d{font-size:12px;color:var(--faint);margin-top:4px}
.up{color:var(--acc)}.dn{color:var(--down)}.be{color:var(--be)}
.two{grid-template-columns:1fr 1fr;margin-bottom:12px}
.three{grid-template-columns:1.1fr 1fr 1fr;margin-bottom:12px}
svg.ch{width:100%;height:auto;display:block}
.lg{display:flex;gap:14px;font-size:12px;color:var(--dim);margin-top:8px}
.lg i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.fn .st{display:grid;grid-template-columns:150px 1fr 88px;gap:12px;align-items:center;padding:7px 0}
.fn .st:last-of-type{margin-top:6px;border-top:1px dashed var(--line)}
.fn .st+.st{border-top:1px solid var(--soft)}
.fn .n{font-size:13px}
.fn .bar{height:10px;border-radius:6px;background:var(--soft);overflow:hidden}
.fn .bar i{display:block;height:100%;border-radius:6px;background:var(--acc)}
.fn .v{text-align:right;font-family:var(--mono);font-size:13px}
.fn .v small{color:var(--faint);margin-left:6px}
.feat{display:grid;grid-template-columns:1fr auto;gap:6px 12px;font-size:13px}
.feat span:nth-child(even){font-family:var(--mono);text-align:right}
.feat small{color:var(--faint);margin-left:6px}
table{width:100%;border-collapse:collapse}
th{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);
font-weight:500;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--soft);font-size:13px;vertical-align:middle}
td.num,th.num{text-align:right;font-family:var(--mono)}
td:first-child{white-space:nowrap}
tr.lnk{cursor:pointer}tr.lnk:hover td{background:rgba(255,255,255,.025)}
.coh td{text-align:center;font-family:var(--mono);font-size:12px;padding:8px 6px;border-radius:0}
.coh td.lb{text-align:left;font-family:var(--sans);color:var(--dim);white-space:nowrap}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;white-space:nowrap}
.p-active{background:rgba(64,224,148,.14);color:var(--acc)}
.p-cool{background:rgba(239,194,88,.14);color:var(--be)}
.p-sleep{background:rgba(255,110,96,.12);color:var(--down)}
.p-new{background:rgba(255,255,255,.06);color:var(--dim)}
.tag{display:inline-block;font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:5px;
border:1px solid var(--line);color:var(--dim);margin-right:4px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.chip{padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--dim);
font:inherit;font-size:12.5px;cursor:pointer}
.chip.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.chip b{font-family:var(--mono);font-weight:500;margin-left:5px;opacity:.7}
.tw{overflow-x:auto;margin:0 -18px;padding:0 18px}
th.s{cursor:pointer;user-select:none}th.s:hover{color:var(--dim)}th.s.on{color:var(--text)}
.mute{color:var(--faint)}
.list{display:flex;flex-direction:column}
.list a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:8px 0;border-top:1px solid var(--soft);font-size:13px}
.list a>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grid>*{min-width:0}
.list a:first-child{border-top:0}
.list a:hover .nm{color:var(--acc)}
.list small{color:var(--faint)}
.empty{color:var(--faint);font-size:13px;padding:6px 0}
.back{color:var(--dim);font-size:13px}.back:hover{color:var(--text)}
.btn{padding:7px 12px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--text);
font:inherit;font-size:12.5px;cursor:pointer}
.btn:hover{border-color:var(--dim)}
.btn.on{border-color:var(--acc);color:var(--acc)}
.danger{border-color:rgba(255,110,96,.25)}
.danger .go{background:#7a1f1f;border:0;color:#fff}
.kv{display:grid;grid-template-columns:auto 1fr;gap:8px 18px;font-size:13px}
.kv span:nth-child(odd){color:var(--dim)}
.kv span:nth-child(even){text-align:right}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.three{grid-template-columns:1fr 1fr}}
@media(max-width:720px){.wrap{padding:16px 12px 60px}.kpis{grid-template-columns:repeat(2,1fr)}
.two,.three{grid-template-columns:1fr}.search{flex:1 1 100%;min-width:0}.fn .st{grid-template-columns:110px 1fr 74px}
.kpi .v{font-size:24px}}
"""

HEAD = ("<!doctype html><html lang=ru><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'><title>@TITLE@</title>"
        "<link rel=preconnect href='https://fonts.googleapis.com'>"
        "<link rel=preconnect href='https://fonts.gstatic.com' crossorigin>"
        "<link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700"
        "&family=Geist+Mono:wght@400;500;600&display=swap'>"
        "<style>" + CSS + "</style></head><body><div class=wrap>")


def head(title):
    # у CSS є «%», тож не форматуємо — лише підставляємо
    return HEAD.replace("@TITLE@", e(title))


# -------------------------------------------------------------- графіки ----

def _bars(days, series, colors, h=150, W=640, every=7):
    """Стовпчики по днях. series — список рядів однакової довжини, кладуться
    один на одного (ручні угоди + перенесені). Підказка — у <title>."""
    H, L, R, T, B = h, 30, 6, 10, 22
    n = len(days)
    tot = [sum(s[i] for s in series) for i in range(n)]
    mx = max(max(tot or [0]), 1)
    step = 1
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if mx / s <= 4:
            step = s
            break
    top = -(-mx // step) * step
    cw = (W - L - R) / n
    bw = max(2, cw - 3)
    y = lambda v: T + (H - T - B) * (1 - v / top)
    out = ['<svg class=ch viewBox="0 0 %d %d">' % (W, H)]
    v = 0
    while v <= top:
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="rgba(255,255,255,.06)"/>' % (L, W - R, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" fill="#5e5e64" font-size="10" text-anchor="end" '
                   'font-family="Geist Mono,monospace">%d</text>' % (L - 6, y(v) + 3.5, v))
        v += step
    for i, d in enumerate(days):
        x = L + i * cw + (cw - bw) / 2
        base = 0
        tip = d.strftime("%d.%m") + ": " + " · ".join(str(s[i]) for s in series)
        out.append("<g><title>%s</title>" % e(tip))
        for s, col in zip(series, colors):
            val = s[i]
            if val:
                out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"/>'
                           % (x, y(base + val), bw, y(base) - y(base + val), col))
            base += val
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="transparent"/></g>' % (x, T, bw, H - T - B))
        if i % every == (n - 1) % every:
            out.append('<text x="%.1f" y="%d" fill="#5e5e64" font-size="10" text-anchor="middle" '
                       'font-family="Geist Mono,monospace">%s</text>' % (x + bw / 2, H - 6, d.strftime("%d.%m")))
    out.append("</svg>")
    return "".join(out)


def _delta(now, prev, suffix="прошлой неделей"):
    if prev == 0 and now == 0:
        return '<div class=d>как и неделей раньше</div>'
    diff = now - prev
    cls = "up" if diff > 0 else "dn" if diff < 0 else ""
    sign = "+" if diff > 0 else ""
    return '<div class=d><span class="%s">%s%d</span> к %s</div>' % (cls, sign, diff, suffix)


def _kpi(label, value, sub=""):
    return ('<div class="card kpi"><div class=l>%s</div><div class=v>%s</div>%s</div>'
            % (e(label), value, sub))


# ------------------------------------------------------------- дані ----

def _collect():
    _inits()
    today = _today()
    now = datetime.datetime.now(datetime.timezone.utc)

    users = _q("""SELECT id, nickname, email, created_at, coalesce(ref_source,'') AS ref, ref_at,
                         telegram_id IS NOT NULL AS tg, public_journal AS pub,
                         email_confirmed_at IS NOT NULL AS mailok,
                         plan, paid_until, free_trades_used, free_trades_cap
                  FROM users ORDER BY created_at DESC""")
    bstart = billing_start()
    # Числа угод — тільки з миті запуску лімітів (limits_at): те, що людина
    # занесла до оновлення, власникам нецікаве й до ліміту не має стосунку.
    # Поруч тримаємо «за весь час» (n_all, manual_all) — його питає розділ
    # «Чим користуються»: перенесення з Notion і бектест майже в усіх були
    # ще до викладки, і від відсічки вони б занулились.
    cut, cargs = _since()
    tr = {r["user_id"]: r for r in _q("""
        SELECT user_id,
               count(*) FILTER (WHERE true{0}) AS n,
               count(*) FILTER (WHERE import_id = '' AND notion_id = ''{0}) AS manual,
               count(*) FILTER (WHERE created_at >= now() - interval '7 days'{0}) AS d7,
               count(*) AS n_all,
               count(*) FILTER (WHERE import_id = '' AND notion_id = '') AS manual_all,
               count(*) FILTER (WHERE "kind" = 'bt') AS bt,
               max(created_at) AS last_at
        FROM trades GROUP BY user_id""".format(cut), (cargs * 3) or None)}
    notes = {r["user_id"]: r for r in _q("""
        SELECT user_id,
               count(*) FILTER (WHERE CASE WHEN jsonb_typeof(data->'assets') = 'array'
                                           THEN jsonb_array_length(data->'assets') ELSE 0 END > 0) AS n,
               max(updated_at) AS last_at
        FROM day_notes GROUP BY user_id""")}
    has_ts = {r["user_id"] for r in _q("SELECT user_id FROM strategies WHERE data <> '{}'::jsonb")}
    shares = {r["user_id"]: r for r in _q("""
        SELECT user_id, count(*) AS n, coalesce(sum(views),0) AS views
        FROM share_stats WHERE user_id IS NOT NULL GROUP BY user_id""")}
    idents = {r["user_id"]: r["p"] for r in _q(
        "SELECT user_id, string_agg(DISTINCT provider, ',') AS p FROM identities GROUP BY user_id")}
    accs = {r["user_id"]: r["n"] for r in _q("SELECT user_id, count(*) AS n FROM accounts GROUP BY user_id")}

    # дні, коли людина щось записала: угоду чи розбір дня
    act = {}
    for r in _q("""SELECT user_id, (ts AT TIME ZONE 'Europe/Kyiv')::date AS d FROM (
                       SELECT user_id, created_at AS ts FROM trades
                       UNION ALL SELECT user_id, updated_at FROM day_notes) a
                   GROUP BY 1, 2"""):
        act.setdefault(r["user_id"], set()).add(r["d"])

    tday = {r["d"]: r for r in _q("""
        SELECT (created_at AT TIME ZONE 'Europe/Kyiv')::date AS d, count(*) AS n,
               count(*) FILTER (WHERE import_id = '' AND notion_id = '') AS manual
        FROM trades WHERE created_at >= now() - interval '40 days' GROUP BY 1""")}
    kinds = _q("""SELECT kind, count(*) AS n, coalesce(sum(views),0) AS views,
                         count(*) FILTER (WHERE created >= extract(epoch from now()) - 7*86400) AS d7,
                         count(*) FILTER (WHERE created >= extract(epoch from now()) - 14*86400
                                            AND created < extract(epoch from now()) - 7*86400) AS p7
                  FROM share_stats GROUP BY kind ORDER BY n DESC""")

    people = []
    for u in users:
        t = tr.get(u["id"]) or {}
        nt = notes.get(u["id"]) or {}
        days = act.get(u["id"]) or set()
        last = max(days) if days else None
        since = (today - last).days if last else None
        n = t.get("n") or 0
        if not n and not (nt.get("n") or 0):
            st = "new"
        elif since is not None and since <= 7:
            st = "active"
        elif since is not None and since <= 21:
            st = "cool"
        else:
            st = "sleep"
        created = _kdate(u["created_at"])
        people.append({
            "id": u["id"], "nick": u["nickname"], "email": u["email"] or "",
            "reg": created.isoformat() if created else "", "regd": (today - created).days if created else 999,
            "ref": u["ref"], "tg": bool(u["tg"]), "pub": bool(u["pub"]), "mail": bool(u["mailok"]),
            "n": n, "manual": t.get("manual") or 0, "bt": t.get("bt") or 0, "d7": t.get("d7") or 0,
            "nall": t.get("n_all") or 0, "mall": t.get("manual_all") or 0,
            # той самий лічильник, яким журнал закриває запис (billing)
            "free": u["free_trades_used"] or 0,
            "cap": u["free_trades_cap"] or FREE_LIMIT,
            "sub": _sub(u, now),
            "notes": nt.get("n") or 0, "ts": u["id"] in has_ts,
            "sh": (shares.get(u["id"]) or {}).get("n") or 0, "views": (shares.get(u["id"]) or {}).get("views") or 0,
            "idp": idents.get(u["id"]) or "", "acc": accs.get(u["id"]) or 0,
            "last": last.isoformat() if last else "", "since": since, "st": st,
            "days7": sum(1 for d in days if (today - d).days < 7),
            "_days": days, "_ref_at": u["ref_at"],
        })
    return {"today": today, "now": now, "people": people, "tday": tday, "kinds": kinds, "bstart": bstart}


# ----------------------------------------------------------- розділи ----

def _kpis(D):
    today, P = D["today"], D["people"]
    in_w = lambda d, a, b: d is not None and a <= (today - d).days <= b
    new7 = sum(1 for p in P if p["regd"] <= 6)
    new_p = sum(1 for p in P if 7 <= p["regd"] <= 13)
    a7 = sum(1 for p in P if any(in_w(d, 0, 6) for d in p["_days"]))
    a7p = sum(1 for p in P if any(in_w(d, 7, 13) for d in p["_days"]))
    a30 = sum(1 for p in P if any(in_w(d, 0, 29) for d in p["_days"]))
    tm7 = sum((D["tday"].get(today - datetime.timedelta(days=i)) or {}).get("manual") or 0 for i in range(7))
    tm7p = sum((D["tday"].get(today - datetime.timedelta(days=i)) or {}).get("manual") or 0 for i in range(7, 14))
    sh7 = sum(r["d7"] for r in D["kinds"])
    sh7p = sum(r["p7"] for r in D["kinds"])
    views = sum(r["views"] for r in D["kinds"])
    # Тих, хто платить, тут немає: лічильник у них стоїть, і "вперся" про
    # них неправда — так само, як у списку нижче й у фільтрі таблиці.
    dry = [p for p in P if not p["sub"]]
    lim = sum(1 for p in dry if p["free"] >= p["cap"])
    near = sum(1 for p in dry if p["cap"] - 5 <= p["free"] < p["cap"])
    bs = D.get("bstart")
    paid = {k: sum(1 for p in P if p["sub"] == k) for k in ("month", "quarter", "year", "life")}
    return ('<div class="grid kpis">'
            + _kpi("Аккаунтов", str(len(P)),
                   '<div class=d><span class=up>+%d</span> за 7 дней · неделей раньше +%d</div>' % (new7, new_p))
            + _kpi("Активны 7 дней", str(a7), _delta(a7, a7p))
            + _kpi("Активны 30 дней", str(a30), '<div class=d>%d%% от всех</div>' % (round(a30 * 100 / len(P)) if P else 0))
            + _kpi("Сделок вручную за 7 дн.", str(tm7), _delta(tm7, tm7p))
            + _kpi("Ссылок за 7 дней", str(sh7), _delta(sh7, sh7p).replace("</div>", " · %d переходов всего</div>" % views, 1))
            + _kpi("Платят сейчас", '<span class=up>%d</span>' % (paid["month"] + paid["quarter"] + paid["year"]),
                   '<div class=d>месяц %d · квартал %d · год %d · Special %d</div>'
                   % (paid["month"], paid["quarter"], paid["year"], paid["life"]))
            + _kpi("Упёрлись в лимит %d" % FREE_LIMIT, '<span class=up>%d</span>' % lim,
                   '<div class=d>ещё %d на подходе (%d–%d)%s</div>'
                   % (near, FREE_LIMIT - 5, FREE_LIMIT - 1,
                      (" · счёт с " + bs.strftime("%d.%m")) if bs else ""))
            + "</div>")


def _charts(D):
    today = D["today"]
    days = [today - datetime.timedelta(days=29 - i) for i in range(30)]
    reg = {}
    for p in D["people"]:
        if p["reg"]:
            reg[p["reg"]] = reg.get(p["reg"], 0) + 1
    act = [sum(1 for p in D["people"] if d in p["_days"]) for d in days]
    manual = [(D["tday"].get(d) or {}).get("manual") or 0 for d in days]
    imp = [((D["tday"].get(d) or {}).get("n") or 0) - m for d, m in zip(days, manual)]
    regs = [reg.get(d.isoformat(), 0) for d in days]
    lg = lambda items: '<div class=lg>' + "".join('<span><i style="background:%s"></i>%s</span>' % (c, e(t)) for c, t in items) + "</div>"
    return ('<div class="grid two">'
            '<div class=card><h2>Активные люди по дням · 30 дней</h2>' + _bars(days, [act], ["#40e094"], h=170, W=460)
            + lg([("#40e094", "записали сделку или анализ дня")]) + "</div>"
            '<div class=card><h2>Регистрации по дням · 30 дней</h2>' + _bars(days, [regs], ["#6aa8ff"], h=170, W=460)
            + lg([("#6aa8ff", "новые аккаунты")]) + "</div>"
            "</div>"
            '<div class="grid" style="margin-bottom:12px"><div class=card><h2>Сделки по дням · 30 дней</h2>'
            + _bars(days, [manual, imp], ["#40e094", "rgba(255,255,255,.18)"], h=170, W=1100)
            + lg([("#40e094", "вручную и через бота"), ("rgba(255,255,255,.18)", "перенесены из Notion / Excel")])
            + "</div></div>")


def _funnel(D):
    P = D["people"]
    total = len(P) or 1
    steps = [
        ("Зарегистрировались", len(P)),
        ("Записали 1+ сделку", sum(1 for p in P if p["n"] >= 1)),
        ("10+ сделок", sum(1 for p in P if p["n"] >= 10)),
        ("Дошли до лимита %d" % FREE_LIMIT, sum(1 for p in P if p["free"] >= FREE_LIMIT)),
        ("Активны 7 дней", sum(1 for p in P if p["st"] == "active")),
    ]
    rows = []
    for i, (name, n) in enumerate(steps):
        prev = steps[i - 1][1] if i else n
        conv = ("%d%% от шага выше" % round(n * 100 / prev)) if 0 < i < len(steps) - 1 and prev else ""
        rows.append('<div class=st><span class=n>%s</span><span class=bar><i style="width:%.1f%%"></i></span>'
                    '<span class=v>%d<small>%d%%</small></span></div>'
                    % (e(name), n * 100 / total, n, round(n * 100 / total))
                    + ('<div class=mute style="font-size:11.5px;margin:-4px 0 2px 162px">%s</div>' % conv if conv else ""))
    return '<div class="card fn"><h2>Воронка</h2>' + "".join(rows) + "</div>"


def _features(D):
    P = D["people"]
    n = len(P) or 1
    feats = [
        ("Telegram-бот подключён", sum(1 for p in P if p["tg"])),
        ("Своя ТС заполнена", sum(1 for p in P if p["ts"])),
        ("Ведут анализ дня", sum(1 for p in P if p["notes"])),
        ("Переносили из Notion / Excel", sum(1 for p in P if p["nall"] > p["mall"])),
        ("Делились ссылкой", sum(1 for p in P if p["sh"])),
        ("Завели счета", sum(1 for p in P if p["acc"])),
        ("Бэктест", sum(1 for p in P if p["bt"])),
        ("Открытый журнал", sum(1 for p in P if p["pub"])),
        ("Вход через Google / Discord", sum(1 for p in P if p["idp"])),
        ("Почта подтверждена", sum(1 for p in P if p["mail"])),
    ]
    return ('<div class=card><h2>Чем пользуются</h2><div class=feat>'
            + "".join("<span>%s</span><span>%d<small>%d%%</small></span>" % (e(k), v, round(v * 100 / n)) for k, v in feats)
            + "</div></div>")


def _status(D):
    P = D["people"]
    c = lambda s: sum(1 for p in P if p["st"] == s)
    rows = [("active", "Активные", "запись за последние 7 дней", c("active")),
            ("cool", "Остывают", "8–21 день без записей", c("cool")),
            ("sleep", "Спят", "больше 3 недель тишины", c("sleep")),
            ("new", "Не начали", "ни одной сделки и анализа", c("new"))]
    return ('<div class=card><h2>Кто сейчас где</h2><div class=list>'
            + "".join('<a href="#people" data-f="%s"><span><span class="pill p-%s">%s</span> <small>%s</small></span>'
                      '<span style="font-family:var(--mono)">%d</span></a>' % (k, k, e(t), e(s), n) for k, t, s, n in rows)
            + "</div></div>")


def _cohorts(D):
    today = D["today"]
    cur = _monday(today)
    weeks = [cur - datetime.timedelta(weeks=7 - i) for i in range(8)]
    head = "".join("<th class=num>Нед. %d</th>" % k for k in range(8))
    body = []
    for w0 in weeks:
        coh = [p for p in D["people"] if p["reg"] and _monday(datetime.date.fromisoformat(p["reg"])) == w0]
        if not coh:
            continue
        cells = []
        for k in range(8):
            wk = w0 + datetime.timedelta(weeks=k)
            if wk > cur:
                cells.append("<td></td>")
                continue
            end = wk + datetime.timedelta(days=6)
            n = sum(1 for p in coh if any(wk <= d <= end for d in p["_days"]))
            pct = n * 100 / len(coh)
            a = 0.06 + 0.55 * pct / 100
            cells.append('<td style="background:rgba(64,224,148,%.2f);color:%s" title="%d из %d">%d%%</td>'
                         % (a, "#06130d" if pct >= 55 else "var(--text)", n, len(coh), round(pct)))
        body.append('<tr><td class=lb>%s <span class=mute>· %d</span></td>%s</tr>'
                    % (w0.strftime("%d.%m") + "–" + (w0 + datetime.timedelta(days=6)).strftime("%d.%m"), len(coh), "".join(cells)))
    return ('<div class=card style="margin-bottom:12px"><h2>Возвращаются ли · по неделям регистрации</h2>'
            '<p class=mute style="margin:-4px 0 12px;font-size:12.5px">Строка — люди, зарегистрированные в эту неделю. '
            'Клетка — какая доля из них что-то записала через N недель. Неделя 0 — неделя регистрации.</p>'
            '<div class=tw><table class=coh><tr><th>Неделя регистрации</th>' + head + "</tr>"
            + ("".join(body) or '<tr><td class=empty colspan=9>Пока пусто</td></tr>') + "</table></div></div>")


def _partners(D, titles, refs=()):
    P = D["people"]
    today = D["today"]
    # усі мітки, навіть без людей: інакше нове посилання (соцмережі) не
    # видно зовсім, поки за ним хтось не зареєструється
    groups = {r: [] for r in refs}
    for p in P:
        groups.setdefault(p["ref"], []).append(p)
    vis = {r["ref"]: r for r in _q("""SELECT ref, sum(n) AS n,
                                             sum(n) FILTER (WHERE day >= (now() AT TIME ZONE 'Europe/Kyiv')::date - 29) AS d30
                                      FROM ref_visits GROUP BY ref""")}
    rows = []
    for ref, ps in sorted(groups.items(), key=lambda kv: (kv[0] == "", -len(kv[1]))):
        v = vis.get(ref) or {}
        clicks = ("%d <span class=mute>· +%d</span>" % (v.get("n") or 0, v.get("d30") or 0)) if ref else "<span class=mute>—</span>"
        n30 = sum(1 for p in ps if p["_ref_at"] and (today - _kdate(p["_ref_at"])).days < 30) if ref else \
            sum(1 for p in ps if p["regd"] < 30)
        rows.append("<tr><td>%s</td><td class=num>%s</td><td class=num>%d</td><td class=num>%s</td><td class=num>%d</td>"
                    "<td class=num>%d</td><td class=num>%d</td></tr>" % (
                        e(titles.get(ref, ref) if ref else "Без метки"), clicks, len(ps), ("+%d" % n30) if n30 else "0",
                        sum(1 for p in ps if p["n"]), sum(1 for p in ps if p["st"] == "active"),
                        sum(1 for p in ps if p["free"] >= FREE_LIMIT)))
    return ('<div class=card><h2>Партнёры и метки</h2><div class=tw><table>'
            "<tr><th>Метка</th><th class=num>Переходов · 30 дн.</th><th class=num>Людей</th><th class=num>30 дн.</th>"
            "<th class=num>Со сделками</th><th class=num>Активны</th><th class=num>Лимит 30+</th></tr>" + "".join(rows)
            + "</table></div><p class=mute style=\"margin:10px 0 0;font-size:12px\">Переходы — нажатия на короткие "
              "ссылки /bs, /soc, считаются с 27.09.2026. Люди — кто зарегистрировался с этой меткой.</p></div>")


def _links(D, kind_ru):
    K = D["kinds"]
    rows = "".join("<tr><td>%s</td><td class=num>%d</td><td class=num>%s</td><td class=num>%d</td></tr>"
                   % (e(kind_ru.get(r["kind"], r["kind"] or "—")), r["n"], ("+%d" % r["d7"]) if r["d7"] else "0", r["views"])
                   for r in K)
    top = sorted([p for p in D["people"] if p["sh"]], key=lambda p: (-p["sh"], -p["views"]))[:6]
    tl = "".join('<a href="/admin/u/%s"><span class=nm>%s</span><span class=mute>%d %s · %d перех.</span></a>'
                 % (e(p["nick"]), e(p["nick"]), p["sh"], _plural(p["sh"], "ссылка", "ссылки", "ссылок"), p["views"]) for p in top)
    return ('<div class=card><h2>Ссылки «поделиться»</h2><div class=tw><table>'
            "<tr><th>Что</th><th class=num>Всего</th><th class=num>7 дн.</th><th class=num>Переходов</th></tr>"
            + (rows or '<tr><td class=empty colspan=4>Пока никто не делился</td></tr>')
            + '</table></div><h2 style="margin-top:16px">Кто делится чаще</h2><div class=list>'
            + (tl or '<div class=empty>—</div>') + "</div></div>")


def _watch(D):
    P = D["people"]
    top = sorted([p for p in P if p["days7"]], key=lambda p: (-p["days7"], -p["d7"]))[:8]
    idle = [p for p in P if p["st"] == "new" and p["regd"] <= 14][:10]
    lim = sorted([p for p in P if not p["sub"] and p["free"] >= p["cap"] - 5], key=lambda p: -p["free"])[:10]
    li = lambda p, right: '<a href="/admin/u/%s"><span class=nm>%s <small>%s</small></span><span class=mute>%s</span></a>' % (
        e(p["nick"]), e(p["nick"]), e(p["email"]), right)
    return ('<div class="grid three">'
            '<div class=card><h2>Самые активные на неделе</h2><div class=list>'
            + ("".join(li(p, "%d %s · %d сд." % (p["days7"], _plural(p["days7"], "день", "дня", "дней"), p["d7"])) for p in top)
               or '<div class=empty>На этой неделе тихо</div>') + "</div></div>"
            '<div class=card><h2>Зарегистрировались и не начали</h2><div class=list>'
            + ("".join(li(p, _ago(p["regd"])) for p in idle) or '<div class=empty>Все новенькие что-то записали</div>')
            + "</div></div>"
            '<div class=card><h2>Ближе всех к подписке</h2><div class=list>'
            + ("".join(li(p, '<span class="%s">%d / %d</span>' % ("up" if p["free"] >= p["cap"] else "be", p["free"], p["cap"])) for p in lim)
               or '<div class=empty>%s</div>' % ("Пока никто не подошёл к %d сделкам" % FREE_LIMIT))
            + "</div></div>"
            "</div>")


def _people(D, titles, query):
    rows = [{k: v for k, v in p.items() if not k.startswith("_")} for p in D["people"]]
    # Колонка рахує угоди з запуску лімітів — підписуємо, щоб число поряд з
    # «5 / 20» не читалось як весь журнал.
    since_th = ('<br><span class=mute style="font-weight:400;font-size:11px">с %s</span>'
                % D["bstart"].strftime("%d.%m")) if D["bstart"] else ""
    for r in rows:
        r["refT"] = titles.get(r["ref"], r["ref"]) if r["ref"] else ""
    # Усе, що їде всередину <script>, проганяємо через один хелпер:
    # json.dumps не чіпає "</", а саме ним рядок закрив би тег — далі
    # браузер читав би вміст як розмітку. Пошук (?q=) сюди приходить
    # просто з адреси, тож посилання на /admin?q=... інакше стало б
    # готовою пасткою для того, хто цю панель відкриє.
    data = _js(rows)
    return ('<div class=card id=people><h2>Все люди</h2><div class=chips id=chips></div>'
            '<div class=tw><table id=pt><thead><tr>'
            '<th class=s data-k=nick>Ник</th><th class="s" data-k=st>Статус</th><th class="s num" data-k=n>Сделок'
            + since_th + '</th>'
            '<th class="s num" data-k=d7>7 дн.</th><th class="s num" data-k=notes>Анализ</th>'
            '<th class="s num" data-k=since>Активность</th><th class="s num" data-k=regd>Регистрация</th>'
            '<th class="s" data-k=sub>Тариф</th><th>Метка</th><th>Есть</th></tr></thead><tbody></tbody></table></div>'
            '<p class=mute id=pcount style="margin:10px 0 0;font-size:12.5px"></p></div>'
            "<script>const P=" + data + ";const Q=" + _js(query or "") + ";" + PEOPLE_JS + "</script>")


PEOPLE_JS = r"""
const ST={active:['Активный','p-active'],cool:['Остывает','p-cool'],sleep:['Спит','p-sleep'],new:['Не начал','p-new']};
const F=[['all','Все',()=>true],['active','Активные',p=>p.st==='active'],['cool','Остывают',p=>p.st==='cool'],
['sleep','Спят',p=>p.st==='sleep'],['new','Не начали',p=>p.st==='new'],['fresh','Новые 7 дн.',p=>p.regd<=6],
['limit','Упёрлись в лимит',p=>!p.sub&&p.free>=p.cap],['paid','Платят',p=>['month','quarter','year'].includes(p.sub)],
['special','Special',p=>p.sub==='life'],['tg','С Telegram',p=>p.tg]];
const SUB={month:'Месяц',quarter:'Квартал',year:'Год',life:'Special'};
let f='all',k='regd',dir=1,q=(Q||'').toLowerCase();
const s=document.getElementById('q');if(s){s.value=Q||'';s.addEventListener('input',()=>{q=s.value.trim().toLowerCase();draw();});}
const esc=x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ago=d=>d==null?'—':d===0?'сегодня':d===1?'вчера':d+' дн.';
function chips(){document.getElementById('chips').innerHTML=F.map(([id,t,fn])=>
 '<button class="chip'+(f===id?' on':'')+'" data-f="'+id+'">'+t+'<b>'+P.filter(fn).length+'</b></button>').join('');}
function draw(){
 const fn=F.find(x=>x[0]===f)[2];
 let L=P.filter(fn).filter(p=>!q||(p.nick+' '+p.email).toLowerCase().includes(q));
 L.sort((a,b)=>{let x=a[k],y=b[k];if(k==='since'){x=x==null?1e9:x;y=y==null?1e9:y;}
  if(typeof x==='string')return x.localeCompare(y)*dir;return ((x||0)-(y||0))*dir;});
 document.querySelector('#pt tbody').innerHTML=L.map(p=>'<tr class=lnk data-n="'+esc(p.nick)+'"><td><b>'+esc(p.nick)+
  '</b><br><span class=mute style="font-size:12px">'+esc(p.email)+'</span></td><td><span class="pill '+ST[p.st][1]+'">'+ST[p.st][0]+
  '</span></td><td class=num>'+p.n+(p.n>p.manual?'<br><span class=mute style="font-size:11px">'+p.manual+' вручную</span>':'')+
  '</td><td class=num>'+(p.d7||'<span class=mute>0</span>')+'</td><td class=num>'+(p.notes||'<span class=mute>0</span>')+
  '</td><td class=num>'+ago(p.since)+'</td><td class=num>'+p.reg.split('-').reverse().join('.')+
  '</td><td>'+(p.sub?'<span class="pill '+(p.sub==='life'?'p-cool':'p-active')+'">'+SUB[p.sub]+'</span>'
   :'<span class=mute>'+p.free+' / '+p.cap+'</span>')+
  '</td><td>'+(p.refT?'<span class=tag>'+esc(p.refT)+'</span>':'<span class=mute>—</span>')+'</td><td>'+
  (p.tg?'<span class=tag>TG</span>':'')+(p.ts?'<span class=tag>ТС</span>':'')+(p.sh?'<span class=tag>🔗'+p.sh+'</span>':'')+
  (p.acc?'<span class=tag>счета</span>':'')+'</td></tr>').join('')||'<tr><td colspan=10 class=empty>Никого</td></tr>';
 document.getElementById('pcount').textContent='Показано '+L.length+' из '+P.length;
 document.querySelectorAll('#pt th.s').forEach(th=>th.classList.toggle('on',th.dataset.k===k));
}
document.getElementById('chips').addEventListener('click',ev=>{const b=ev.target.closest('.chip');if(!b)return;f=b.dataset.f;chips();draw();});
document.querySelectorAll('#pt th.s').forEach(th=>th.onclick=()=>{if(k===th.dataset.k)dir=-dir;else{k=th.dataset.k;dir=(k==='nick'||k==='since'||k==='regd')?1:-1;}draw();});
document.querySelector('#pt tbody').addEventListener('click',ev=>{const tr=ev.target.closest('tr.lnk');if(tr)location.href='/admin/u/'+encodeURIComponent(tr.dataset.n);});
document.querySelectorAll('[data-f]').forEach(a=>{if(a.tagName==='A')a.addEventListener('click',()=>{f=a.dataset.f;chips();draw();});});
chips();draw();
"""


def dashboard(query, titles, kind_ru, refs=()):
    D = _collect()
    stamp = datetime.datetime.now(KYIV).strftime("%d.%m.%Y %H:%M")
    return (head("StatsAI · админка")
            + '<div class=top><div class=brand>Stats<b>AI</b><small>админка</small></div><span class=sp></span>'
              '<label class=search><svg width=15 height=15 viewBox="0 0 24 24" fill=none><circle cx=11 cy=11 r=7 '
              'stroke=currentColor stroke-width=2 /><path d="M20 20l-3.5-3.5" stroke=currentColor stroke-width=2 '
              'stroke-linecap=round /></svg><input id=q placeholder="Ник или почта" autocomplete=off></label>'
              '<span class=stamp>обновлено ' + stamp + "</span></div>"
            + _kpis(D) + _charts(D)
            + '<div class="grid three">' + _funnel(D) + _features(D) + _status(D) + "</div>"
            + _cohorts(D) + _watch(D)
            + '<div class="grid two">' + _partners(D, titles, refs) + _links(D, kind_ru) + "</div>"
            + _people(D, titles, query)
            + "</div></body></html>")


# -------------------------------------------------- картка людини ----

def user_card(u, titles, kind_ru, refs, billing_html=""):
    _inits()
    today = _today()
    uid = u["id"]
    one = lambda sql: (_q(sql, (uid,)) or [{}])[0]
    bstart = billing_start()
    # Угоди рахуємо з миті запуску лімітів (_since): записане до оновлення
    # власникам нецікаве. Окремо беремо «за весь час» — лише на те, що не
    # може від відсічки зникнути: слід останнього запису (бо з нього статус
    # «Активний / Спить») і бектест.
    cut, cargs = _since()
    t = (_q("""SELECT count(*) AS n, count(*) FILTER (WHERE result='Skip') AS skips,
                      count(*) FILTER (WHERE import_id = '' AND notion_id = '') AS manual,
                      min("date") AS first, max("date") AS last,
                      count(*) FILTER (WHERE created_at >= now() - interval '7 days') AS d7,
                      count(*) FILTER (WHERE created_at >= now() - interval '30 days') AS d30,
                      count(DISTINCT left("date", 10)) AS days
               FROM trades WHERE user_id=%s""" + cut, (uid,) + cargs) or [{}])[0]
    tall = (_q("""SELECT count(*) AS n, max(created_at) AS last_at,
                         count(*) FILTER (WHERE "kind" = 'bt') AS bt
                  FROM trades WHERE user_id=%s""", (uid,)) or [{}])[0]
    pairs = _q("""SELECT "pair", count(*) AS n FROM trades WHERE user_id=%s AND "pair"<>''""" + cut
               + ' GROUP BY 1 ORDER BY n DESC LIMIT 6', (uid,) + cargs)
    weeks = {r["w"]: r for r in _q("""
        SELECT date_trunc('week', created_at AT TIME ZONE 'Europe/Kyiv')::date AS w, count(*) AS n,
               count(*) FILTER (WHERE import_id = '' AND notion_id = '') AS manual
        FROM trades WHERE user_id=%s AND created_at >= now() - interval '100 days' GROUP BY 1""", (uid,))}
    nt = one("""SELECT count(*) FILTER (WHERE CASE WHEN jsonb_typeof(data->'assets') = 'array'
                                              THEN jsonb_array_length(data->'assets') ELSE 0 END > 0) AS n,
                       max(updated_at) AS last_at FROM day_notes WHERE user_id=%s""")
    sh = one("SELECT count(*) AS n, coalesce(sum(views),0) AS views, max(created) AS last FROM share_stats WHERE user_id=%s")
    kinds = _q("SELECT kind, count(*) AS n, coalesce(sum(views),0) AS views FROM share_stats WHERE user_id=%s "
               "GROUP BY kind ORDER BY n DESC", (uid,))
    idp = ", ".join(r["provider"].capitalize() for r in _q("SELECT DISTINCT provider FROM identities WHERE user_id=%s", (uid,)))
    accs = _q("SELECT name, firm, kind FROM accounts WHERE user_id=%s ORDER BY id", (uid,))
    try:
        import ts_store
        ts = ts_store.get(uid)
    except Exception:
        ts = None

    lasts = [x for x in (tall.get("last_at"), nt.get("last_at")) if x]
    last = _kdate(max(lasts)) if lasts else None
    since = (today - last).days if last else None
    if not (tall.get("n") or 0) and not (nt.get("n") or 0):
        st = ("new", "Не начал")
    elif since is not None and since <= 7:
        st = ("active", "Активный")
    elif since is not None and since <= 21:
        st = ("cool", "Остывает")
    else:
        st = ("sleep", "Спит")
    dt = lambda v: _kdate(v).strftime("%d.%m.%Y") if v else "—"

    wk = [_monday(today) - datetime.timedelta(weeks=11 - i) for i in range(12)]
    man = [(weeks.get(w) or {}).get("manual") or 0 for w in wk]
    imp = [((weeks.get(w) or {}).get("n") or 0) - m for w, m in zip(wk, man)]

    ts_line = "нет"
    if ts:
        bits = []
        if ts.get("assets"):
            bits.append("активы: " + ", ".join(str(x) for x in ts["assets"][:6]))
        if ts.get("models"):
            bits.append("моделей: %d" % len(ts["models"]))
        if ts.get("updated"):
            bits.append("обновлена " + str(ts["updated"]))
        ts_line = " · ".join(bits) or "есть"
    manual = t.get("manual") or 0
    free = u.get("free_trades_used") or 0
    cap = u.get("free_trades_cap") or FREE_LIMIT
    nick_js = _js(u["nickname"])
    kv = lambda k, v: "<span>%s</span><span>%s</span>" % (e(k), v)

    return (head("StatsAI · " + u["nickname"])
        + '<div class=top><a class=back href="/admin">← все цифры</a><span class=sp></span>'
          '<span class=stamp>id ' + str(uid) + "</span></div>"
        + '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px">'
          '<div style="font-size:26px;font-weight:700;letter-spacing:-.02em">' + e(u["nickname"]) + "</div>"
          '<span class="pill p-' + st[0] + '">' + st[1] + "</span>"
          '<span class=mute>' + e(u["email"]) + "</span></div>"
        + _access(u, free)
        + '<div class="grid kpis">'
        + _kpi("Сделок с " + bstart.strftime("%d.%m.%Y") if bstart else "Сделок всего",
               str(t.get("n") or 0), '<div class=d>%d вручную · %d скипов</div>' % (manual, t.get("skips") or 0))
        + (_kpi("Лимит сделок", '<span class=mute>подписка</span>',
                '<div class=d>%d из %d · пока платит, не тратится</div>' % (free, cap))
           if _sub(u, datetime.datetime.now(datetime.timezone.utc)) else
           _kpi("До лимита %d" % cap,
                '<span class="%s">%d / %d</span>'
                % ("up" if free >= cap else "be" if free >= cap - 5 else "", min(free, 999), cap),
                '<div class=d>%s%s</div>'
                % ("упёрся в бесплатный лимит" if free >= cap else "ещё %d бесплатных" % (cap - free),
                   (" · счёт с " + bstart.strftime("%d.%m.%Y")) if bstart else "")))
        + _kpi("Торговых дней", str(t.get("days") or 0), '<div class=d>%s — %s</div>' % (str(t.get("first") or "—")[:10], str(t.get("last") or "—")[:10]))
        + _kpi("Сделок за 7 / 30 дн.", "%d / %d" % (t.get("d7") or 0, t.get("d30") or 0), "")
        + _kpi("Анализов дня", str(nt.get("n") or 0), '<div class=d>последний %s</div>' % dt(nt.get("last_at")))
        + _kpi("Последняя активность", e(_ago(since)), '<div class=d>%s</div>' % (last.strftime("%d.%m.%Y") if last else "ничего не записал"))
        + "</div>"
        + '<div class="grid two"><div class=card><h2>Сделки по неделям · 12 недель</h2>'
        + _bars(wk, [man, imp], ["#40e094", "rgba(255,255,255,.18)"], h=180, W=460, every=3)
        + '<div class=lg><span><i style="background:#40e094"></i>вручную и через бота</span>'
          '<span><i style="background:rgba(255,255,255,.18)"></i>перенесены</span></div></div>'
        + '<div class=card><h2>Аккаунт</h2><div class=kv>'
        + kv("Зарегистрирован", dt(u["created_at"]))
        + kv("Почта подтверждена", dt(u["email_confirmed_at"]))
        + kv("Telegram", e(("@" + u["telegram_username"]) if u["telegram_username"] else ("да" if u["telegram_id"] else "нет")))
        + kv("Вход через", e(idp or "почта и пароль"))
        + kv("Открытый журнал", ('<a href="/u/%s" style="color:var(--acc)">/u/%s</a>' % (e(u["nickname"]), e(u["nickname"])))
             if u["public_journal"] else "нет")
        + kv("Своя ТС", e(ts_line))
        + kv("Счета", e(", ".join((a["name"] or a["firm"] or a["kind"]) for a in accs) or "нет"))
        + kv("Бэктест", "%d сделок" % (tall.get("bt") or 0) if tall.get("bt") else "нет")
        + kv("Инструменты", e(", ".join("%s (%d)" % (r["pair"], r["n"]) for r in pairs) or "—"))
        + "</div></div></div>"
        + '<div class="grid two"><div class=card><h2>Метка партнёра</h2>'
          '<p style="margin:0 0 12px">' + (e(titles.get(u["ref_source"], u["ref_source"])) + ' <span class=mute>с ' + dt(u["ref_at"]) + "</span>"
                                            if u["ref_source"] else '<span class=mute>без метки</span>') + "</p>"
          '<div style="display:flex;gap:6px;flex-wrap:wrap">'
        + "".join('<button class="btn refb%s" data-r="%s">%s</button>' % (" on" if (u["ref_source"] or "") == k else "", e(k), e(v))
                  for k, v in [("", "без метки")] + [(r, titles.get(r, r)) for r in refs])
        + ' <span id=refmsg class=mute></span></div></div>'
        + '<div class=card><h2>Ссылки «поделиться»</h2><div class=kv>'
        + kv("Поделился", str(sh.get("n") or 0)) + kv("Переходов", str(sh.get("views") or 0))
        + kv("Последняя", datetime.datetime.fromtimestamp(sh["last"]).strftime("%d.%m.%Y") if sh.get("last") else "—")
        + "".join(kv("· " + kind_ru.get(r["kind"], r["kind"]), "%d · %d перех." % (r["n"], r["views"])) for r in kinds)
        + "</div></div></div>"
        + billing_html
        + '<div class="card danger" style="margin-top:12px"><h2>Опасная зона</h2>'
          '<p class=mute style="margin:0 0 10px;font-size:13px">Удаляет аккаунт и всё, что в нём: сделки, ТС, анализ дня, '
          'настройки, ссылки и скриншоты. Отменить нельзя. Чтобы подтвердить, впишите ник точно так: <b style="color:var(--text)">'
        + e(u["nickname"]) + "</b></p>"
          '<div style="display:flex;gap:8px;flex-wrap:wrap"><input id=cf placeholder="' + e(u["nickname"]) + '" '
          'style="flex:1;min-width:200px;padding:9px 12px;border-radius:9px;border:1px solid var(--line);background:var(--card);'
          'color:var(--text);font:inherit"><button id=go class="btn go">Удалить аккаунт</button></div><p id=msg class=mute></p></div>'
        + "<script>"
          "document.querySelectorAll('.refb').forEach(b=>b.onclick=async()=>{refmsg.textContent='…';"
          "const r=await fetch('/api/admin/set-ref',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({nick:" + nick_js + ",ref:b.dataset.r})});const d=await r.json().catch(()=>({}));"
          "refmsg.textContent=r.ok?'готово':(d.error||('ошибка '+r.status));if(r.ok)setTimeout(()=>location.reload(),600);});"
          "go.onclick=async()=>{if(!confirm('Удалить аккаунт '+" + nick_js + "+'? Отменить нельзя.'))return;"
          "go.disabled=true;msg.textContent='Удаляю…';const r=await fetch('/api/admin/delete-user',{method:'POST',"
          "headers:{'Content-Type':'application/json'},body:JSON.stringify({nick:" + nick_js + ",confirm:cf.value})});"
          "const d=await r.json().catch(()=>({}));if(r.ok){msg.textContent='Удалён. Файлов убрано: '+d.files;"
          "setTimeout(()=>location.href='/admin',1200);}else{go.disabled=false;msg.textContent=d.error||('Ошибка '+r.status);}};"
          "</script></div></body></html>")


def not_found(nick):
    return (head("StatsAI · нет такого")
            + '<div class=top><a class=back href="/admin">← все цифры</a></div>'
              '<div class=card><h2>Нет такого пользователя</h2><p>' + e(nick) + "</p></div></div></body></html>")


if __name__ == "__main__":
    # самоперевірка частин без бази
    d0 = datetime.date(2026, 9, 1)
    days = [d0 + datetime.timedelta(days=i) for i in range(30)]
    svg = _bars(days, [[i % 4 for i in range(30)], [1] * 30], ["#40e094", "#333"])
    assert svg.startswith("<svg") and svg.count("<g>") == 30
    assert _plural(1, "a", "b", "c") == "a" and _plural(3, "a", "b", "c") == "b" and _plural(11, "a", "b", "c") == "c"
    assert _monday(datetime.date(2026, 9, 27)) == datetime.date(2026, 9, 21)
    assert "up" in _delta(5, 2) and "dn" in _delta(1, 4)
    print("ok")
