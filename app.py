# -*- coding: utf-8 -*-
"""
Trading Journal — сервер журнала.
Только стандартная библиотека Python плюс драйвер Postgres. Запуск:  python app.py
Данные: Postgres (DATABASE_URL), скриншоты: data/screenshots/
"""
import base64
import datetime
import gzip
import hmac
import html as _html
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from urllib.parse import urlparse, unquote, parse_qs

import antifraud
import assistant
import delete_ai
import auth
import backup
import billing
import creem
import crypto_pay
import http.cookies
import config
import db
import emotions
import filestore
import share_store
import admin_page
import llm
from psycopg.types.json import Jsonb

import notion_import as notion
import notion_public as npub
import authmail
import oauth
import ratelimit
import seclog
import accounts_store
import notes_store
import mailout
import bt_journals_store
import day_store
import tg_api
import tidy
import twofa
import ts_check
import ts_edit
import ts_notion
import ts_store
import calendar_feed
import tv_calendar
from calendar_feed import calendar_events, event_history
from zoneinfo import ZoneInfo

ROOT   = config.ROOT
STATIC = os.path.join(ROOT, "static")
DATA   = config.DATA_DIR
SHOTS  = os.path.join(DATA, "screenshots")
PORT   = config.PORT

os.makedirs(SHOTS, exist_ok=True)

_id_counter = int(time.time() * 1000)
_id_lock = threading.Lock()


def new_id():
    global _id_counter
    with _id_lock:
        _id_counter += 1
        return "t" + str(_id_counter)


# Що сторінці дозволено вантажити. Другий рубіж проти XSS: навіть якщо
# чужий текст колись просочиться в HTML, підвантажити скрипт зі свого
# домену йому не дадуть, а <base> і <object> закриті зовсім.
#
# 'unsafe-inline' у script-src поки обов'язковий: сторінки журналу тримають
# обробники прямо в розмітці (onclick=...) і вбудовані <script>. Прибрати
# його можна тільки разом із ними — окрема велика робота.
#
# Шрифти йдуть із Google Fonts, картинки бувають data: (аватарка в формі)
# і blob: (щойно вибраний файл) — тому вони в списку.
CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'self'",
    "form-action 'self'",
    "img-src 'self' data: blob:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "script-src 'self' 'unsafe-inline'",
    "connect-src 'self'",
    "frame-src 'self'",
])


def html_escape(x):
    """Текст людини всередину HTML. Разом із лапками: підставляємо і в
    тіло сторінки, і в content="..." мета-тегів."""
    return _html.escape("" if x is None else str(x), quote=True)


DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)
# Один скрін — не більше 8 МБ, як і в разовій заливці. Браузер і так
# пережимає картинку до ~1 МБ, але сервер цього не бачить: прямий запит
# в обхід сторінки міг покласти в базу що завгодно.
SHOT_MAX = 8 * 1024 * 1024


NOTE_MAX = 2000            # підпис під скріном: думка, а не пара слів
ASK_LIMIT = 20             # питань до помічника за хвилину на людину


def shot_note(s):
    """Підпис під скріном — чому на цьому таймфреймі видно те, що видно."""
    return str(s.get("note") or "").strip()[:NOTE_MAX]


def save_screenshots(trade, uid, old=None):
    """Скриншоты с base64-данными сохраняем в файлы; уже сохранённые оставляем.

    Уже сохранённый ({"file": ім'я}) приймаємо, лише якщо він і так цієї
    людини: був у цій угоді (old) або в іншій її угоді. Інакше, знаючи ім'я
    чужого файлу (його видно у відкритому журналі й у посиланнях), можна
    було вписати його собі — і дивитись чужий скрін, а видаливши угоду,
    стерти його з бази. Чужі імена просто відкидаємо, мовчки.

    Спершу перевіряємо всі, потім пишемо: якщо третій скрін завеликий,
    перші два не мають лишитись у базі сиротами від незбереженої угоди.
    Не пройшло — filestore.ShotError, і угода не зберігається зовсім:
    мовчки загубити скрін гірше, ніж сказати про це."""
    ready = []
    mine = {s.get("file") for s in (old or {}).get("screenshots") or [] if s.get("file")}
    shots = trade.get("screenshots") or []
    for i, s in enumerate(shots):
        tf = re.sub(r"[^0-9A-Za-zА-Яа-я]", "", str(s.get("tf") or "img"))[:8] or "img"
        if s.get("data"):
            m = DATAURL_RE.match(s["data"])
            if not m:
                continue
            try:
                raw = base64.b64decode(m.group(2))
            except Exception:
                continue
            if len(raw) > SHOT_MAX:
                raise filestore.ShotError("завеликий скріншот", "too_big", 413)
            # Розширення — з самих байтів: слово в data-URL пише клієнт.
            ext = filestore.kind(raw)
            if not ext:
                raise filestore.ShotError("файл не схожий на картинку", "bad_image")
            name = "%s_%d_%s.%s" % (trade["id"], int(time.time() * 1000) % 100000000 + i, tf, ext)
            ready.append((s, name, raw))
        elif s.get("file"):
            name = str(s["file"])
            if name in mine or db.owns_screenshot(uid, name):
                ready.append((s, name, None))
    out = []
    for s, name, raw in ready:
        if raw is not None:
            keep_file(name, raw)
        out.append({"tf": s.get("tf") or "", "file": name, "note": shot_note(s)})
    trade["screenshots"] = out


def keep_file(name, raw):
    """Картинка живёт в базе, на диске остаётся кэшем: у контейнеров на
       хостинге файловая система временная, а база — нет."""
    try:
        filestore.put(name, raw)
    except Exception:
        pass
    try:
        with open(os.path.join(SHOTS, name), "wb") as f:
            f.write(raw)
    except OSError:
        pass


def under(base, name):
    """Повний шлях до файла всередині base — або None, якщо назва виводить
    назовні.

    Одного os.path.join мало: назва, що починається з кореня ("/etc/passwd",
    "C:/..."), не додається до base, а заміняє його цілком — і запит до
    папки зі стилями діставав будь-який файл на сервері. Тому питаємо
    систему, де шлях опинився насправді, і звіряємо з коренем."""
    try:
        full = os.path.realpath(os.path.join(base, name))
    except (OSError, ValueError):
        return None
    root = os.path.realpath(base)
    return full if full == root or full.startswith(root + os.sep) else None


def shot_path(name):
    """Путь к картинке: с диска, а если его там нет — вытащив из базы."""
    path = os.path.join(SHOTS, os.path.basename(name))
    if os.path.exists(path):
        return path
    try:
        return filestore.cache(SHOTS, name)
    except Exception:
        return None


def delete_files(names):
    names = [os.path.basename(n) for n in names if n]
    # Файл, який ще згадує інша угода, не чіпаємо. Не вдалось спитати базу —
    # теж не чіпаємо: краще зайвий файл, ніж стерта чужа картинка.
    try:
        busy = db.files_in_use(names)
    except Exception:
        return
    names = [n for n in names if n not in busy]
    try:
        filestore.delete(names)
    except Exception:
        pass
    for n in names:
        p = os.path.join(SHOTS, os.path.basename(n))
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def clean_trade(body, tid):
    t = {"id": tid}
    for k in db.FIELDS:
        v = body.get(k)
        t[k] = v if v is not None else ""
    for k in db.NUM_FIELDS:
        try:
            t[k] = float(t[k]) if str(t[k]).strip() != "" else None
        except Exception:
            t[k] = None
    t["screenshots"] = body.get("screenshots") or []
    if body.get("hidden"): t["hidden"] = True
    # Реальная сделка или бэктест. Всё, кроме "bt", считаем торговлей: тип
    # приходит из браузера, и это единственное место, где он входит внутрь.
    t["kind"] = "bt" if str(body.get("kind") or "").strip() == "bt" else ""
    # стратегія — номер із ts_multi або "" (перша); у бектесті своєї немає
    t["ts"] = str(t.get("ts") or "").strip()
    if not t["ts"].isdigit() or t["ts"] == "0" or t["kind"] == "bt":
        t["ts"] = ""
    # откуда сделка приехала — нужно, чтобы повторный импорт не задвоил её
    if body.get("notion_id"): t["notion_id"] = str(body["notion_id"])[:64]
    # какое перенесение её принесло — нужно, чтобы его можно было отменить
    if body.get("import_id"): t["import_id"] = str(body["import_id"])[:32]
    return t


# ---------------------------------------------------------------------------
# Ссылки, которыми можно поделиться.
#
# Сохраняем снимок статистики файлом и выдаём короткий адрес. Снимок — уже
# посчитанные цифры, а не сами сделки: по ссылке нельзя вытащить журнал целиком.
# У каждой ссылки свой срок жизни; просроченные удаляются при обращении.
# ---------------------------------------------------------------------------
SHARE_DIR = os.path.join(DATA, "shares")
SHARE_MAX = 1536 * 1024         # рік із календарями по місяцях і угодами всередині
SHARE_TTL = share_store.TTL     # що можна вибрати в інтерфейсі; бот бере той самий список
os.makedirs(SHARE_DIR, exist_ok=True)
_share_lock = threading.Lock()


def _share_path(sid):
    return os.path.join(SHARE_DIR, sid + ".json")


def share_create(payload, ttl_key, user_id=None):
    """Знімок кладеться в базу (share_store.py): файли на хостингу зникають
    при кожному оновленні коду, а роздане посилання має жити свій термін."""
    ttl = SHARE_TTL.get(ttl_key, SHARE_TTL["7d"])
    return share_store.create(payload, ttl_key, ttl, user_id)


def share_trades(rec):
    """Усі угоди знімка: зверху, у днях календаря і в розборі дня."""
    d = rec.get("data") or {}
    for t in d.get("trades") or []:
        yield t
    for day in ((d.get("calendar") or {}).get("days") or []):
        for t in day.get("trades") or []:
            yield t
    # рік і квартал: календарі лежать по місяцях
    for m in d.get("months") or []:
        for day in ((m.get("calendar") or {}).get("days") or []):
            for t in day.get("trades") or []:
                yield t
    for a in ((d.get("review") or {}).get("assets") or []):
        for t in a.get("trades") or []:
            yield t


def share_shot_ok(rec, name):
    """Чи згадана ця картинка в самому знімку.

    Знімок бачить будь-хто, кому дали посилання, тому й картинки віддаємо
    без входу — але рівно ті, що в ньому перелічені. Підставити чуже ім'я
    не вийде: перевіряємо по списку."""
    if not name:
        return False
    d = rec.get("data") or {}
    if d.get("og") == name:              # намальований календар для превью
        return True
    # Картинки лежать не в одному місці: в угодах, у днях календаря, у
    # розборі дня. Замість переліку всіх місць просто обходимо знімок
    # цілком і шукаємо це ім'я у полях "file" — додасться новий розділ,
    # правити тут не доведеться.
    stack = [d]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("file") == name:
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


# Превью посилання в мессенджері — як у TradingView: заголовок, рядок
# цифр і картинка входу. Telegram і Discord скриптів не виконують, тому
# теги Open Graph вставляє сервер, а не сторінка.
TF_ORDER = ["1W", "1D", "4H", "2H", "1H", "30M", "15M", "5M", "3M", "1M"]


TF_MIN = {"M": 1, "H": 60, "D": 1440, "W": 10080}
TF_WORDS = {"DAILY": 1440, "DAY": 1440, "D": 1440, "WEEKLY": 10080, "WEEK": 10080, "W": 10080,
            "MONTHLY": 43200, "MONTH": 43200, "MN": 43200}


def tf_minutes(tf):
    """Таймфрейм у хвилинах: 15M, M15, 1H, H1, D, Daily, W… Незрозумілий
    підпис («Daily Screenshot», «свій») рахуємо найстаршим, а не наймолодшим:
    інакше він ліз у превью замість 1M."""
    t = re.sub(r"[^A-Z0-9]", "", str(tf or "").upper())
    if t in TF_WORDS:
        return TF_WORDS[t]
    m = re.fullmatch(r"(\d+)([MHDW])", t) or re.fullmatch(r"([MHDW])(\d+)", t)
    if not m:
        return 10 ** 9
    a, b = m.groups()
    n, u = (a, b) if a.isdigit() else (b, a)
    return int(n) * TF_MIN[u]


def tf_rank(tf):
    """Більше — молодший таймфрейм (для max())."""
    return -tf_minutes(tf)


def share_preview_shot(rec):
    """Скрін для превью — наймолодший таймфрейм першої угоди зі скрінами:
    саме на ньому видно, як набиралась позиція. У знімку тижня чи місяця
    угоди лежать у днях календаря, тому шукаємо і там."""
    for a in (((rec.get("data") or {}).get("review") or {}).get("assets") or []):
        shots = [sh for sh in (a.get("shots") or []) if sh.get("file")]
        if shots:
            return shots[0]["file"]
    for t in share_trades(rec):
        shots = [sh for sh in (t.get("shots") or []) if sh.get("file")]
        if shots:
            return max(shots, key=lambda sh: tf_rank(sh.get("tf")))["file"]
    return None


def share_og(rec, sid, base):
    d = rec.get("data") or {}
    # у заголовку спершу кажемо, що це за посилання: «Зведення за місяць».
    # Раніше стояла сама назва періоду, і зі списку посилань не було
    # видно, де тиждень, а де місяць
    kind = d.get("kindFull") or d.get("kind") or ""
    title = ((str(kind) + " · " if kind else "") + (d.get("title") or "StatsAI")) + " · StatsAI"
    # перші два показники читаються самі (TP, +3.1%), решті потрібен підпис (RR 3.1)
    kpis = [k for k in (d.get("kpis") or [])[:4] if k.get("v")]
    bits = [str(k["v"]) for k in kpis[:2]] + ["%s %s" % (k.get("k"), k["v"]) for k in kpis[2:]]
    if d.get("kind"):
        bits.insert(0, str(d["kind"]))
    desc = " · ".join(bits) or "StatsAI"
    # для тижня й місяця сторінка малює свій календар — він і йде в превью;
    # для дня й угоди беремо скрін самої угоди
    shot = d.get("og") or share_preview_shot(rec)
    esc_ = html_escape
    tags = [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="StatsAI">',
        '<meta property="og:title" content="%s">' % esc_(title),
        '<meta property="og:description" content="%s">' % esc_(desc),
        '<meta property="og:url" content="%s/s/%s">' % (esc_(base), sid),
        '<meta name="twitter:title" content="%s">' % esc_(title),
        '<meta name="twitter:description" content="%s">' % esc_(desc),
    ]
    if shot:
        img = esc_("%s/api/share/%s/shot/%s" % (base, sid, shot))
        tags += ['<meta property="og:image" content="%s">' % img,
                 '<meta name="twitter:image" content="%s">' % img,
                 '<meta name="twitter:card" content="summary_large_image">']
    else:
        tags += ['<meta name="twitter:card" content="summary">']
    return "\n".join(tags)


def ts_copy_ok(rec):
    """Посилання на ТС, і автор дозволив її забирати."""
    if not rec or share_store.kind_of(rec.get("data")) != "ts" or not rec.get("user_id"):
        return False
    try:
        u = db.get_user(rec["user_id"])
    except Exception:
        return False
    return bool(u and u.get("ts_copy"))


def share_read(sid):
    """Отдаёт снимок или None, если его нет либо срок вышел.

    Спершу база; старі посилання, роздані ще з файлів, дочитуємо з диска,
    щоб не зламались у людей, кому їх уже відправили."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", sid or ""):
        return None
    try:
        rec = share_store.read(sid)
    except Exception:
        rec = None
    if rec:
        return rec
    path = _share_path(sid)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        return None
    if rec.get("expires") and time.time() > rec["expires"]:
        try: os.remove(path)                # просроченное сразу убираем
        except Exception: pass
        return None
    return rec


# ---------------------------------------------------------------------------
# Перенос журнала из Notion по обычной публичной ссылке.
#
# Никаких ключей: человек в Notion делает Share -> Publish to web и вставляет
# сюда ссылку. Чтение живёт в notion_public.py, разбор значений — в
# notion_import.py. Последнюю ссылку и сверку колонок помним для каждого
# пользователя отдельно: журналы у всех свои.
# ---------------------------------------------------------------------------
_jobs = {}
_jobs_lock = threading.Lock()

# Посилання, назва бази і звірка колонок — у базі, а не файлом: на хостингу
# диск контейнера стирається при кожному оновленні коду, і статус «підключено»
# зникав разом із файлом.
_NOTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_conf (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data    JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""
_notion_ready = False


def _notion_init():
    global _notion_ready
    if _notion_ready:
        return
    with db.connect() as conn:
        conn.execute(_NOTION_SCHEMA)
    _notion_ready = True


def notion_conf(uid):
    _notion_init()
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM notion_conf WHERE user_id=%s", (uid,)).fetchone()
    return _with_sources(dict(row["data"]) if row and row["data"] else {})


def _with_sources(conf):
    """Старая запись про единственное перенесение становится первой строкой
    списка баз.

    Сворачиваем её сразу при чтении: `url` и `title` в conf описывают именно
    её, а следующий же импорт их перезапишет — тогда старый журнал получил бы
    имя и ссылку нового."""
    src = [dict(s) for s in (conf.get("sources") or [])
           if isinstance(s, dict) and s.get("id")]
    last = conf.get("last") or {}
    if last.get("id") and not any(s["id"] == last["id"] for s in src):
        src.append({"id": last["id"], "url": conf.get("url") or "",
                    "title": conf.get("title") or "", "when": last.get("when") or ""})
    conf["sources"] = src
    return conf


def notion_save(uid, conf):
    _notion_init()
    with db.connect() as conn:
        conn.execute("INSERT INTO notion_conf (user_id, data) VALUES (%s,%s) "
                     "ON CONFLICT (user_id) DO UPDATE SET data=EXCLUDED.data",
                     (uid, Jsonb(conf or {})))


# Сколько перенесений помним. Каждое — это одна база Notion, из которой
# брали сделки; больше двух-трёх не бывает, запас взят с потолка.
NOTION_SOURCES_MAX = 20


def notion_sources(uid, conf=None):
    """Из каких баз собран журнал: по записи на каждое перенесение.

    Раньше помнили только последнее — и человек, перенёсший второй журнал
    (у многих месяцы лежат в разных таблицах Notion), терял возможность
    откатить первый. Теперь помним все.

    Количество сделок считаем по журналу, а не по записанному числу: цифра
    верна, даже если браузер закрыли посреди переноса.

    Базы, от которых в журнале не осталось ни одной сделки, раньше из списка
    выпадали — и человек не мог их отвязать: суточное обновление ходило в
    Notion, а показать было нечего. Теперь показываем все подключённые базы,
    хоть с нулём: список отвечает на вопрос «откуда ко мне ещё ходят», а не
    только «откуда пришли сделки».
    """
    conf = notion_conf(uid) if conf is None else conf
    counts = db.count_imports(uid)
    out = [dict(s, count=counts.get(s["id"]) or 0)
           for s in conf.get("sources") or []]
    out.sort(key=lambda s: s.get("when") or "", reverse=True)
    return out


def notion_add_source(conf, rec):
    src = [s for s in (conf.get("sources") or []) if s["id"] != rec["id"]]
    src.append(rec)
    conf["sources"] = src[-NOTION_SOURCES_MAX:]
    return conf


def add_trades(user_id, items, kind="", run="", ts=""):
    """Кладём пачку сделок в журнал. Вызывается из фонового потока импорта.
    kind="bt" — в бэктест; run — журнал бэктеста, если колонки под него не было."""
    batch = []
    for it in items:
        if kind == "bt":
            it = dict(it, kind="bt", bt_run=it.get("bt_run") or run)
        elif ts:
            it = dict(it, ts=ts)            # у ту стратегію, яку людина зараз бачить
        t = clean_trade(it, new_id())
        t["screenshots"] = it.get("screenshots") or []
        batch.append(t)
    db.insert_trades(user_id, batch)
    # Перенос качает картинки прямо на диск. Забираем их в базу, иначе после
    # первого же обновления кода на хостинге они пропадут.
    for t in batch:
        for sh in t["screenshots"]:
            name = sh.get("file")
            if not name:
                continue
            try:
                filestore.ingest(os.path.join(SHOTS, name), name)
            except Exception:
                pass


def drop_import(user_id, batch):
    """Отменяет перенесение целиком: убирает его сделки и их скриншоты.

    Без этого любая ошибка в сверке колонок необратима — а ошибиться там
    легко, поэтому откат нужен не «когда-нибудь», а сразу."""
    batch = str(batch or "")[:32]
    if not batch:
        return 0
    removed, orphan_files = db.drop_import(user_id, batch)
    delete_files(orphan_files)
    conf = notion_conf(user_id)
    conf["sources"] = [s for s in conf.get("sources") or [] if s["id"] != batch]
    if (conf.get("last") or {}).get("id") == batch:
        conf.pop("last", None)
    if not conf["sources"]:
        _forget_notion(conf)
    notion_save(user_id, conf)
    return removed


def _forget_notion(conf):
    """Останню базу зняли — прибираємо й те, що її описувало. Інакше сайт
    вважав би Notion підключеним через саме лише посилання, яке людина
    колись вставила."""
    for k in ("url", "title", "mapping", "auto"):
        conf.pop(k, None)


# ---------------------------------------------------------------------------
# Налаштування підказок: що людина прибрала з кнопок, що додала свого.
# Один JSON на людину — як notion_conf. Форму не описуємо: її знає
# сторінка, сервер лише зберігає й повертає.
# ---------------------------------------------------------------------------
_PREFS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_prefs (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data    JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""
_prefs_ready = False
PREFS_MAX = 32 * 1024      # більше — це вже не налаштування


def _prefs_init():
    global _prefs_ready
    if _prefs_ready:
        return
    with db.connect() as conn:
        conn.execute(_PREFS_SCHEMA)
    _prefs_ready = True


# ---------------------------------------------------------------------------
# Реферальні мітки. Власник спільноти не довіряє відповідям людей — рахуємо
# за посиланнями: ?ref=<партнер> у адресі → кука на 30 днів у гостя → поле
# users.ref_source при реєстрації. Раз і назавжди: пишемо лише туди, де
# порожньо, тож ні людина, ні інший партнер мітку не переб'ють.
# ---------------------------------------------------------------------------
REF_COOKIE = "ref"
REF_TTL = 30 * 24 * 3600
# Відбиток пристрою для входу через Google чи Discord. Звичайна реєстрація
# шле його в тілі запиту, а тут дорога йде через чужий сайт і назад, і
# нічого, крім кук, не переживає цю подорож. Живе хвилини — рівно щоб
# дійти до сервісу й повернутись.
DEV_COOKIE = "devm"
DEV_TTL = 15 * 60
PARTNER_TITLES = {"blackswan": "Black Swan",      # як партнера звуть у прев'ю
                  "fxlab": "FX LAB"}
# Коротке посилання: statsai.xyz/bs замість statsai.xyz/?ref=blackswan.
# Довге теж лишається робочим — його вже роздали.
# ig і tt лишаємо як синоніми соцмереж: якщо коротке посилання вже кудись
# вставили, воно рахується туди ж, а не пропадає
PARTNER_ALIASES = config.PARTNER_ALIASES
# Як мітку звуть у звіті
REF_TITLES = {"blackswan": "Black Swan", "fxlab": "FX LAB", "social": "Соцсети"}


def ref_all():
    """Усі мітки, які приймаємо: партнери й свої канали."""
    return tuple(config.PARTNERS) + tuple(config.CHANNELS)


def ref_norm(value):
    """Мітка з адреси: коротка назва чи повна — однаково. Чуже — порожньо."""
    v = (value or "").strip().lower()
    v = PARTNER_ALIASES.get(v, v)
    return v if v in ref_all() else ""


def ref_short(ref):
    """Як писати мітку в адресі: коротко, якщо є коротка назва."""
    for short, full in PARTNER_ALIASES.items():
        if full == ref:
            return short
    return ref
KIND_RU = {"trade": "Сделка", "day": "День", "week": "Неделя", "month": "Месяц", "year": "Год",
           "quarter": "Квартал",
           "reviewmonth": "Анализ дня · месяц",
           "ts": "Торговая система", "review": "Анализ дня", "period": "Период (старые)",
           "other": "Другое"}


def _emo_init():
    """Одноразово: емоції в уже записаних угодах — кодами (emotions.norm).
    Старі записи лежали словами різних мов — «Спокій» від бота,
    «Спокойствие» з сайту — і в розрізі стояли окремими рядками."""
    try:
        if db.meta_get("emotions_codes_v1", ""):
            return
        n = 0
        with db.connect() as conn:
            rows = conn.execute('SELECT id, "emotion" FROM trades WHERE "emotion" <> \'\'').fetchall()
            for r in rows:
                v = emotions.norm(r["emotion"])
                if v != r["emotion"]:
                    conn.execute('UPDATE trades SET "emotion"=%s WHERE id=%s', (v, r["id"]))
                    n += 1
            conn.commit()
        db.meta_set("emotions_codes_v1", "1")
        print("емоції → коди: %d угод" % n)
    except Exception as ex:
        print("емоції не зведено:", ex)


def _emo_init2():
    """Одноразово: відповіді «своїми словами» з бота, які не звелись до
    категорії (у розрізі стояло «Розфокус» серед російських назв), —
    пробуємо звести ще раз, не вийшло — «Інше». Слова лишаються в
    emotion_raw. Свої категорії з сайту (emotion_raw порожній) не чіпаємо.
    У фоні: для кожного рядка може знадобитись модель."""
    def run():
        try:
            if db.meta_get("emotions_raw_v2", ""):
                return
            with db.connect() as conn:
                rows = conn.execute('SELECT id, "emotion", emotion_raw FROM trades '
                                    'WHERE emotion_raw IS NOT NULL AND "emotion" <> \'\'').fetchall()
            n = 0
            for r in rows:
                parts = [p.strip() for p in r["emotion"].split(",") if p.strip()]
                if all(emotions.code_of(p) for p in parts):
                    continue
                code = emotions.classify(r["emotion_raw"] or r["emotion"]) or emotions.OTHER_CODE
                with db.connect() as conn:
                    conn.execute('UPDATE trades SET "emotion"=%s WHERE id=%s', (code, r["id"]))
                    conn.commit()
                n += 1
            db.meta_set("emotions_raw_v2", "1")
            print("свої слова → категорії: %d угод" % n)
        except Exception as ex:
            print("свої слова не зведено:", ex)
    threading.Thread(target=run, daemon=True).start()


def _pairs_init():
    """Разово для кожної версії списку синонімів (tidy.SAME_VERSION): у
    кожного журналу один актив — одне написання. Беремо те, що трапляється
    найчастіше; «Nasdaq (NQ)» стає «US100», якщо US100 у журналі більше.
    Нові угоди й так сводяться при записі (db._one_spelling), тут — старі."""
    def run():
        flag = "pairs_same_v" + tidy.SAME_VERSION
        try:
            if db.meta_get(flag, ""):
                return
            with db.connect() as conn:
                rows = conn.execute('SELECT id, user_id, "pair" FROM trades WHERE "pair" <> \'\'').fetchall()
            by = {}
            for r in rows:
                by.setdefault((r["user_id"], tidy.pair_key(r["pair"])), []).append(r)
            n = 0
            with db.connect() as conn:
                for (_u, _k), rs in by.items():
                    cnt = {}
                    for r in rs:
                        p = r["pair"].strip()
                        cnt[p] = cnt.get(p, 0) + 1
                    if len(cnt) < 2:
                        continue
                    best = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                    for r in rs:
                        if r["pair"].strip() != best:
                            conn.execute('UPDATE trades SET "pair"=%s WHERE id=%s', (best, r["id"]))
                            n += 1
                conn.commit()
            db.meta_set(flag, "1")
            print("інструменти зведено: %d угод" % n)
        except Exception as ex:
            print("інструменти не зведено:", ex)
    threading.Thread(target=run, daemon=True).start()


def ref_visit(ref, ua):
    """Перехід за коротким посиланням (/bs, /soc): скільки людей натиснуло,
    ще до реєстрації. Боти месенджерів, що тягнуть прев'ю, не рахуються."""
    if not ref or share_store.BOT_UA.search(ua or ""):
        return
    try:
        with db.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS ref_visits (
                               ref TEXT NOT NULL, day DATE NOT NULL, n INTEGER NOT NULL DEFAULT 0,
                               PRIMARY KEY (ref, day))""")
            conn.execute("""INSERT INTO ref_visits (ref, day, n) VALUES (%s, (now() AT TIME ZONE 'Europe/Kyiv')::date, 1)
                            ON CONFLICT (ref, day) DO UPDATE SET n = ref_visits.n + 1""", (ref,))
            conn.commit()
    except Exception as ex:
        print("ref_visit:", ex)


def _ref_init():
    with db.connect() as conn:
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_source TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_at TIMESTAMPTZ")
        conn.commit()
    # Власники журналу мітки не носять — знімаємо, якщо колись причепилась
    # (клік по партнерському посиланню, старе опитування).
    with db.connect() as conn:
        conn.execute("UPDATE users SET ref_source=NULL, ref_at=NULL "
                     "WHERE ref_source IS NOT NULL AND (lower(nickname) = ANY(%s) OR lower(email) = ANY(%s))",
                     (list(config.ADMIN_NICKS), list(config.ADMIN_EMAILS)))
        conn.commit()
    # Одноразово: хто відповів партнером у старому опитуванні «звідки
    # дізнався» — отримує мітку. Для старих акаунтів це єдине, що є.
    if db.meta_get("refs_from_survey"):
        return
    _prefs_init()
    with db.connect() as conn:
        conn.execute("""UPDATE users u SET ref_source = p.data->'source'->>'id', ref_at = now()
                        FROM user_prefs p
                        WHERE p.user_id = u.id AND u.ref_source IS NULL
                          AND p.data->'source'->>'id' = ANY(%s)""", (list(config.PARTNERS),))
        conn.commit()
    db.meta_set("refs_from_survey", "1")


# Таблиці, у яких лежить чуже добро з user_id. Частина зникає каскадом за
# зовнішнім ключем, частина (shares, share_stats) ключа не має — тому
# проходимо списком і не покладаємось на каскад.
PER_USER_TABLES = ("trades", "strategies", "notion_conf", "user_prefs", "day_notes",
                   "trade_drafts", "backups", "shares", "share_stats", "identities",
                   "link_codes", "notified_events", "auth_links")


def _files_in(obj, out):
    """Імена скрінів усередині будь-якого JSON: ключі file / shot / shots."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("file", "shot") and isinstance(v, str) and v.strip():
                out.add(os.path.basename(v.strip()))
            elif k == "shots" and isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and x.strip():
                        out.add(os.path.basename(x.strip()))
                    else:
                        _files_in(x, out)
            else:
                _files_in(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _files_in(x, out)
    return out


def user_files(uid):
    """Усі файли скрінів людини: угоди, ТС, аналіз дня."""
    out = set()
    try:
        for t in db.list_trades(uid):
            _files_in(t, out)
    except Exception:
        pass
    for get in (lambda: [ts_store.get(uid)], lambda: day_store.days(uid, 2000)):
        try:
            _files_in(get(), out)
        except Exception:
            pass
    return [n for n in out if n]


def delete_user_fully(uid):
    """Прибрати людину й усе її. Повертає кількість видалених файлів."""
    names = user_files(uid)
    for table in PER_USER_TABLES:
        try:
            with db.connect() as conn:
                conn.execute("DELETE FROM %s WHERE user_id=%%s" % table, (uid,))
                conn.commit()
        except Exception:
            pass                       # немає такої таблиці або колонки — не біда
    with db.connect() as conn:
        conn.execute("DELETE FROM users WHERE id=%s", (uid,))
        conn.commit()
    delete_files(names)
    return len(names)


def _billing_block(u):
    """Підписка в картці адмінки: що видно і чим це можна поправити.

    Тут, на відміну від журналу, лічильники показуємо — адмін мусить
    бачити, скільки людина витратила й де її межа. Заборона на «лишилось
    N із 20» стосується самої людини, а не цієї сторінки.
    """
    e = admin_page.e
    dt = lambda v: v.strftime("%d.%m.%Y") if hasattr(v, "strftime") else (str(v)[:10] if v else "—")
    st = billing.state(u["id"])
    nb = antifraud.neighbours(u["id"])
    n = lambda k, d=0: (u[k] if u[k] is not None else d)
    pair = lambda used, cap, d: "%s из %s" % (n(used), n(cap, d))
    kv = lambda k, v: "<span>%s</span><span>%s</span>" % (e(k), v)
    who = lambda rows: ", ".join(
        '<a href="/admin/u/%s" style="color:var(--acc)">%s</a>' % (e(r["nickname"]), e(r["nickname"]))
        for r in rows) or "—"
    # Нік їде всередину <script>. json.dumps не чіпає "</", а саме ним
    # рядок закрив би тег і все після нього стало б розміткою. Ніком
    # такого не зробити (NICK_RE не пускає ні "<", ні "/"), але
    # підстраховка тут коштує рядок, а перевірка живе в іншому файлі.
    nick_js = json.dumps(u["nickname"], ensure_ascii=False).replace("</", "<\\/")
    inp = ('padding:8px 10px;border-radius:9px;border:1px solid var(--line);'
           'background:var(--card);color:var(--text);font:inherit;width:82px')
    return (
        '<div class="grid two" style="margin-top:12px"><div class=card><h2>Подписка</h2><div class=kv>'
        + kv("План", e(("Special · с %s (выдан вручную)" % dt(u["special_since"]))
                       if st["plan"] == billing.LIFE
                       else (("%s · до %s" % (st["plan"], dt(u["paid_until"])))
                             if st["active"] else "бесплатный")))
        + kv("Сделки", e(pair("free_trades_used", "free_trades_cap", config.FREE_TRADES)))
        + kv("Бэктест", e(pair("free_bt_used", "free_bt_cap", config.FREE_BT)))
        + kv("Переносы", e(pair("imports_used", "imports_cap", config.FREE_IMPORTS)))
        + kv("Бэктест из Notion", e(pair("bt_imports_used", "bt_imports_cap", 3) + " (с подпиской)"))
        + kv("Обращения к модели", e("%s из %s%s" % (
            billing.ai_used(u), billing.ai_cap(u),
            (" · окно до " + dt(u["ai_reset_at"])) if u["ai_reset_at"] else "")))
        + kv("Набор цен", e({"early": "ранние (скидка навсегда)",
                             "fxlab": "FX LAB (по промокоду)"}.get(u["price_plan"] or "std", "обычный")))
        + kv("Промокод", "—" if not u["promo_code"] else
             e("%s · %s" % (u["promo_code"], ("оплачен " + dt(u["promo_used_at"]))
                            if u["promo_used_at"] else "введён, ждёт оплаты")))
        + kv("Своя цена", e("%.2f EUR" % (u["own_price_cents"] / 100.0)) if u["own_price_cents"] else "—")
        + kv("Заметка", e(u["billing_note"] or "—"))
        + "</div></div>"
        + "<div class=card><h2>Откуда пришёл</h2><div class=kv>"
        + kv("IP регистрации", e((u["signup_ip"] or "—") + (" · разрешён вручную" if nb["allowed"] else "")))
        + kv("Отпечаток устройства", e((u["signup_device"] or "")[:12] or "—"))
        + kv("Тот же IP", who(nb["ip"]))
        + kv("То же устройство", who(nb["device"]))
        + kv("Та же база Notion", who(nb["notion"]))
        + '</div><p class=mute style="margin:10px 0 0;font-size:12px">Совпал только IP — это ещё ничего '
          'не значит: у мобильных операторов один выход на тысячи людей. Совпало устройство — почти '
          "наверняка тот же человек.</p></div></div>"
        + '<div class=card style="margin-top:12px"><h2>Поправить подписку</h2>'
          '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
          '<input id=bdays type=number min=1 placeholder="30" style="%s">'
          '<button id=bgrant class=btn>Дать подписку на N дней</button>'
          '<button class="btn bplan" data-d=30 data-p=month>Месяц</button>'
          '<button class="btn bplan" data-d=90 data-p=quarter>Квартал</button>'
          '<button class="btn bplan" data-d=365 data-p=year>Год</button>'
          '<button id=blife class=btn>Сделать Special</button>'
          '<button id=brevoke class=btn>Снять подписку</button></div>' % inp
        + '<p class=mute style="margin:14px 0 8px;font-size:12px">Бонус к бесплатным лимитам '
          "(прибавляем к границе, потраченное не трогаем):</p>"
          '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
          '<span class=mute>сделки</span><input id=btr type=number placeholder="0" style="%s">'
          '<span class=mute>бэктест</span><input id=bbt type=number placeholder="0" style="%s">'
          '<span class=mute>переносы</span><input id=bim type=number placeholder="0" style="%s">'
          '<span class=mute>обращения</span><input id=bai type=number placeholder="0" style="%s">'
          '<span class=mute>бэктест из Notion</span><input id=bbti type=number placeholder="0" style="%s">'
          '<button id=bbonus class=btn>Добавить</button></div>' % (inp, inp, inp, inp, inp)
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">'
          '<button id=bearly class=btn>Цены как ранним</button>'
          '<button id=bstd class=btn>Обычные цены</button>'
          '<button id=ballow class=btn>%s</button></div>'
          '<p id=bmsg class=mute></p></div>' % (
              "Убрать разрешение IP" if nb["allowed"] else "Разрешить этот IP")
        + "<script>const NICK=%s;"
          "async function bill(act,data){bmsg.textContent='…';"
          "const r=await fetch('/api/admin/billing/'+act,{method:'POST',"
          "headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify(Object.assign({nick:NICK},data||{}))});"
          "const d=await r.json().catch(()=>({}));"
          "bmsg.textContent=r.ok?'готово':(d.error||('ошибка '+r.status));"
          "if(r.ok)setTimeout(()=>location.reload(),700);}"
          "bgrant.onclick=()=>bill('grant',{days:+bdays.value||0});"
          "document.querySelectorAll('.bplan').forEach(b=>b.onclick=()=>{"
          "if(confirm('Дать подписку «'+b.textContent+'»? Дни прибавятся к уже оплаченным.'))"
          "bill('grant',{days:+b.dataset.d,plan:b.dataset.p});});"
          "blife.onclick=()=>{if(confirm('Сделать Special? Журнал откроется целиком, без срока и оплаты.'))"
          "bill('grant',{life:1});};"
          "brevoke.onclick=()=>{if(confirm('Снять подписку? Оплаченные дни пропадут.'))"
          "bill('revoke');};"
          "bbonus.onclick=()=>bill('bonus',{trades:+btr.value||0,bt:+bbt.value||0,"
          "imports:+bim.value||0,ai:+bai.value||0,bt_imports:+bbti.value||0});"
          "bearly.onclick=()=>bill('price',{price_plan:'early'});"
          "bstd.onclick=()=>bill('price',{price_plan:'std'});"
          "ballow.onclick=()=>bill('allow-ip',{off:%s});</script>" % (
              nick_js, "true" if nb["allowed"] else "false"))


def _ts_restore_block(u):
    """Картка адмінки: повернути ТС з денного зліпка. Скріни у зліпку лише
    іменами — якщо файли вже прибрано, слоти лишаться порожніми."""
    e = admin_page.e
    try:
        cur = json.dumps(ts_store.get(u["id"]) or {}, sort_keys=True, ensure_ascii=False)
        vers = backup.strategies(u["id"])
    except Exception as ex:
        print("ts restore list:", ex)
        return ('<div class=card style="margin-top:12px"><h2>ТС из копии</h2>'
                '<p class=mute>Не удалось прочитать копии: %s</p></div>' % e(str(ex)))
    if not vers:
        return ('<div class=card style="margin-top:12px"><h2>ТС из копии</h2>'
                '<p class=mute>Копий с ТС нет.</p></div>')
    opts = "".join(
        '<option value="%s">%s · %d знаков%s</option>' % (
            d, e(".".join(reversed(d.split("-")))), len(js),
            " · как сейчас" if js == cur else "")
        for d, js in ((d, json.dumps(ts, sort_keys=True, ensure_ascii=False)) for d, ts in vers))
    return ('<div class=card style="margin-top:12px"><h2>ТС из копии</h2>'
            '<p class=mute style="font-size:12px;margin:0 0 10px">Копия делается раз в день, хранится 14 дней. '
            'Сейчас ТС %d знаков. Выбери день до того, как её затёрло.</p>'
            '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
            '<select id=tsday class=btn>%s</select>'
            '<button id=tsback class=btn>Вернуть ТС</button></div>'
            '<script>tsback.onclick=()=>{if(confirm("Заменить нынешнюю ТС копией за "+'
            'tsday.selectedOptions[0].textContent.split(" ")[0]+"?"))bill("ts-restore",{day:tsday.value});};'
            '</script></div>' % (len(cur), opts))


def _is_admin(uid):
    try:
        u = db.get_user(uid)
    except Exception:
        return False
    if not u:
        return False
    return ((u["nickname"] or "").strip().lower() in config.ADMIN_NICKS
            or (u["email"] or "").strip().lower() in config.ADMIN_EMAILS)


def ref_claim(uid, ref):
    """Поставити мітку на акаунт, якщо її ще нема. True — поставили.
    Власники журналу (ADMIN_NICKS) мітки не носять: їхні посилання — свої."""
    ref = (ref or "").strip().lower()
    if not uid or ref not in ref_all() or _is_admin(uid):
        return False
    with db.connect() as conn:
        cur = conn.execute("UPDATE users SET ref_source=%s, ref_at=now() "
                           "WHERE id=%s AND ref_source IS NULL", (ref, uid))
        n = cur.rowcount
        conn.commit()
    return n > 0


def ref_of_user(uid):
    """Мітка хазяїна сторінки: його гості рахуються тому ж партнерові."""
    if not uid:
        return None
    try:
        u = db.get_user(uid)
    except Exception:
        return None
    ref = (u and u["ref_source"]) or None
    # свої канали далі не передаємо: людина прийшла з чужого посилання,
    # а не з інстаграма — інакше цифра каналу перестає щось означати
    return ref if ref in config.PARTNERS else None


def prefs_get(uid):
    _prefs_init()
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM user_prefs WHERE user_id=%s", (uid,)).fetchone()
    return dict(row["data"]) if row and row["data"] else {}


def prefs_save(uid, data):
    _prefs_init()
    with db.connect() as conn:
        conn.execute("INSERT INTO user_prefs (user_id, data) VALUES (%s,%s) "
                     "ON CONFLICT (user_id) DO UPDATE SET data=EXCLUDED.data",
                     (uid, Jsonb(data)))
        conn.commit()


def blank_filler(user_id, rows):
    """Куди дописувати поля, якщо угода вже в журналі.

    Впізнаємо її тими самими двома способами, що й імпорт, коли вирішує не
    переносити: за id запису в Notion, а якщо його немає — за відбитком
    (день, інструмент, напрямок, результат). Другий шлях потрібен угодам,
    перенесеним з іншої бази або ще до того, як ми стали зберігати id:
    саме вони й лишались без сесії назавжди.

    Кожен рядок журналу віддаємо лише один раз: три однакових входи за
    день — три різних рядки, і другий Notion-рядок не має дописувати те,
    що вже дописав перший."""
    by_nid, by_mark, mark_of = {}, {}, {}
    for t in rows:
        if t.get("notion_id"):
            by_nid.setdefault(t["notion_id"], t["id"])
        mark = tidy.same_trade_key(t)
        if mark:
            by_mark.setdefault(mark, []).append(t["id"])
            mark_of[t["id"]] = mark

    def fill(notion_id, t):
        tid = by_nid.pop(notion_id, None)
        if tid is None:
            ids = by_mark.get(tidy.same_trade_key(t) or "")
            tid = ids.pop(0) if ids else None
        else:
            ids = by_mark.get(mark_of.get(tid) or "")
            if ids and tid in ids:
                ids.remove(tid)
        # Такої угоди в журналі немає — значить, її зараз перенесуть як нову.
        return db.fill_blanks(user_id, tid, t) if tid else 0

    return fill


def start_import(user_id, tables, mapping, opts, kind="", run="", ts=""):
    jid = secrets.token_urlsafe(6)
    job = notion.Job(jid)
    job.user_id = user_id          # чтобы чужое задание нельзя было подсмотреть
    with _jobs_lock:
        _jobs[jid] = job
        # старые задания не копим
        for old_id in list(_jobs)[:-8]:
            _jobs.pop(old_id, None)
    # что уже было: сделки в журнале плюс те, что человек из него убрал.
    # Отпечатки нужны, чтобы узнать сделку, записанную в другой базе Notion, —
    # там у неё свой notion_id, и он не совпадёт
    # бектест звіряємо з бектестом: та сама угода в реальному журналі —
    # не причина її не перенести
    rows = db.list_trades(user_id, kind)
    known, seen, marks = db.import_seen(user_id, rows)
    th = threading.Thread(
        target=npub.run_public_import,
        args=(job, tables, mapping, opts, SHOTS, known, seen,
              lambda items: add_trades(user_id, items, kind, run, ts), marks),
        kwargs={"fill": blank_filler(user_id, rows)},
        daemon=True)
    th.start()
    return job


def import_busy(uid):
    """Чи йде просто зараз ручне перенесення цієї людини. Автооновлення
    в цей час не лізе: обидва писали б у журнал одні й ті самі угоди, і
    хто з них перший — вирішував би випадок."""
    with _jobs_lock:
        return any(getattr(j, "user_id", None) == uid and j.state == "running"
                   for j in _jobs.values())


def ask_emotion_later(user, trade):
    """Вопрос про эмоцию уходит в фоне — ответ сайту ждать Telegram не должен."""
    def run():
        try:
            emotions.send_prompt(user["telegram_id"], trade)
        except Exception as ex:
            print("не смог спросить про эмоцию:", ex)
    threading.Thread(target=run, daemon=True).start()


def bot_username():
    """Имя бота нужно для ссылки привязки. Спрашиваем у Telegram сами и запоминаем,
    чтобы кнопка работала и до первого запуска bot.py."""
    name = config.BOT_USERNAME or db.meta_get("bot_username")
    if name:
        return name
    try:
        name = tg_api.get_me()["username"]
    except Exception as ex:
        print("не смог узнать имя бота:", ex)
        return None
    db.meta_set("bot_username", name)
    return name


# Пошта на око: одна «собачка», крапка після неї, ніяких пробілів. Строгішу
# перевірку робити нема сенсу — чи існує скринька, скаже тільки лист, який
# туди піде.
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


def nick_from_email(email):
    """Нікнейм із пошти: до «собачки», літери й цифри.

    Нікнейм потрібен лише для адреси відкритого журналу (/u/<нік>) і для
    звертання в боті. На реєстрації його більше не питаємо — людині це
    зайве поле, а придумати ім'я з пошти можна й самому. Так само робить
    вхід через Google (oauth.py).
    """
    base = (email or "").split("@")[0]
    base = "".join(ch for ch in base if ch.isalnum() or ch in "_-.").strip("._-")[:24]
    base = base or "trader"
    # Нік із пошти ніхто не вводить руками, тому заборонені імена треба
    # відсіювати саме тут: пошта виду «davaraf@…» інакше зробила б власника
    # з випадкової людини (див. nick_taken_by_us).
    return (base + "1") if nick_taken_by_us(base) else base


NICK_RE = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
# Службові й власницькі ніки лежать у config: їх перевіряє не лише ця
# сторінка, а й вхід через Google чи Discord (oauth.py).
nick_taken_by_us = config.nick_reserved
AVATAR_MAX = 2 * 1024 * 1024


def nick_problem(want, uid):
    """Чим новий нік не годиться: "" — годиться, "same" — той самий,
    "bad" — не той формат, "taken" — зайнятий чи зарезервований."""
    if not NICK_RE.match(want or ""):
        return "bad"
    me = db.get_user(uid)
    if me and (me["nickname"] or "") == want:
        return "same"
    if nick_taken_by_us(want):
        return "taken"
    other = db.get_user_by_nick(want)
    if other and other["id"] != uid:
        return "taken"
    return ""


def in_background(fn, *args):
    """Зробити повільне діло після відповіді.

    Лист іде через чужий сервер і забирає секунду-другу. Тримати на ньому
    відповідь ні до чого, а на «забув пароль» ще й шкідливо: знайома пошта
    відповідала б помітно повільніше за незнайому, і однакова відповідь
    перестала б бути однаковою.
    """
    def run():
        try:
            fn(*args)
        except Exception as ex:
            print("лист не пішов:", ex, flush=True)
    threading.Thread(target=run, daemon=True).start()


def request_tz(raw, user=None):
    """Пояс запиту: спершу той, що прислав браузер, потім із профілю.

    Браузер шле свій, бо гість профілю не має, а вибір пояса має діяти
    й до входу. Не впізнали назву — Київ, як було завжди.
    """
    for want in (raw, (user or {}).get("tz") if user else None):
        if not want:
            continue
        try:
            return ZoneInfo(str(want))
        except Exception:
            continue
    return calendar_feed.KYIV


# Готові аватарки — помічник StatsAI у 15 варіаціях. Картинки лежать у static/avatars/<назва>.svg, у базі —
# "preset:<назва>". Список закритий: чужу назву сервер не прийме.
AVATAR_PRESETS = ("wink", "shades", "surprised", "focused", "laugh",
                  "sleepy", "love", "stars", "sly", "bull",
                  "bear", "headphones", "cap", "tongue", "robot")
AVATAR_PRESET_V = 1


def avatar_url(value):
    if not value:
        return None
    if value.startswith("preset:"):
        name = value[len("preset:"):]
        return ("/static/avatars/%s.svg?v=%d" % (name, AVATAR_PRESET_V)) if name in AVATAR_PRESETS else None
    return "/api/me/avatar/" + value


def own_avatar_file(value):
    """Чи це завантажене фото (його файл треба прибрати), а не готова аватарка."""
    return bool(value) and not value.startswith("preset:")


def user_public(user):
    return {"id": user["id"], "email": user["email"], "nickname": user["nickname"],
            "telegram": user["telegram_username"] or (str(user["telegram_id"])
                                                      if user["telegram_id"] else None),
            "telegram_linked": user["telegram_id"] is not None,
            "digest_hour": user["digest_hour"], "digest_minute": user["digest_minute"],
            "digest_enabled": user["digest_enabled"],
            "public_journal": bool(user["public_journal"]),
            "ts_copy": bool(user.get("ts_copy")),
            "mail_news": user.get("mail_news") is not False,
            "tz": user["tz"] or "Europe/Kyiv",
            "email_confirmed": user["email_confirmed_at"] is not None,
            "avatar": avatar_url(user.get("avatar")),
            "twofa": twofa.enabled(user),
            "twofa_backup_left": len(user.get("twofa_backup") or [])}


# ---------------------------------------------------------------------------
# Відкритий журнал: /u/<нік>.
#
# Людина сама вирішує, показувати свій журнал іншим чи ні. Показуємо тільки
# те, за чим ідуть: угоди і статистику. Нотатки, помилки, емоції та «Аналіз
# дня» — щоденник, а не вітрина, тому назовні не йдуть ніколи.
#
# Білий список нижче — єдине місце, де це вирішується: додали поле в угоду —
# воно за замовчуванням лишається приватним, поки його сюди не впишуть.
# ---------------------------------------------------------------------------
PUBLIC_FIELDS = ["id", "pair", "date", "session", "position", "bias", "setup",
                 "entry_model", "direction_type", "result", "rr", "risk",
                 "entry_details"]


def public_trade(t):
    out = {f: t.get(f) for f in PUBLIC_FIELDS}
    # підпис під скріном показуємо разом з ним: він пояснює сам графік,
    # а не є окремою нотаткою трейдера, які тут і далі лишаються прихованими
    out["screenshots"] = [{"tf": s.get("tf") or "", "file": s.get("file") or "",
                           "note": shot_note(s)}
                          for s in (t.get("screenshots") or []) if s.get("file")]
    return out


def share_author(user_id):
    """Хто зробив знімок: нік і чи є в нього аватарка.

    Показуємо всім, кому дали посилання, — людина має бачити, чий це
    розбір дня чи угода. На відміну від public_owner, відкритість
    журналу тут ні до чого: це підпис автора, а не запрошення в журнал."""
    if not user_id:
        return None
    try:
        user = db.get_user(user_id)
    except Exception:
        return None
    if not user or not user["nickname"]:
        return None
    av = user.get("avatar")
    out = {"nick": user["nickname"]}
    if av:
        # готова аватарка лежить у static і відкрита всім; завантажене фото
        # віддаємо тільки через адресу самого знімка (нижче в GET)
        out["av"] = avatar_url(av) if av.startswith("preset:") else True
    return out


def public_owner(user_id):
    """Нік хазяїна, поки журнал відкритий. Закрив — повертаємо None, і
    посилання на нього зникає скрізь, де ми його показували."""
    if not user_id:
        return None
    try:
        user = db.get_user(user_id)
    except Exception:
        return None
    if not user or not user["public_journal"]:
        return None
    return user["nickname"]


class H(BaseHTTPRequestHandler):
    # Чим ми підписуємось у заголовку Server. Стандартно тут їде
    # «BaseHTTP/0.6 Python/3.14.6» — рядок, з якого одразу видно, якої
    # версії мова й бібліотека. Саме з цього починають, коли шукають
    # готову діру під конкретну версію; нам сказати нічого.
    server_version = "StatsAI"
    sys_version = ""

    def version_string(self):
        return self.server_version

    # Скільки чекати на самого клієнта. Без цього браузер, який відкрив
    # з'єднання і замовк (обірваний вай-фай, вкладка в сплячці), тримав би
    # робітника вічно — а їх обмежена кількість.
    timeout = 30

    def log_message(self, fmt, *args):  # тихий лог
        pass

    # ---------- ответы ----------
    def _old_host(self):
        """Запит прийшов на старий адрес хостингу — перекидаємо на основний.

        Сайт переїхав, а Railway лишився живим: люди реєструвались там уже
        після того, як користувачів скопіювали, і на statsai.xyz їх немає.
        GET — 301, решта — 308, щоб метод і тіло дійшли. /health не чіпаємо:
        за ним Railway стежить, чи живий сервіс."""
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        path = urlparse(self.path).path
        if not host.endswith(".railway.app") or path == "/health":
            return False
        target = config.SITE_URL.rstrip("/") + self.path
        self.send_response(301 if self.command in ("GET", "HEAD") else 308)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _json(self, obj, code=200, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        enc = self._squeeze(data)
        if enc is not None:
            data = enc
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if enc is not None:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        # Жодної відповіді api не кешуємо. Поки сайт віддає себе сам, це
        # дрібниця, але щойно попереду стане CDN, відповідь без цього рядка
        # може осісти в ньому й дістатись не тому, кому призначалась.
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    # Скільки браузер має право тримати файл у себе. Кожен скрипт і стиль
    # ідуть з версією в адресі (news.js?v=5), тож вміст за цією адресою вже
    # ніколи не зміниться — можна кешувати надовго, а правка версії сама
    # змусить браузер піти за новим. Без цього сторінка щоразу качала всі
    # 800 КБ заново, і на телефоні це відчувалось.
    FOREVER = "public, max-age=31536000, immutable"
    # Картинки належать конкретній людині (перевіряємо власника), тому
    # private: спільним кешам по дорозі їх тримати не можна.
    PRIVATE = "private, max-age=604800"

    # Що має сенс стискати: текст стискається в 3-4 рази, картинки — ні,
    # вони вже стиснуті, і другий прохід тільки з'їдає час.
    GZIP_TYPES = ("text/", "application/javascript", "application/json",
                  "image/svg+xml")
    GZIP_MIN = 1024                  # дрібниця від стиснення тільки товстішає

    _gz_lock = threading.Lock()
    _gz_cache = {}                   # (шлях, час зміни) -> стиснуті байти

    def _squeeze(self, data):
        """Стиснути те, що зібрали в пам'яті (JSON, сторінку входу).

        Кешувати нічого: вміст щоразу новий. Дрібниці не чіпаємо — на них
        стиснення дорожче за виграш.
        """
        if len(data) < self.GZIP_MIN:
            return None
        if "gzip" not in (self.headers.get("Accept-Encoding") or "").lower():
            return None
        try:
            return gzip.compress(data, 6)
        except Exception:
            return None

    def _gzipped(self, path, data, ctype):
        """Стиснута копія файлу — з пам'яті, якщо вона там уже є."""
        if len(data) < self.GZIP_MIN:
            return None
        if not any(ctype.startswith(t) for t in self.GZIP_TYPES):
            return None
        if "gzip" not in (self.headers.get("Accept-Encoding") or "").lower():
            return None
        try:
            key = (path, os.path.getmtime(path))
        except OSError:
            return None
        with self._gz_lock:
            got = self._gz_cache.get(key)
        if got is not None:
            return got
        try:
            got = gzip.compress(data, 6)
        except Exception:
            return None
        with self._gz_lock:
            if len(self._gz_cache) > 200:      # більше файлів у нас і немає
                self._gz_cache.clear()
            self._gz_cache[key] = got
        return got

    def _file(self, path, ctype, cache=None):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            self.send_response(404); self.end_headers(); return
        enc = self._gzipped(path, data, ctype)
        if enc is not None:
            data = enc
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if enc is not None:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        # Без версії в адресі кешувати не можна: браузер показував би старий
        # файл після правки, і здавалося б, що зміни не застосувались.
        self.send_header("Cache-Control", cache or "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _media(self, path, ctype, cache=None):
        """Відео — частинами, за заголовком Range.

        Ролик-підказку в перенесенні з Notion не можна віддавати одним
        шматком, як решту файлів: Safari спершу просить перші два байти й
        без відповіді «206» взагалі не починає грати, а решті браузерів
        частини дають перемотування.
        """
        try:
            size = os.path.getsize(path)
            f = open(path, "rb")
        except Exception:
            self.send_response(404); self.end_headers(); return
        with f:
            start, end, partial = 0, size - 1, False
            m = re.match(r"bytes=(\d*)-(\d*)\s*$",
                         (self.headers.get("Range") or "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), end)
                else:                       # bytes=-N — хвіст файлу
                    start = max(0, size - int(m.group(2)))
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers(); return
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", cache or "no-store")
            self.end_headers()
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass            # закрили вікно посеред ролика — це не помилка

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.end_headers()

    def _landing(self):
        """Стартова сторінка. Як і в /login: месенджерам потрібна повна адреса
        картинки прев'ю, а у файлі вона відносна — дописуємо базу на віддачі."""
        try:
            with open(os.path.join(STATIC, "landing.html"), "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            self.send_response(404); self.end_headers(); return
        main_og = os.path.join(STATIC, "og-main.png")
        if os.path.exists(main_og):
            html = html.replace('"/static/og-main.png"',
                                '"/static/og-main.png?v=%d"' % int(os.path.getmtime(main_og)))
        # Адреса сайту без PUBLIC_URL збирається із заголовка Host, а його
        # підробляють одним рядком у запиті: у розмітку — лише екрановану.
        html = html.replace('content="/static/', 'content="%s/static/' % html_escape(self._base()))
        html = html.replace("</title>",
                            '</title>\n<meta property="og:url" content="%s/">' % html_escape(self._base()), 1)
        body = html.encode("utf-8")
        enc = self._squeeze(body)
        if enc is not None:
            body = enc
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if enc is not None:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # Найбільше тіло запиту. Угода з кількома скрінами в base64 — кілька
    # мегабайт; без межі будь-хто міг змусити сервер читати в пам'ять
    # скільки завгодно.
    MAX_BODY = 50 * 1024 * 1024

    def _body(self):
        self._too_big = False
        self._raw_body = b""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n <= 0:
            return None
        if n > self.MAX_BODY:
            # не читаємо зовсім — з'єднання закриється після відповіді
            self.close_connection = True
            self._too_big = True
            return None
        raw = self.rfile.read(n)
        # Сире тіло лишаємо: підпис вебхука рахується саме від байтів, а
        # не від розібраного json — після розбору й складання назад
        # порядок ключів і пробіли зміняться, і підпис не зійдеться.
        self._raw_body = raw
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _too_big_reply(self):
        """Тіло більше за MAX_BODY — кажемо прямо, а не «bad json»."""
        return self._json({"error": "запит завеликий", "code": "too_big"}, 413)

    # Адреси, яких загальна межа не стосується. /health стукає сам сервер
    # раз на кілька секунд, і замкнути його означало б перезапускати живий
    # сайт по колу.
    FLOOD_FREE = ("/health",)

    def _flooding(self):
        """Чи засипає нас ця адреса запитами. True — відповідь уже пішла.

        Стоїть першою дією кожного запиту, до будь-якої роботи: сенс саме
        в тому, щоб на напливі не ходити в базу й не читати файли. Відмова
        коротка, з Retry-After — чемні клієнти після нього притихають самі.
        """
        p = urlparse(self.path).path
        if p in self.FLOOD_FREE:
            return False
        wait = ratelimit.flood("flood:" + self._guest())
        if not wait:
            return False
        body = json.dumps({"error": "забагато запитів", "code": "too_many",
                           "wait": wait}, ensure_ascii=False).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Retry-After", str(wait))
        self.send_header("Content-Length", str(len(body)))
        self.close_connection = True      # не тримаємо з'єднання за собою
        self.end_headers()
        self.wfile.write(body)
        return True

    def _shot_reply(self, e):
        return self._json({"error": str(e), "code": e.code}, e.status)

    # ---------- вхід ----------
    def _add_cookie(self, c):
        self._pending = getattr(self, "_pending", []) + [c]

    def _session_cookie(self, user):
        return auth.cookie_header(auth.make_session(user["id"], gen=user["session_gen"]),
                                  secure=auth.is_https(self))

    def _enter(self, user, code=200):
        """Перший крок пройдено (пароль, посилання з листа, реєстрація).

        Без 2FA — одразу кука входу. З 2FA — лише пропуск на другий крок
        (HttpOnly-кука на 10 хвилин), а сторінка просить код."""
        if twofa.enabled(user):
            self._add_cookie(auth.pending_cookie(
                auth.make_pending(user["id"], user["session_gen"]), auth.is_https(self)))
            return self._json({"twofa": True}, code)
        return self._json({"user": user_public(user)}, code, cookie=self._session_cookie(user))

    def _needs_mail_code(self, user):
        """Пошта справжня, але ще не підтверджена — у журнал поки не пускаємо."""
        return authmail.has_email(user) and user["email_confirmed_at"] is None

    def _ask_mail_code(self, user, lang, code=200):
        """Шлемо код на пошту й просимо його ввести. Сесії ще немає — лише
        пропуск на цей крок у HttpOnly-куці.

        Лист — не частіше разу на хвилину на людину: інакше повторні входи
        засипали б скриньку листами й щоразу міняли код під пальцями."""
        keys = ["mailcode-send:%d" % user["id"]]
        if not ratelimit.check(keys, limit=1):
            ratelimit.miss(keys, limit=1)
            in_background(authmail.start_code, user, self._base(), lang)
        self._add_cookie(auth.mailcode_cookie(auth.make_mailcode(user["id"]), auth.is_https(self)))
        return self._json({"confirm": True, "email": user["email"]}, code)

    def _fresh_login(self, uid, extra=None):
        """Нове покоління входів: усі інші пристрої вилітають, цей лишається
        з новою кукою. Після зміни пароля, 2FA, «вийти на всіх пристроях»."""
        auth.bump_gen(uid)
        me = db.get_user(uid)
        out = {"user": user_public(me)}
        out.update(extra or {})
        return self._json(out, cookie=self._session_cookie(me))

    def _twofa_limit(self, uid):
        """Ліміт на коди: шість цифр перебирати по 5 на хвилину — роки."""
        keys = ["2fa:%d" % uid]
        wait = ratelimit.locked(keys)
        if wait:
            self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                        "code": "too_many", "wait": wait}, 429)
            return None
        return keys

    # Після скількох невдач за годину кажемо хазяїнові акаунта, що його
    # підбирають. Береться перша сходинка паузи: рівно з неї починається
    # те, чого звичайна забудькуватість не робить.
    GUESS_ALERT = ratelimit.STEPS[0][0]

    def _note_guessing(self, user, lang):
        """Порахувати невдалу спробу на сам акаунт і, якщо їх забагато,
        попередити хазяїна.

        Лист — не частіше разу на годину (notified_events), інакше
        попередження саме стало б розсилкою: сто спроб — сто листів.
        Помилка тут нічого не має ламати: людині вже відмовлено у вході,
        і це головне.
        """
        try:
            key = "user:%d" % user["id"]
            ratelimit.fail([key])
            if ratelimit.fails(key) < self.GUESS_ALERT:
                return
            hour = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H")
            if not db.record_notified(user["id"], "guess:" + hour, "guess"):
                return
            print("підбір пароля: %s, %d спроб за годину"
                  % (user["nickname"], ratelimit.fails(key)), flush=True)
            in_background(authmail.warn_guessing, user, ratelimit.fails(key),
                          self._base(), lang)
        except Exception as ex:
            print("підбір: не вдалось попередити —", ex, flush=True)

    def _settle_return(self):
        """Людина повернулась із каси: вмикаємо оплачене, не чекаючи вебхука.

        Порядок тут навмисний. Підпис в адресі доводить лише те, що назад
        її відправив Creem, а не те, що гроші дійшли: платіж міг лишитись
        в обробці. Тому підпис каже тільки, **у кого питати**, а вмикаємо
        за відповіддю їхнього API. Не підтвердив — не вмикаємо нічого,
        дочекається вебхука.

        Помилка тут не має ламати вхід у журнал: не змогли спитати —
        мовчки пропускаємо, підписку донесе вебхук.
        """
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if not creem.verify_return(q):
            print("повернення: підпис не зійшовся", flush=True)
            return
        uid = creem.who({"request_id": q.get("request_id", "")})
        sid = q.get("subscription_id", "")
        if not uid or not sid:
            return
        try:
            sub = creem.subscription(sid)
        except Exception as ex:
            print("повернення: не спитали Creem:", ex, flush=True)
            return
        status = str(sub.get("status") or "")
        if status not in creem.LIVE_STATUSES:
            print("повернення: підписка %s поки %r" % (sid, status), flush=True)
            return
        # Підпис міг бути справжній, але від іншої людини — звіряємо, що
        # підписка справді та, про яку йшлося в адресі.
        if creem.who(sub) not in (None, uid):
            print("повернення: підписка не тієї людини", flush=True)
            return
        try:
            db.set_creem_customer(uid, creem.customer_of(sub))
        except Exception as ex:
            print("повернення: не записав покупця:", ex, flush=True)
        try:
            billing.apply_paid(uid, creem.plan_of(sub) or "month",
                               creem.period_end(sub))
            # Номер підписки в журнал — без нього потім не скажеш, яку
            # саме оплату вмикали, а скасувати її на боці Creem можна
            # тільки за точним номером: списку за покупцем вони не дають.
            print("повернення: увімкнули оплачене для %s: %s, %s, до %s"
                  % (uid, sid, creem.plan_of(sub) or "month",
                     creem.period_end(sub)), flush=True)
        except Exception as ex:
            print("повернення: не застосував оплату:", ex, flush=True)

    def _uid(self):
        return auth.current_user_id(self)

    def _tz(self):
        """Часовий пояс того, хто прислав запит: ?tz=… або профіль."""
        raw = urllib.parse.parse_qs(urlparse(self.path).query).get("tz", [""])[0]
        user = None
        if not raw:
            uid = self._uid()
            if uid:
                try:
                    user = db.get_user(uid)
                except Exception:
                    user = None
        return request_tz(raw, user)

    def _cookie(self, name):
        try:
            jar = http.cookies.SimpleCookie()
            jar.load(self.headers.get("Cookie") or "")
            m = jar.get(name)
            return m.value if m else ""
        except Exception:
            return ""

    def _dev_cookie(self, mark):
        """Кука з відбитком пристрою на час походу в Google чи Discord.

        HttpOnly тут ні до чого — відбиток однаково рахує браузер, і
        приховувати від нього нічого. А от SameSite=Lax обов'язковий:
        повернення з сервісу — це перехід з чужого сайту, і при Strict
        кука до нас просто не доїхала б.
        """
        return ("%s=%s; Path=/; Max-Age=%d; SameSite=Lax"
                % (DEV_COOKIE, urllib.parse.quote(mark, safe=""), DEV_TTL)
                + ("; Secure" if auth.is_https(self) else ""))

    def _ref_query(self):
        """?ref=<партнер> у адресі — або нічого."""
        q = parse_qs(urlparse(self.path).query)
        return ref_norm((q.get("ref") or [""])[0])

    def _ref_touch(self, owner_ref=None):
        """Сторінка з міткою (своя в адресі або мітка хазяїна сторінки).
        Увійшов — мітка на акаунт, якщо порожньо. Гість — кука на 30 днів;
        наявну не перебиваємо: перша мітка головніша."""
        ref = self._ref_query() or (owner_ref or "")
        if ref not in ref_all():
            return
        uid = self._uid()
        if uid:
            ref_claim(uid, ref)
            return
        if self._cookie(REF_COOKIE) in ref_all():
            return
        parts = ["%s=%s" % (REF_COOKIE, ref), "Path=/", "SameSite=Lax", "Max-Age=%d" % REF_TTL]
        if auth.is_https(self):
            parts.append("Secure")
        self._pending = getattr(self, "_pending", []) + ["; ".join(parts)]

    def end_headers(self):
        """Відкладені Set-Cookie (мітка партнера) — до будь-якої відповіді,
        якою б гілкою вона не пішла."""
        for c in getattr(self, "_pending", []):
            self.send_header("Set-Cookie", c)
        self._pending = []
        # Захисні заголовки — тут, бо сюди проходить кожна відповідь.
        # nosniff: браузер не вгадує тип файлу (скрін не стане скриптом);
        # SAMEORIGIN: журнал не вбудувати в чужу сторінку під видом кнопок,
        # а свою можна — share.html кладе /demo фоном в iframe;
        # HSTS — лише на https, інакше локальний http зламався б.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", CSP)
        if auth.is_https(self):
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        BaseHTTPRequestHandler.end_headers(self)

    def _guest(self):
        """Адреса гостя. За проксі хостингу справжня приходить у заголовку,
        а client_address — це вже сам проксі, один на всіх.

        Заголовок можна підробити, тому на ньому одному не тримаємось:
        поруч рахуємо спроби ще й за логіном, і його підробкою не обійти.

        Беремо ОСТАННЄ значення, а не перше: перше пише сам клієнт (будь-яке,
        щоразу нове — і лічильник спроб не спрацьовував), а останнє дописує
        наш проксі, і його клієнт не підробить."""
        fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
        return fwd or (self.client_address[0] if self.client_address else "?")

    def _base(self):
        """Зовнішня адреса сайту: з PUBLIC_URL, інакше з заголовків — за
        проксі хостингу схема приходить в X-Forwarded-Proto."""
        if config.PUBLIC_URL:
            return config.PUBLIC_URL
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost"
        return "%s://%s" % (proto, host)

    # ---------- GET ----------
    # Чи живий сайт. Хостинг стукає сюди раз на кілька секунд і перезапускає
    # процес, якщо відповіді немає. Перевіряємо не тільки себе, а й базу:
    # сайт, який відповідає «живий» без бази, насправді не працює — людина
    # побачить порожній журнал замість своїх угод.
    #
    # Базу мацаємо не частіше разу на 10 секунд: стукають часто, а зайвий
    # запит на кожен стук — це навантаження на рівному місці.
    _health_lock = threading.Lock()
    _health = [0.0, False]            # коли перевіряли, що вийшло

    def _db_alive(self):
        now = time.time()
        with self._health_lock:
            when, ok = self._health
            if now - when < 10:
                return ok
        try:
            with db.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            ok = True
        except Exception:
            ok = False
        with self._health_lock:
            self._health[:] = [now, ok]
        return ok

    # ---------- замок на акаунт ----------
    # Ставить і знімає його тільки власник руками з /admin (db.set_lock).
    # Замкнених зазвичай немає взагалі, тому тримаємо їх у пам'яті й
    # перечитуємо раз на LOCK_TTL секунд: інакше кожен запит кожної людини
    # коштував би ще один SELECT заради стану, якого ні в кого немає.
    LOCK_TTL = 20
    _lock_gate = threading.Lock()
    _locks = [0.0, {}]                 # коли читали, {uid: текст}

    # Що працює й під замком: /api/auth/ — щоб було чим вийти, і
    # /api/admin/ — інакше власник, замкнувши сам себе помилково, не мав
    # би чим зняти. Вхід сюди можна було б і не вносити: він ходить без
    # сесії, а замок без неї нікого не знає.
    LOCK_FREE = ("/api/auth/", "/api/admin/")

    def _lock_note(self, uid):
        """Текст замка цієї людини або "" — замка немає."""
        now = time.time()
        with self._lock_gate:
            when, got = self._locks
            fresh = now - when < self.LOCK_TTL
        if fresh:
            return got.get(uid, "")
        try:
            got = db.locked_users()
        except Exception:
            # База не відповіла — замок не вигадуємо й не знімаємо:
            # лишаємо те, що знали востаннє.
            return self._locks[1].get(uid, "")
        with self._lock_gate:
            self._locks[:] = [now, got]
        return got.get(uid, "")

    def _locked_out(self, p):
        """True — запит далі не йде: на акаунті замок.

        Стоїть на /api/, а не на сторінках: сторінка має відкритись, щоб
        показати сам текст замка (lock.js), а зробити нею нічого не
        вийде — усі дії журналу ходять через /api/. Тому замок тримає
        сервер, і зняти його з консолі браузера неможливо.
        """
        if not p.startswith("/api/") or p.startswith(self.LOCK_FREE):
            return False
        uid = self._uid()
        if not uid:
            return False
        note = self._lock_note(uid)
        if not note:
            return False
        self._json({"error": note, "code": "locked"}, 403)
        return True

    def do_GET(self):
        if self._flooding(): return
        if self._old_host(): return
        p = unquote(urlparse(self.path).path)

        # ---- мітка партнера на початку шляху: /fxlab/u/dan, /bs/s/abc ----
        # Те саме, що «?ref=», тільки без хвоста в адресі: посиланням
        # діляться, і воно має виглядати охайно. Знявши мітку, далі
        # малюємо сторінку так, ніби її в адресі й не було.
        m = re.match(r"^/([A-Za-z0-9_-]{2,16})(/[^/].*)$", p)
        if m and not p.startswith("/api/") and ref_norm(m.group(1)):
            ref = ref_norm(m.group(1))
            uid0 = self._uid()
            if not (uid0 and _is_admin(uid0)):      # свої переходи не рахуємо
                ref_visit(ref, self.headers.get("User-Agent") or "")
            self._ref_touch(ref)
            u = urlparse(self.path)
            rest = u.path[len(m.group(1)) + 1:]     # шлях без «/<мітка>»
            self.path = rest + (("?" + u.query) if u.query else "")
            p = unquote(rest)

        # ?ref=<партнер> у будь-якій адресі — /, /login, /demo, /s/…
        if "ref=" in self.path and not p.startswith("/api/"):
            self._ref_touch()

        # Замок — після зняття мітки, а не до нього: мітка на початку
        # шляху переписує адресу, і «/fxlab/api/trades» стає «/api/trades»
        # уже тут. Перевірка до переписування дивилась би на шлях, якого
        # обробник не побачить, — і замок обходився б одним префіксом.
        if self._locked_out(p): return

        if p == "/health":
            if self._db_alive():
                return self._json({"ok": True})
            return self._json({"ok": False, "db": "no answer"}, 503)

        # ---- открыто всем: страница по ссылке и её снимок ----
        # картинка зі знімка: /api/share/<id>/shot/<файл>
        m = re.match(r"^/api/share/([A-Za-z0-9_-]{6,32})/shot/([\w.\-]{4,120})$", p)
        if m:
            rec = share_read(m.group(1))
            name = os.path.basename(m.group(2))
            if not rec or not share_shot_ok(rec, name):
                self.send_response(404); self.end_headers(); return
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            return self._file(path, ctype, self.PRIVATE)

        # аватарка автора знімка: /api/share/<id>/avatar
        m = re.match(r"^/api/share/([A-Za-z0-9_-]{6,32})/avatar$", p)
        if m:
            rec = share_read(m.group(1))
            uid_a = rec and rec.get("user_id")
            user = db.get_user(uid_a) if uid_a else None
            av = user and user.get("avatar")
            if not av:
                self.send_response(404); self.end_headers(); return
            if av.startswith("preset:"):
                name = av[len("preset:"):]
                if name not in AVATAR_PRESETS:
                    self.send_response(404); self.end_headers(); return
                # кеш короткий: поміняв аватарку — гості побачать нову
                return self._file(os.path.join(STATIC, "avatars", name + ".svg"),
                                  "image/svg+xml", "private, max-age=300")
            got = filestore.get(os.path.basename(av))
            if not got:
                self.send_response(404); self.end_headers(); return
            mime, blob = got
            ext = av.rsplit(".", 1)[-1].lower()
            ctype = mime or {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                             "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            self.wfile.write(blob)
            return

        if p.startswith("/api/share/"):
            rec = share_read(p[len("/api/share/"):])
            if rec is None:
                return self._json({"error": "посилання не знайдено або прострочене"}, 404)
            # Хазяїна віддаємо ніком і тільки поки журнал відкритий: id
            # користувача назовні не потрібен, а стан питаємо щоразу заново.
            out = {k: v for k, v in rec.items() if k != "user_id"}
            ref = ref_of_user(rec.get("user_id"))
            if ref:
                out["ref"] = ref_short(ref)  # сторінка допише ?ref= в адресу
            nick = public_owner(rec.get("user_id"))
            if nick:
                out["owner"] = {"nick": nick}
            if ts_copy_ok(rec):
                out["ts_copy"] = True
            author = share_author(rec.get("user_id"))
            if author:
                out["author"] = author
            return self._json(out)
        if p.startswith("/s/"):
            sid = p[len("/s/"):].strip("/")
            rec = share_read(sid)
            try:
                with open(os.path.join(STATIC, "share.html"), "rb") as f:
                    html = f.read().decode("utf-8")
            except Exception:
                self.send_response(404); self.end_headers(); return
            if rec:
                # гості хазяїна рахуються його партнерові
                self._ref_touch(ref_of_user(rec.get("user_id")))
                share_store.hit(sid, self.headers.get("User-Agent") or "")
                proto = self.headers.get("X-Forwarded-Proto") or "http"
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
                base = "%s://%s" % (proto, host)
                d = rec.get("data") or {}
                # Назву знімка пише людина, а звідси вона їде прямо в HTML:
                # екрануємо все, а не саме "<" — інакше лапка чи "&" псують
                # розмітку сусідніх тегів.
                html = html.replace("<title>StatsAI</title>",
                                    "<title>%s · StatsAI</title>"
                                    % html_escape(d.get("title") or "StatsAI"), 1)
                html = html.replace("</head>", share_og(rec, sid, base) + "\n</head>", 1)
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        # ---- вхід через сервіси (oauth.py) ----
        if p == "/api/auth/providers":
            on = oauth.enabled()
            return self._json({"providers": on})

        m = re.match(r"^/auth/(google|discord)$", p)
        if m:
            prov = m.group(1)
            if not oauth.enabled().get(prov):
                return self._redirect("/login?err=off")
            url, state = oauth.start_url(prov, self._base())
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("Set-Cookie", oauth.state_cookie(state, auth.is_https(self)))
            # Відбиток пристрою кладемо кукою по дорозі в сервіс: назад
            # людина повернеться вже з чужого сайту, і в тому запиті від нас
            # лишаться самі куки. Сторінка входу додає його до адреси.
            dev = (parse_qs(urlparse(self.path).query).get("dev", [""])[0] or "")[:512]
            if dev:
                self.send_header("Set-Cookie", self._dev_cookie(dev))
            self.end_headers()
            return

        m = re.match(r"^/auth/(google|discord)/callback$", p)
        if m:
            prov = m.group(1)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urlparse(self.path).query).items()}
            try:
                cookies = self.headers.get("Cookie") or ""
                st = ""
                for part in cookies.split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "oauth_state":
                        st = v
                if q.get("error") or not oauth.check_state(q.get("state"), st):
                    raise ValueError("вхід скасовано або сплив час")
                ext_id, email, name = oauth.fetch_profile(prov, q.get("code", ""), self._base())
                if not ext_id:
                    raise ValueError("сервіс не віддав профіль")
                # Відбиток пристрою на переадресації взятися нізвідки — його
                # кладе кукою сама сторінка входу, перед тим як відправити
                # людину в сервіс. Без цього вхід через Google був широкою
                # хвірткою повз заслон: новий акаунт там робиться за хвилину.
                ip = self._guest()
                device = antifraud.device_hash(
                    urllib.parse.unquote(self._cookie(DEV_COOKIE)))
                user = oauth.find_or_create_user(
                    prov, ext_id, email, name,
                    guard=lambda: bool(antifraud.blocked(ip, device, email)))
                try:
                    antifraud.remember(user["id"], ip, device)
                except Exception as ex:
                    print("antifraud oauth:", ex)
                ref_claim(user["id"], self._cookie(REF_COOKIE))
            except oauth.Blocked:
                print("oauth %s: другий безкоштовний акаунт" % prov)
                self.send_response(302)
                self.send_header("Location", "/login?err=ip_taken")
                self.send_header("Set-Cookie", oauth.clear_state_cookie(auth.is_https(self)))
                self.end_headers()
                return
            except Exception as ex:
                print("oauth %s: %s" % (prov, ex))
                self.send_response(302)
                self.send_header("Location", "/login?err=oauth")
                self.send_header("Set-Cookie", oauth.clear_state_cookie(auth.is_https(self)))
                self.end_headers()
                return
            self.send_response(302)
            if twofa.enabled(user):
                # Сервіс підтвердив, хто це, але 2FA — властивість акаунта,
                # а не способу входу: код просимо і тут.
                self.send_header("Location", "/login?twofa=1")
                self.send_header("Set-Cookie", auth.pending_cookie(
                    auth.make_pending(user["id"], user["session_gen"]), auth.is_https(self)))
            else:
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", self._session_cookie(user))
            self.send_header("Set-Cookie", oauth.clear_state_cookie(auth.is_https(self)))
            self.end_headers()
            return

        if p == "/api/prefs":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"prefs": prefs_get(uid)})

        # ---- звідки про нас дізнались: лише власникам ----
        # ---- відписка з листа: без входу, за підписаним посиланням ----
        if p == "/unsub":
            qs = parse_qs(urlparse(self.path).query)
            ok = mailout.unsubscribe((qs.get("u") or [""])[0], (qs.get("t") or [""])[0])
            text = ("Готово — больше не пришлём писем с новостями. Вернуть можно в профиле журнала."
                    if ok else "Ссылка не сработала. Отписаться можно в профиле журнала.")
            data = ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
                    '<title>StatsAI</title><body style="font-family:Segoe UI,Arial,sans-serif;background:#0d0f12;color:#e8eaee;'
                    'display:grid;place-items:center;min-height:90vh;margin:0;padding:16px"><div style="max-width:420px;text-align:center">'
                    '<h2>Stats<span style="color:#3ccf8e">AI</span></h2><p style="line-height:1.6">%s</p>'
                    '<p><a href="/" style="color:#3ccf8e">Открыть журнал</a></p></div></body>' % _html.escape(text)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if p == "/admin/mail":
            uid = self._uid()
            if not uid:
                return self._redirect("/login")
            if not _is_admin(uid):
                self.send_response(403); self.end_headers(); return
            data = admin_page.mail_page(mailout.stats(), mailout.AUDIENCES, list(ref_all()),
                                        REF_TITLES, bool(config.RESEND_API_KEY)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        # ---- службова сторінка з цифрами: лише власникам ----
        if p == "/admin":
            uid = self._uid()
            if not uid:
                return self._redirect("/login")
            if not _is_admin(uid):
                seclog.event("адмінка", False, user=db.get_user(uid), ip=self._guest())
                self.send_response(403); self.end_headers(); return
            seclog.event("адмінка", True, user=db.get_user(uid), ip=self._guest())
            # панель цифр малює admin_page.py; ?q= — підставити пошук
            query = urllib.parse.parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            data = admin_page.dashboard(query, REF_TITLES, KIND_RU, list(ref_all())).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        # ---- картка користувача: лише власникам ----
        m = re.match(r"^/admin/u/([^/\x00-\x1f]{1,40})/?$", p)
        if m:
            uid = self._uid()
            if not uid:
                return self._redirect("/login")
            if not _is_admin(uid):
                self.send_response(403); self.end_headers(); return
            nick = unquote(m.group(1))
            u = None
            try:
                u = db.get_user_by_nick(nick) or db.get_user_by_email(nick)
            except Exception:
                u = None
            if not u:
                data = admin_page.not_found(nick).encode("utf-8")
                self.send_response(404)
            else:
                data = admin_page.user_card(u, REF_TITLES, KIND_RU,
                                           list(ref_all()),
                                           _billing_block(u) + _ts_restore_block(u)).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        # ---- скільки людей за кожним партнером: лише адмінам ----
        if p == "/api/admin/refs":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not _is_admin(uid):
                return self._json({"error": "forbidden"}, 403)
            with db.connect() as conn:
                rows = conn.execute("""
                    SELECT coalesce(ref_source, '') AS ref,
                           count(*) AS n,
                           count(*) FILTER (WHERE ref_at >= date_trunc('month', now())) AS month,
                           count(*) FILTER (WHERE ref_at >= now() - interval '30 days') AS d30
                    FROM users GROUP BY 1 ORDER BY n DESC""").fetchall()
            out = [{"ref": r["ref"], "n": r["n"], "month": r["month"], "d30": r["d30"]} for r in rows]
            return self._json({"rows": out, "total": sum(r["n"] for r in out)})

        if p == "/api/auth/me":
            uid = self._uid()
            user = db.get_user(uid) if uid else None
            return self._json({"user": user_public(user) if user else None})

        # ---- чужий відкритий журнал ----
        #
        # Закритий журнал і неіснуючий нік відповідають однаково — 404. Так
        # по чужому ніку не можна навіть дізнатись, що така людина є.
        m = re.match(r"^/api/u/([^/\x00-\x1f]{1,40})(/trades)?$", p)
        if m:
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            owner = db.get_user_by_nick(m.group(1))
            if not owner or not owner["public_journal"]:
                return self._json({"error": "not found"}, 404)
            trades = [public_trade(t) for t in db.list_trades(owner["id"])
                      if not t.get("hidden")]
            if m.group(2):
                return self._json(trades)
            dates = sorted(t["date"] for t in trades if t.get("date"))
            return self._json({"nick": owner["nickname"], "count": len(trades),
                               "since": dates[0][:10] if dates else "",
                               "me": owner["id"] == uid})

        # картинка з чужого журналу: /ushot/<нік>/<файл>
        m = re.match(r"^/ushot/([^/\x00-\x1f]{1,40})/([\w.\-]{4,120})$", p)
        if m:
            uid = self._uid()
            owner = db.get_user_by_nick(m.group(1)) if uid else None
            name = os.path.basename(m.group(2))
            if not owner or not db.public_screenshot(owner["id"], name):
                self.send_response(404); self.end_headers(); return
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            return self._file(path, ctype, self.PRIVATE)

        if p == "/api/trades":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            # Журнал переключается между реальной торговлей и бэктестом целиком.
            # Без параметра — торговля, как было до появления бэктеста.
            kind = "bt" if (parse_qs(urlparse(self.path).query).get("kind")
                            or [""])[0] == "bt" else ""
            return self._json(db.list_trades(uid, kind))

        # ---- рахунки: свій депозит і проп-фірми (accounts_store.py) ----
        #
        # Тільки описи рахунків. Гроші й просадка рахуються в браузері з
        # угод, які вже поїхали окремим запитом: другий раз ті самі угоди
        # ганяти по мережі нема сенсу.
        if p == "/api/accounts":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"accounts": accounts_store.lst(uid)})

        # ---- журнали бектесту (bt_journals_store.py) ----
        if p == "/api/bt/journals":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"journals": bt_journals_store.lst(uid)})

        # ---- нотатки (notes_store.py) ----
        if p == "/api/notes":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"notes": notes_store.lst(uid)})

        if p.startswith("/api/day/"):
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            rest = p[len("/api/day/"):]
            if rest == "list":
                return self._json({"days": day_store.days(uid)})
            if rest == "stats":
                # ?since=YYYY-MM-DD — для знімка місяця; без нього останні 30 днів
                want = urllib.parse.parse_qs(urlparse(self.path).query).get("since", [""])[0]
                since = want if day_store.valid_date(want) else \
                    (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
                return self._json({"notes": day_store.notes_since(uid, since), "since": since})
            if not day_store.valid_date(rest):
                return self._json({"error": "bad date"}, 400)
            return self._json({"day": day_store.get(uid, rest)})

        # ---- профіль: цифри, перевірка ніка, фото ----
        if p == "/api/me/profile":
            uid = self._uid()
            me = db.get_user(uid) if uid else None
            if not me:
                return self._json({"error": "auth required"}, 401)
            tz = request_tz(None, me)
            today = datetime.datetime.now(tz).date()
            stats = db.profile_stats(uid, today, tz=tz)
            joined = me["created_at"].astimezone(request_tz(None, me)).date() if me["created_at"] else today
            stats["with_us"] = (today - joined).days + 1
            return self._json({"user": user_public(me), "stats": stats})

        if p == "/api/me/nick-check":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            want = parse_qs(urlparse(self.path).query).get("n", [""])[0].strip()
            return self._json({"code": nick_problem(want, uid)})

        if p.startswith("/api/me/avatar/"):
            uid = self._uid()
            me = db.get_user(uid) if uid else None
            name = os.path.basename(p[len("/api/me/avatar/"):])
            if not me or not name or name != me["avatar"]:
                self.send_response(404); self.end_headers(); return
            got = filestore.get(name)
            if not got:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", got[0])
            self.send_header("Content-Length", str(len(got[1])))
            # ім'я файла міняється з кожним новим фото — кешувати можна довго
            self.send_header("Cache-Control", self.PRIVATE)
            self.end_headers()
            self.wfile.write(got[1])
            return

        if p.startswith("/dnshot/"):
            uid = self._uid()
            name = os.path.basename(p[len("/dnshot/"):])
            if not uid or not day_store.owns_shot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype, self.PRIVATE)

        # ---- торгова стратегія (ts_store.py, ts_notion.py) ----
        if p == "/api/ts":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            # у бектесті своя копія ТС: перший захід знімає її з реальної,
            # далі це два окремі документи
            qs = parse_qs(urlparse(self.path).query)
            kind = "bt" if (qs.get("kind") or [""])[0] == "bt" else ""
            return self._json({"ts": ts_store.get(uid, kind, sid=(qs.get("sid") or ["0"])[0])})

        if p == "/api/ts/list":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"list": ts_store.lst(uid)})

        if p.startswith("/tsshot/"):
            uid = self._uid()
            name = os.path.basename(p[len("/tsshot/"):])
            if not uid or not ts_store.owns_shot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype, self.PRIVATE)

        # ---- зліпок журналу собі на диск (backup.py) ----
        # Той самий вміст, що лягає в щоденний зліпок: угоди, розбори днів,
        # стратегія. Один файл, який відкриє будь-що, — і журнал уже не
        # тільки в нашій базі.
        if p == "/api/export":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            snap = backup.snapshot(uid)
            data = json.dumps(snap, ensure_ascii=False, indent=1).encode("utf-8")
            name = "journal-%s.json" % datetime.date.today().isoformat()
            enc = self._squeeze(data)
            if enc is not None:
                data = enc
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="%s"' % name)
            if enc is not None:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if p == "/api/backups":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            try:
                have = backup.listing(uid)
            except Exception as ex:
                print("backups:", ex)
                have = []
            return self._json({"backups": have, "keep": backup.KEEP})

        if p == "/api/billing/state":
            # Стан підписки для браузера: тариф, дата, ціни саме цієї людини
            # і скільки лишилось звернень до моделі. Залишку угод тут немає —
            # лічильника ми не показуємо ніде (див. billing.public).
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            out = billing.public(uid)
            # Друга каса поруч із карткою. Якщо людина вже виставила
            # рахунок і зараз переказує гроші, віддаємо його тут же:
            # сторінка перемалює очікування навіть після перезавантаження.
            out["crypto"] = crypto_pay.enabled()
            # Чи працює каса картками. Без цього сторінка показувала
            # плитку «Карткою» завжди, і натиснута без ключа вона
            # відповідала помилкою в підвалі розділу — тобто нічим.
            out["card"] = creem.enabled()
            if out["crypto"]:
                inv = crypto_pay.current(uid)
                if inv:
                    out["invoice"] = crypto_pay.public(inv)
            return self._json(out)

        if p == "/api/calendar":
            # Розділу «Новини» віддаємо рівно один робочий тиждень: усередині
            # ми знаємо більше (фід плюс дні вперед з TradingView), і без
            # цього зрізу стрічка днів угорі розділу тягнулась на два тижні.
            # Вікно ріжемо в поясі того, хто дивиться: у Нью-Йорку київський
            # ранок понеділка — це ще вечір неділі, і без цього в стрічку
            # лізли вихідні, яких ми там не хочемо.
            events, warn = calendar_events()
            return self._json({"events": calendar_feed.week_only(events, tz=self._tz()),
                               "warning": warn})

        # Історія однієї події: попередні випуски з архіву календаря.
        # Відкрито всім, як і сам календар: це чужі публічні дані,
        # нічого свого журналу тут немає.
        if p == "/api/calendar/event":
            q = urllib.parse.parse_qs(urlparse(self.path).query)
            country = (q.get("country") or [""])[0]
            title = (q.get("title") or [""])[0]
            mine = None
            for one in calendar_feed.cached_events():
                if (one.get("country") or "") == country and (one.get("title") or "") == title:
                    mine = one
                    break
            rows, src = [], "tv"
            if mine:
                try:
                    rows = tv_calendar.history(mine)
                except Exception as ex:
                    print("history:", ex)
            if not rows:
                # свій архів: він тонкий, зате точно про цю ж подію
                rows, src = event_history(country, title), "archive"
            return self._json({"history": rows, "source": src})

        if p == "/api/tidy":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"groups": tidy.scan(db.list_trades(uid))})

        if p == "/api/notion/state":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            conf = notion_conf(uid)
            sources = notion_sources(uid, conf)
            # `last` оставлен для окна, которое браузер мог взять из кэша:
            # в новом список источников заменяет его целиком
            last = sources[0] if sources else None
            return self._json({
                "url": conf.get("url") or "",
                "title": conf.get("title") or "",
                "sources": sources,
                "last": last,
                "mapping": conf.get("mapping") or {},
                # Підключено — це коли є база, з якої ми оновлюємось. Угоди,
                # перенесені колись, лишаються в журналі назавжди й про
                # підключення не говорять нічого.
                "connected": bool(sources),
                # а це — «людина вже переносила»: вікно-пропозиція новачкові
                # більше не потрібне
                "imported": bool(db.notion_known(uid)[1]),
                "fields": [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS],
            })

        if p.startswith("/api/notion/job/"):
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            with _jobs_lock:
                job = _jobs.get(p[len("/api/notion/job/"):])
            if not job or getattr(job, "user_id", None) != uid:
                return self._json({"error": "завдання не знайдено"}, 404)
            return self._json(job.snapshot())

        # Публічні сторінки. Приватність і умови вимагає Google для входу
        # через акаунт; умови, тарифи й повернення — платіжний сервіс під
        # час перевірки сайту. Адреси без .html: так вони роздаються давно,
        # і посилання на них уже розійшлись.
        if p in ("/privacy", "/terms", "/refund", "/pricing"):
            return self._file(os.path.join(STATIC, p.strip("/") + ".html"), "text/html; charset=utf-8")

        # Ярлик на телефоні. Коли на сторінці немає посилання на іконку —
        # або воно не встигло завантажитись — Safari шукає її в корені
        # сайту. Там був 404, і iOS малювала на робочому столі саму лише
        # літеру «S» замість нашого знака.
        if p in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            return self._file(os.path.join(STATIC, "apple-touch-icon.png"),
                              "image/png", cache="public, max-age=86400")

        # Перехід із листа: гасимо посилання, ставимо позначку й ведемо
        # на сторінку входу — там людина побачить, що пошту прийнято.
        # Робимо це на GET, хоч посилання й відкриє будь-хто, кому лист
        # потрапив до рук (буває, що поштові сторожі відкривають посилання
        # самі): нічого небезпечного за ним немає — тільки підтвердження,
        # якого ми й домагаємось.
        if p == "/confirm":
            args = urllib.parse.parse_qs(urlparse(self.path).query)
            token = (args.get("t") or [""])[0].strip()
            user = db.take_link(authmail.token_hash(token), "confirm") if token else None
            if not user:
                return self._redirect("/login?err=confirm")
            db.confirm_email(user["id"])
            return self._redirect("/login?ok=confirmed")

        # Сторінка нового пароля — та сама сторінка входу: вона побачить
        # у адресі ключ і сама покаже потрібні поля.
        if p in ("/login", "/reset"):
            # Месенджери хочуть в og:image повну адресу, а у файлі вона
            # відносна — сторінка ж не знає, під яким доменом її відкриють.
            # Дописуємо базу на віддачі.
            try:
                with open(os.path.join(STATIC, "login.html"), "r", encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                self.send_response(404); self.end_headers(); return
            # партнерське посилання (?ref=blackswan): прев'ю і назва — в стилі
            # колаборації, щоб у чаті спільноти картка була «наша × їхня»
            ref = self._ref_query()
            og_path = os.path.join(STATIC, "og-%s.png" % ref) if ref else ""
            if ref and os.path.exists(og_path):
                title = PARTNER_TITLES.get(ref, ref)
                # Слово «коллаборация» — в самом описании: в чате сообщества
                # карточку видят те, кто пришёл от партнёра, и первое, что
                # они должны понять, — это совместное, а не реклама мимо.
                desc = ("Коллаборация StatsAI и %s. Журнал трейдера: сделки, "
                        "статистика, анализ дня и своя ТС." % title)
                # у адресі картинки — час її зміни: месенджери кешують прев'ю за
                # адресою, і без цього нова картинка не показувалась
                html = html.replace("/static/og-main.png",
                                    "/static/og-%s.png?v=%d" % (ref, int(os.path.getmtime(og_path))))
                for attr in ('property="og:title"', 'name="twitter:title"'):
                    html = re.sub(r'(%s content=")[^"]*' % re.escape(attr),
                                  lambda m: m.group(1) + "StatsAI × " + title, html, 1)
                for attr in ('property="og:description"', 'name="twitter:description"'):
                    html = re.sub(r'(%s content=")[^"]*' % re.escape(attr),
                                  lambda m: m.group(1) + desc, html, 1)
            # головна картинка теж із часом зміни в адресі: месенджери кешують
            # прев'ю за адресою, і перемальована картинка інакше не показувалась.
            # Після партнерського блоку: там її вже підмінено на свою.
            main_og = os.path.join(STATIC, "og-main.png")
            if os.path.exists(main_og):
                html = html.replace('"/static/og-main.png"',
                                    '"/static/og-main.png?v=%d"' % int(os.path.getmtime(main_og)))
            html = html.replace('content="/static/',
                                'content="%s/static/' % html_escape(self._base()))
            if 'property="og:url"' not in html:
                html = html.replace("</title>",
                                    '</title>\n<meta property="og:url" content="%s/">' % html_escape(self._base()), 1)
            body = html.encode("utf-8")
            enc = self._squeeze(body)
            if enc is not None:
                body = enc
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if enc is not None:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if p.startswith("/design/"):
            # прототипы: экран входа, новости, знак — чтобы смотреть с того же адреса.
            # Це чернетки майбутніх розділів, і лежать вони на бойовому
            # сайті. Стороннім там робити нічого, тому показуємо тільки
            # своїм — рядок нижче прибрати, якщо треба комусь показати.
            if not _is_admin(self._uid()):
                self.send_response(404); self.end_headers(); return
            full = under(os.path.join(ROOT, "design"), p[len("/design/"):])
            if not full:
                self.send_response(403); self.end_headers(); return
            if os.path.isdir(full):
                full = os.path.join(full, "index.html")
            ext = full.rsplit(".", 1)[-1].lower()
            ctype = {"html":"text/html; charset=utf-8","css":"text/css; charset=utf-8",
                     "js":"application/javascript; charset=utf-8","json":"application/json; charset=utf-8",
                     "svg":"image/svg+xml","png":"image/png","md":"text/plain; charset=utf-8"
                     }.get(ext, "application/octet-stream")
            return self._file(full, ctype)

        if p.startswith("/shots/"):
            uid = self._uid()
            name = os.path.basename(p[len("/shots/"):])
            # скриншот отдаём только владельцу сделки, в которой он числится
            if not uid or not db.owns_screenshot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
                     "webp":"image/webp","gif":"image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype, self.PRIVATE)

        # Чужий журнал — та сама сторінка застосунку: розділи, календар і
        # аналітика вже вміють малювати будь-який список угод. Хто саме
        # хазяїн і що можна робити, розбирає pub.js за адресою.
        #
        # Нік у адресі беремо будь-який, крім скісної риски: при реєстрації
        # його не звужували, тому там бувають пробіли й кирилиця ("Artur
        # Rafaelian"). Далі він іде тільки в запит до бази за точним збігом,
        # у файлові шляхи не потрапляє.
        if re.match(r"^/u/[^/\x00-\x1f]{1,40}/?$", p):
            try:
                owner = db.get_user_by_nick(p[len("/u/"):].strip("/"))
                self._ref_touch(owner and owner["ref_source"])
            except Exception:
                pass
            return self._file(os.path.join(STATIC, "index.html"),
                              "text/html; charset=utf-8")

        # ---- коротке партнерське посилання: /bs ----
        m = re.match(r"^/([A-Za-z0-9_-]{2,16})/?$", p)
        if m:
            ref = ref_norm(m.group(1))
            if ref:
                uid0 = self._uid()
                if not (uid0 and _is_admin(uid0)):      # свої переходи не рахуємо
                    ref_visit(ref, self.headers.get("User-Agent") or "")
                self._ref_touch(ref)
                if self._uid():
                    return self._redirect("/")
                # на сторінку входу ведемо з повною міткою: звідти месенджер
                # бере прев'ю в оформленні партнера
                return self._redirect("/login?ref=" + ref)

        if p in ("/", "/index.html"):
            # Повернення з каси: ?paid=1 з їхнім підписом. Робимо це до
            # входу — людина могла повернутись у браузер без сесії, а
            # оплата від цього не менш справжня.
            if "paid=1" in (urlparse(self.path).query or ""):
                try:
                    self._settle_return()
                except Exception as ex:
                    print("повернення:", ex, flush=True)
            if not self._uid():
                # ?ref=партнер лишаємо в адресі: месенджер іде за редіректом і
                # бере прев'ю вже зі сторінки входу — там воно в стилі партнера
                q = urlparse(self.path).query
                if q:
                    return self._redirect("/login?" + q)
                # гість без позначок бачить стартову сторінку
                return self._landing()
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")

        if p == "/landing":
            # стартова сторінка й для того, хто вже увійшов, — подивитись, як її бачать гості
            return self._landing()

        if p == "/demo":
            # Журнал без акаунта, на демонстраційних даних. Сюди ведуть
            # сторінка «поділитись» і посилання зі сторінки входу. Сторінка
            # сама зрозуміє, що сесії немає (/api/trades віддасть 401), і
            # ввімкне режим гостя: дивитись можна все, писати — ні.
            if self._uid():
                return self._redirect("/")
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")

        if p.startswith("/static/"):
            full = under(STATIC, p[len("/static/"):])
            if not full:
                self.send_response(403); self.end_headers(); return
            name = os.path.relpath(full, STATIC).replace("\\", "/")
            # Чернетки й службове (_test.html, .rej, .txt) назовні не віддаємо
            base = name.rsplit("/", 1)[-1]
            if base.startswith("_") or base.startswith(".") or \
                    base.rsplit(".", 1)[-1].lower() in ("rej", "txt", "md", "py"):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"css":"text/css; charset=utf-8","js":"application/javascript; charset=utf-8",
                     "html":"text/html; charset=utf-8","png":"image/png","svg":"image/svg+xml",
                     "webp":"image/webp","mp4":"video/mp4"}.get(ext,"application/octet-stream")
            # у файлів є версія в адресі (?v=5), тому кешуємо назавжди:
            # правка версії сама змусить браузер піти за новим
            versioned = "v=" in urlparse(self.path).query
            cache = self.FOREVER if versioned else None
            if ctype.startswith("video/"):
                return self._media(full, ctype, cache)
            return self._file(full, ctype, cache)

        self.send_response(404); self.end_headers()

    # ---------- POST ----------
    def do_POST(self):
        if self._flooding(): return
        if self._old_host(): return
        p = urlparse(self.path).path
        body = self._body()
        if self._too_big:
            return self._too_big_reply()
        # Після читання тіла, а не до нього: відповісти, не забравши
        # надіслані байти, означає лишити їх у з'єднанні — наступний запит
        # почався б з їхньої середини.
        if self._locked_out(p): return

        # ---- вход и регистрация ----
        # ---- поправити мітку руками: лише власникам ----
        # ---- каса ----
        if p == "/api/billing/checkout":
            # Створюємо оплату й віддаємо адресу, куди відправити людину.
            # Разом з оплатою йде її номер у нашій базі — інакше, коли
            # прийде підтвердження, ми знатимемо, що хтось заплатив, але
            # не знатимемо хто.
            uid = self._uid()
            # Каса — місце, де скарга «натискаю, нічого не відбувається»
            # нерозрізненна з «натискаю, і запит не доходить». Решта логу
            # тут мовчить (log_message заглушений), тому кожен захід у касу
            # лишає рядок: видно і сам факт натискання, і чим воно скінчилось.
            print("каса: захід, uid=%s, тариф=%r" % (
                uid, (body or {}).get("plan") if isinstance(body, dict) else None),
                flush=True)
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not creem.enabled():
                print("каса: ключа Creem немає — 503", flush=True)
                return self._json({"error": "оплата ще не ввімкнена",
                                   "code": "no_pay"}, 503)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            plan = str(body.get("plan") or "").strip()
            if plan not in billing.PLANS:
                print("каса: тариф %r не наш — 400" % plan, flush=True)
                return self._json({"error": "невідомий тариф"}, 400)
            try:
                u = db.get_user(uid) or {}
                url = creem.checkout(uid, plan,
                                     price_set=(u.get("price_plan") or "std"),
                                     email=u.get("email") or "",
                                     discount=billing.promo_discount(u, plan))
            except Exception as ex:
                print("checkout:", ex, flush=True)
                return self._json({"error": "не вдалося відкрити оплату",
                                   "code": "pay_failed"}, 502)
            print("каса: відкрили, тариф=%s" % plan, flush=True)
            return self._json({"url": url})

        # ---- оплата криптою ----
        if p == "/api/billing/crypto":
            # Виставляємо рахунок: адреса, сума й скільки її чекати.
            # Далі людина переказує USDT звідки їй зручно й може закрити
            # вкладку — підписку ввімкне фоновий обхід, а не ця сторінка.
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not crypto_pay.enabled():
                return self._json({"error": "оплата криптою ще не ввімкнена",
                                   "code": "no_pay"}, 503)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            plan = str(body.get("plan") or "").strip()
            if plan not in billing.PLANS:
                return self._json({"error": "невідомий тариф"}, 400)
            # Кожен рахунок — рядок у базі й зайнята сума. Передумувати
            # можна скільки завгодно, але не сто разів на хвилину.
            keys = ["cinv:%s" % uid]
            wait = ratelimit.check(keys, limit=20)
            if wait:
                return self._json({"error": "зачекай %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys, limit=20)
            inv = crypto_pay.create(uid, plan)
            if not inv:
                return self._json({"error": "не вдалося виставити рахунок",
                                   "code": "pay_failed"}, 502)
            return self._json(crypto_pay.public(inv))

        if p == "/api/billing/crypto/cancel":
            # «Передумав». Рахунок гасне, але не зникає: переказ, який уже
            # пішов, усе одно знайде його й увімкне підписку.
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            crypto_pay.cancel(uid)
            return self._json({"ok": True, "state": billing.public(uid)})

        if p == "/api/billing/crypto/claim":
            # «Я оплатив, ось номер переказу» — запасний шлях для того, хто
            # округлив суму: за сумою такий переказ не знайти, за номером —
            # можна. Номер перевіряємо в блокчейні, на слово не віримо.
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            keys = ["claim:%s" % uid]
            wait = ratelimit.check(keys, limit=10)
            if wait:
                return self._json({"error": "зачекай %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys, limit=10)
            txid = str((body or {}).get("tx") or "").strip()
            ok, why = crypto_pay.claim(uid, txid)
            if not ok:
                return self._json({"error": "переказ не підійшов",
                                   "code": why}, 404 if why == "not_found" else 409)
            return self._json({"ok": True, "state": billing.public(uid)})

        # ---- кабінет підписки ----
        if p == "/api/billing/portal":
            # Скасувати продовження чи змінити картку людина має вміти сама,
            # без листів у підтримку. Робить це кабінет Creem — ми лише
            # беремо разове посилання туди.
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not creem.enabled():
                return self._json({"error": "оплата ще не ввімкнена",
                                   "code": "no_pay"}, 503)
            cid = (db.get_user(uid) or {}).get("creem_customer") or ""
            if not cid:
                # Людина ще не платила — кабінету в неї просто немає.
                return self._json({"error": "немає оплат",
                                   "code": "no_customer"}, 404)
            try:
                url = creem.portal(cid)
            except Exception as ex:
                print("portal:", ex, flush=True)
                return self._json({"error": "не вдалося відкрити кабінет",
                                   "code": "portal_failed"}, 502)
            return self._json({"url": url})
        # ---- підтвердження оплати від Creem ----
        if p == "/api/creem/webhook":
            # Єдина точка, куди стукає платіжка. Статичних адрес у їхніх
            # запитів немає, тому відсіяти чужих можна тільки підписом.
            raw = getattr(self, "_raw_body", b"")
            if not creem.verify(raw, self.headers.get("creem-signature") or ""):
                print("webhook: підпис не зійшовся", flush=True)
                return self._json({"error": "bad signature"}, 400)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)

            ev = str(body.get("eventType") or body.get("type")
                     or body.get("event") or "")
            ev_id = str(body.get("id") or body.get("event_id") or "")
            obj = body.get("object") or body.get("data") or {}
            if not isinstance(obj, dict):
                obj = {}
            uid = creem.who(obj)

            # Повторна доставка тієї самої події не має продовжити підписку
            # вдруге. Ключ — id події; якщо такий уже лежить, просто мовчки
            # погоджуємось, інакше Creem повторюватиме ще і ще.
            if ev_id:
                try:
                    fresh = db.payment_once(
                        ev_id, uid, ev,
                        amount_cents=(obj.get("amount") or obj.get("total")),
                        currency=(obj.get("currency") or "EUR"), raw=body)
                except Exception as ex:
                    print("webhook: не записав подію:", ex, flush=True)
                    fresh = True
                if not fresh:
                    return self._json({"ok": True, "repeat": True})

            print("webhook: %s для %s" % (ev, uid), flush=True)
            # Номер покупця на боці Creem приходить з кожною подією, а
            # потрібен, щоб відкрити людині її кабінет. Запам'ятовуємо мовчки:
            # не вийшло — це не привід відмовляти в оплаті.
            if uid:
                try:
                    db.set_creem_customer(uid, creem.customer_of(obj))
                except Exception as ex:
                    print("webhook: не записав покупця:", ex, flush=True)
            if not uid:
                # Без номера людини робити нічого не можемо, але відповідаємо
                # згодою: подія записана, розберемо руками в адмінці.
                return self._json({"ok": True, "unknown_user": True})

            try:
                if ev in ("subscription.active", "subscription.paid",
                          "checkout.completed"):
                    plan = creem.plan_of(obj) or "month"
                    billing.apply_paid(uid, plan, creem.period_end(obj))
                    billing.promo_paid(uid)   # перша оплата — код відпрацював
                elif ev in ("refund.created", "dispute.created",
                            "subscription.expired", "subscription.unpaid"):
                    # Повернення й спір — гроші пішли назад, підписку знімаємо.
                    # Строк скінчився без оплати — те саме по суті.
                    billing.revoke(uid)
                # Відмова від продовження (subscription.canceled,
                # scheduled_cancel) дати не чіпає навмисно: оплачені дні
                # людина дожити має, так написано в умовах.
            except Exception as ex:
                print("webhook: не застосував %s: %s" % (ev, ex), flush=True)
            return self._json({"ok": True})

        # ---- промокод ----
        if p == "/api/billing/promo":
            # Код не знижує ціну сам — він переводить акаунт на інший набір,
            # і той лишається назавжди. Тому у відповідь віддаємо новий стан
            # цілком: сторінка перемалює картки з уже новими сумами.
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            code = str(body.get("code") or "")[:64]
            ok, why = billing.redeem(uid, code)
            if not ok:
                return self._json({"error": why, "code": why}, 400)
            print("promo: %s ввів %r" % (uid, code.strip().upper()), flush=True)
            return self._json(billing.public(uid))

        # ---- підписка руками: дати, зняти, підсипати бонус, поставити ціну ----
        if p.startswith("/api/admin/billing/"):
            who = self._uid()
            if not who:
                return self._json({"error": "auth required"}, 401)
            if not _is_admin(who):
                return self._json({"error": "forbidden"}, 403)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            nick = str(body.get("nick") or "").strip()
            try:
                u = db.get_user_by_nick(nick) or db.get_user_by_email(nick)
            except Exception:
                u = None
            if not u:
                return self._json({"error": "такого пользователя нет"}, 404)
            act = p[len("/api/admin/billing/"):].strip("/")
            note = str(body.get("note") or "").strip() or None
            num = lambda k: int(body.get(k) or 0)
            seclog.event("адмін", True, user=db.get_user(who), ip=self._guest(),
                         дія=act, кому=u["nickname"], кому_id=u["id"])
            if act == "grant":
                # Назавжди — окремим прапорцем, а не «99999 днів»: інакше
                # в базі лежала б вигадана дата, а людині показували б строк.
                if body.get("life"):
                    return self._json(billing.grant_life(u["id"]))
                days = num("days")
                if days <= 0:
                    return self._json({"error": "нужно число дней"}, 400)
                plan = str(body.get("plan") or "").strip()
                return self._json(billing.grant(u["id"], days, plan))
            if act == "revoke":
                return self._json(billing.revoke(u["id"]))
            if act == "ts-restore":
                day = str(body.get("day") or "")
                ts = dict(backup.strategies(u["id"])).get(day)
                if not ts:
                    return self._json({"error": "за этот день копии ТС нет"}, 404)
                ts_store.put(u["id"], ts)
                return self._json({"ok": True, "day": day})
            if act == "bonus":
                if not any(num(k) for k in ("trades", "bt", "imports", "ai", "bt_imports")) and note is None:
                    return self._json({"error": "нечего добавлять"}, 400)
                return self._json(billing.bonus(u["id"], trades=num("trades"),
                                                bt=num("bt"), imports=num("imports"),
                                                ai=num("ai"), note=note,
                                                bt_imports=num("bt_imports")))
            if act == "price":
                plan = str(body.get("price_plan") or "").strip()
                own = body.get("own_cents")
                return self._json(billing.set_price(
                    u["id"], price_plan=plan if plan in ("std", "early") else None,
                    own_cents=int(own) if str(own or "").strip() else None, note=note))
            # «це інша людина» — адреса перестає бути заслоном для нових
            # реєстрацій; саму людину це нікуди не пускає й не блокує.
            if act == "allow-ip":
                ip = (u["signup_ip"] or "").strip()
                if not ip:
                    return self._json({"error": "у этого аккаунта не записан IP"}, 400)
                if body.get("off"):
                    antifraud.forbid(ip)
                else:
                    antifraud.allow(ip, note or ("разрешено из карточки " + u["nickname"]))
                return self._json({"ok": True, "ip": ip, "allowed": not body.get("off")})
            return self._json({"error": "неизвестное действие"}, 400)

        if p == "/api/admin/set-ref":
            who = self._uid()
            if not who:
                return self._json({"error": "auth required"}, 401)
            if not _is_admin(who):
                return self._json({"error": "forbidden"}, 403)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            nick = str(body.get("nick") or "").strip()
            try:
                u = db.get_user_by_nick(nick) or db.get_user_by_email(nick)
            except Exception:
                u = None
            if not u:
                return self._json({"error": "такого пользователя нет"}, 404)
            raw = str(body.get("ref") or "").strip().lower()
            ref = ref_norm(raw) if raw else ""
            if raw and not ref:
                return self._json({"error": "неизвестная метка"}, 400)
            with db.connect() as conn:
                conn.execute("UPDATE users SET ref_source=%s, ref_at=%s WHERE id=%s",
                             (ref or None, "now()" and (datetime.datetime.now() if ref else None), u["id"]))
                conn.commit()
            seclog.event("адмін", True, user=db.get_user(who), ip=self._guest(),
                         дія="мітка:%s" % (ref or "—"), кому=u["nickname"], кому_id=u["id"])
            return self._json({"ok": True, "ref": ref})

        # ---- замок на акаунт: лише власникам ----
        # Замок ставиться й знімається тільки звідси, руками. Автоматики
        # навколо нього немає навмисно: це крок, після якого людина не може
        # працювати, і робити його за здогадом коду не можна.
        if p == "/api/admin/set-lock":
            who = self._uid()
            if not who:
                return self._json({"error": "auth required"}, 401)
            if not _is_admin(who):
                return self._json({"error": "forbidden"}, 403)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            nick = str(body.get("nick") or "").strip()
            try:
                u = db.get_user_by_nick(nick) or db.get_user_by_email(nick)
            except Exception:
                u = None
            if not u:
                return self._json({"error": "такого пользователя нет"}, 404)
            note = str(body.get("note") or "").strip()[:2000]
            db.set_lock(u["id"], note)
            # Список замків лежить у пам'яті до LOCK_TTL секунд, і в цього
            # робітника він свій. Свій скидаємо одразу, решта підхопить
            # сама — для «зняв замок» це секунди, і людина однаково
            # перезавантажує сторінку довше.
            with self._lock_gate:
                self._locks[:] = [0.0, {}]
            seclog.event("адмін", True, user=db.get_user(who), ip=self._guest(),
                         дія="замок:%s" % ("поставив" if note else "знято"),
                         кому=u["nickname"], кому_id=u["id"])
            return self._json({"ok": True, "locked": bool(note)})

        # ---- видалення акаунта на прохання людини: лише власникам ----
        if p == "/api/admin/delete-user":
            who = self._uid()
            if not who:
                return self._json({"error": "auth required"}, 401)
            if not _is_admin(who):
                return self._json({"error": "forbidden"}, 403)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            nick = str(body.get("nick") or "").strip()
            u = None
            try:
                u = db.get_user_by_nick(nick) or db.get_user_by_email(nick)
            except Exception:
                u = None
            if not u:
                return self._json({"error": "такого пользователя нет"}, 404)
            # Підтвердження словом: щоб випадковий клік нічого не зніс.
            if str(body.get("confirm") or "").strip() != (u["nickname"] or ""):
                return self._json({"error": "ник в подтверждении не совпадает"}, 400)
            if _is_admin(u["id"]) and u["id"] != who:
                return self._json({"error": "аккаунт владельца так не удаляют"}, 403)
            seclog.event("адмін", True, user=db.get_user(who), ip=self._guest(),
                         дія="видалення", кому=u["nickname"], кому_id=u["id"])
            banned = antifraud.ban_user(u, "бан з картки " + u["nickname"]) if body.get("ban") else []
            n = delete_user_fully(u["id"])
            return self._json({"deleted": u["nickname"], "files": n, "banned": len(banned)})

        if p == "/api/auth/register":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            email = str(body.get("email") or "").strip()
            password = str(body.get("password") or "")
            # Акаунти не штампуємо скриптом: 5 спроб реєстрації за хвилину з
            # однієї адреси. Рахуємо кожну — вдала реєстрація теж спроба.
            keys = ["register:" + self._guest()]
            wait = ratelimit.check(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys)
            if not EMAIL_RE.match(email) or len(password) < 6:
                return self._json({"error": "потрібні пошта і пароль від 6 символів",
                                   "code": "need_fields"}, 400)
            if db.get_user_by_email(email) or db.user_by_email_key(email):
                # Друга умова — та сама скринька з іншим хвостиком:
                # «ivan+2@gmail» це той самий ящик, що й «ivan@gmail».
                return self._json({"error": "така пошта вже зайнята", "code": "taken"}, 409)
            if antifraud.throwaway_mail(email):
                return self._json({"error": "потрібна постійна пошта",
                                   "code": "temp_mail"}, 409)
            # Другий акаунт із тієї самої адреси І з того самого пристрою.
            # Тільки разом: сам IP нічого не доводить — за одним виходом
            # оператора сидить півміста (див. antifraud.py).
            ip = self._guest()
            device = antifraud.device_hash(body.get("device"))
            if antifraud.blocked(ip, device, email):
                return self._json({"error": "з цієї адреси вже є акаунт",
                                   "code": "ip_taken"}, 409)
            pw_hash, pw_salt, iters = auth.hash_password(password)
            # Нікнейм робимо з пошти. Він може збігтися з чужим — тоді
            # пробуємо ще раз із хвостиком: людина про це навіть не знає,
            # бо ніде його не вводила.
            nick = nick_from_email(email)
            user = None
            for attempt in range(6):
                try:
                    user = db.create_user(email, nick if attempt == 0
                                          else "%s-%s" % (nick, secrets.token_hex(2)),
                                          pw_hash, pw_salt, iters)
                    break
                except Exception as ex:
                    low = str(ex).lower()
                    if "unique" not in low and "duplicate" not in low:
                        raise
            if not user:
                return self._json({"error": "така пошта вже зайнята", "code": "taken"}, 409)
            seclog.event("реєстрація", True, user=user, ip=ip)
            # Звідки й з чого зайшли — щоб наступну таку реєстрацію було з
            # чим порівняти, а в адмінці було видно сусідів.
            try:
                antifraud.remember(user["id"], ip, device)
            except Exception as ex:
                print("antifraud:", ex)     # заважати реєстрації це не має
            ref_claim(user["id"], self._cookie(REF_COOKIE))
            # У журнал — лише після коду з листа (рішення владельця
            # 15.09.2026): раніше пускали одразу, а підтвердження просили
            # посиланням, яке можна було й не відкривати.
            return self._ask_mail_code(user, str(body.get("lang") or "ru"), 201)

        if p == "/api/auth/login":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            # П'ять невдалих спроб за хвилину — і далі просимо зачекати.
            # Рахуємо і за адресою, і за логіном: перебір з одного місця
            # та перебір одного акаунта з різних адрес — це різні речі.
            who = str(body.get("login") or "").strip().lower()
            keys = ["ip:" + self._guest()] + (["who:" + who] if who else [])
            wait = ratelimit.locked(keys)
            if wait:
                return self._json(
                    {"error": "забагато спроб входу — спробуй за %d с" % wait, "code": "too_many", "wait": wait}, 429)
            user = db.get_user_by_login(body.get("login"))
            if not user or not auth.verify_password(str(body.get("password") or ""),
                                                    user["pw_hash"], user["pw_salt"],
                                                    user["pw_iters"]):
                ratelimit.fail(keys)
                # Окремий лічильник на сам акаунт: логін пишуть і поштою, і
                # ніком, і з великої літери — за рядком їх не звести, а
                # попередити треба про підбір саме цього журналу.
                if user:
                    self._note_guessing(user, str(body.get("lang") or "ru"))
                seclog.event("вхід", False, user=user, ip=self._guest(),
                             login=body.get("login"))
                return self._json({"error": "невірна пошта або пароль", "code": "bad_login"}, 401)
            ratelimit.clear(keys + ["user:%d" % user["id"]])
            seclog.event("вхід", True, user=user, ip=self._guest())
            # Пароль правильний, але пошту так і не підтвердили — спершу код.
            if self._needs_mail_code(user):
                return self._ask_mail_code(user, str(body.get("lang") or "ru"))
            return self._enter(user)

        # ---- код підтвердження пошти ----
        # Пропуск — HttpOnly-кука після реєстрації чи входу з непідтвердженою
        # поштою. Код вірний — пошту підтверджено, далі звичайний вхід (з 2FA,
        # якщо вона є).
        if p in ("/api/auth/mail-code", "/api/auth/mail-code/resend"):
            sec = auth.is_https(self)
            uid = auth.read_mailcode(auth.read_cookie(self, auth.MAILCODE_COOKIE))
            user = db.get_user(uid) if uid else None
            if not user:
                return self._json({"error": "час вийшов — увійди ще раз", "code": "mail_expired"},
                                  401, cookie=auth.mailcode_cookie("", sec))
            if user["email_confirmed_at"] is not None:
                self._add_cookie(auth.mailcode_cookie("", sec))
                return self._enter(user)
            body = body if isinstance(body, dict) else {}
            if p.endswith("/resend"):
                # Новий лист — не частіше разу на хвилину.
                keys = ["mailcode-send:%d" % uid]
                wait = ratelimit.check(keys, limit=1)
                if wait:
                    return self._json({"error": "зачекай %d с" % wait, "code": "too_many",
                                       "wait": wait}, 429)
                ratelimit.miss(keys, limit=1)
                in_background(authmail.start_code, user, self._base(), str(body.get("lang") or "ru"))
                return self._json({"ok": True})
            keys = ["mailcode:%d" % uid]
            wait = ratelimit.locked(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            if not authmail.take_code(uid, body.get("code")):
                ratelimit.fail(keys)
                return self._json({"error": "код не підходить", "code": "mail_bad"}, 401)
            ratelimit.clear(keys)
            db.confirm_email(uid)
            self._add_cookie(auth.mailcode_cookie("", sec))
            return self._enter(db.get_user(uid))

        # ---- другий крок входу: код із застосунку ----
        # Пропуск лежить у HttpOnly-куці після правильного пароля (чи входу
        # через сервіс, чи нового пароля за посиланням). Без нього — нема що
        # перевіряти: код сам по собі нікого не впускає.
        if p == "/api/auth/2fa/verify":
            sec = auth.is_https(self)
            uid = auth.read_pending(auth.read_cookie(self, auth.PENDING_COOKIE))
            if not uid:
                return self._json({"error": "час вийшов — увійди ще раз", "code": "twofa_expired"},
                                  401, cookie=auth.pending_cookie("", sec))
            keys = self._twofa_limit(uid)
            if keys is None:
                return
            user = db.get_user(uid)
            ok, left = twofa.verify(user, (body or {}).get("code"))
            if not ok:
                ratelimit.fail(keys)
                seclog.event("вхід-2fa", False, user=user, ip=self._guest())
                return self._json({"error": "код не підходить", "code": "twofa_bad"}, 401)
            ratelimit.clear(keys)
            seclog.event("вхід-2fa", True, user=user, ip=self._guest(),
                         код="запасний" if left is not None else "застосунок")
            self._add_cookie(auth.pending_cookie("", sec))
            out = {"user": user_public(user)}
            if left is not None:
                out["backup_left"] = left       # зайшли запасним кодом — скажемо, скільки лишилось
            return self._json(out, cookie=self._session_cookie(user))

        # ---- чи знайома нам ця пошта ----
        # Питає сама форма входу, щойно адресу дописано: про незнайому пошту
        # людина має дізнатись там, де її вводить, а не аж після кнопки
        # «надіслати посилання». Ясність тут та сама, що й у forgot нижче, і
        # плата та сама — тож і лічильник спроб той самий, 5 за хвилину.
        if p == "/api/auth/known":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            mail = str(body.get("email") or "").strip()
            keys = ["known:" + self._guest()]
            wait = ratelimit.check(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys)
            if not EMAIL_RE.match(mail):
                return self._json({"error": "це не схоже на пошту",
                                   "code": "bad_email"}, 400)
            return self._json({"known": bool(db.get_user_by_email(mail))})

        # ---- забув пароль ----
        # Відповідаємо чесно: є така пошта чи немає, дійшов лист чи ні.
        # Плата за це відома — сторінкою входу можна перевіряти, хто тут
        # зареєстрований. Власник журналу зважив і вибрав ясність: людина,
        # яка помилилась адресою, інакше дивиться на «якщо така пошта є,
        # ми надіслали» і не розуміє, чому нічого не приходить. Перебір
        # стримує той самий лічильник, що й на вході: 5 спроб за хвилину.
        if p == "/api/auth/forgot":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            mail = str(body.get("email") or "").strip()
            lang = str(body.get("lang") or "ru")
            keys = ["forgot:" + self._guest()] + (["forgot:" + mail.lower()] if mail else [])
            wait = ratelimit.check(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            # Лічильник крутимо на кожен запит, а не лише на невдалий: тут
            # немає «вдалого», і без цього листами можна було б засипати
            # чужу скриньку.
            ratelimit.miss(keys)
            if not EMAIL_RE.match(mail):
                return self._json({"error": "це не схоже на пошту",
                                   "code": "bad_email"}, 400)
            user = db.get_user_by_email(mail)
            if not user:
                return self._json({"error": "такої пошти в нас немає",
                                   "code": "no_user"}, 404)
            # Чекаємо на відправку, а не кидаємо її у фон: обіцяти «лист
            # пішов», не знаючи цього, — гірше за секунду очікування.
            try:
                done = authmail.start(user, self._base(), lang)
            except Exception as ex:
                print("пароль: не вдалось надіслати —", ex, flush=True)
                done = []
            if not done:
                return self._json({"error": "лист не вдалось надіслати",
                                   "code": "send_failed"}, 502)
            return self._json({"ok": True, "sent": done})

        # ---- новий пароль за посиланням ----
        if p == "/api/auth/reset":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            token = str(body.get("token") or "")
            password = str(body.get("password") or "")
            if len(password) < 6:
                return self._json({"error": "пароль від 6 символів", "code": "short"}, 400)
            keys = ["reset:" + self._guest()]
            wait = ratelimit.locked(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            user = db.take_link(authmail.token_hash(token), "password") if token else None
            if not user:
                ratelimit.fail(keys)
                return self._json({"error": "посилання застаріло", "code": "bad_token"}, 400)
            ratelimit.clear(keys)
            pw_hash, pw_salt, iters = auth.hash_password(password)
            db.set_password(user["id"], pw_hash, pw_salt, iters)
            # Пароль скидають, коли його знає хтось чужий (чи боїться цього) —
            # тож усі старі входи гасимо.
            auth.bump_gen(user["id"])
            seclog.event("пароль", True, user=user, ip=self._guest(), як="скидання")
            user = db.get_user(user["id"])
            # Одразу впускаємо: людина щойно довела, що скринька її, і
            # вводити пароль удруге тим самим рухом — зайве. Але з 2FA — ні:
            # доступ до пошти не має відкривати акаунт повз код.
            return self._enter(user)

        if p == "/api/auth/logout":
            return self._json({"ok": True}, cookie=auth.clear_cookie_header(auth.is_https(self)))

        # ---- дальше всё только для своих ----
        uid = self._uid()

        if p.startswith("/api/") and not uid:
            return self._json({"error": "auth required"}, 401)

        if p == "/api/me/mail":
            on = bool((body or {}).get("on"))
            mailout.set_news(uid, on)
            return self._json({"mail_news": on})

        # ---- розсилка: лише власникам ----
        if p.startswith("/api/admin/mail/"):
            if not _is_admin(uid):
                return self._json({"error": "forbidden"}, 403)
            b = body or {}
            act = p[len("/api/admin/mail/"):]
            subject = str(b.get("subject") or "").strip()[:150]
            text = str(b.get("body") or "")[:20000]
            aud = b.get("audience") if b.get("audience") in mailout.AUDIENCES else "all"
            ref = str(b.get("ref") or "")
            ref = ref if ref in ref_all() else ""
            if act == "count":
                return self._json({"n": len(mailout.recipients(aud, ref))})
            if act == "run":
                return self._json({"n": mailout.run_once()})
            if not subject or not text.strip():
                return self._json({"error": "нужны тема и текст"}, 400)
            if act == "test":
                me = db.get_user(uid)
                ok = mailout.send_one(me["email"], subject, text, uid)
                return self._json({"to": me["email"]} if ok else {"error": "письмо не ушло — смотри лог сервера"},
                                  200 if ok else 502)
            if act == "send":
                seclog.event("розсилка", True, user=db.get_user(uid), ip=self._guest(), тема=subject)
                return self._json({"n": mailout.enqueue(subject, text, aud, ref)})
            return self._json({"error": "неизвестное действие"}, 400)

        if p == "/api/ts/active":
            db.set_ts_active(uid, (body or {}).get("ts"))
            return self._json({"ok": True})

        if p == "/api/me/ts-copy":
            on = bool((body or {}).get("on"))
            db.set_ts_copy(uid, on)
            return self._json({"ts_copy": on})

        # Забрати чужу ТС до себе за посиланням на неї — якщо автор дозволив
        m = re.match(r"^/api/share/([A-Za-z0-9_-]{6,32})/copy-ts$", p)
        if m:
            rec = share_read(m.group(1))
            if not ts_copy_ok(rec):
                return self._json({"error": "копіювати не можна", "code": "no_copy"}, 404)
            owner = rec["user_id"]
            if owner == uid:
                return self._json({"error": "це ваша ТС", "code": "own"}, 400)
            src = ts_store.get(owner, "", seed=False, sid=(rec.get("data") or {}).get("sid") or 0)
            if not src:
                return self._json({"error": "ТС уже немає", "code": "no_copy"}, 404)
            data = ts_store.copy_for(uid, src)
            # Своєї ТС ще немає — чужа стає першою. Є — не затираємо її, а
            # кладемо чужу окремою стратегією: людина може тримати обидві.
            if ts_store.get(uid, "", seed=False) and not (body or {}).get("replace"):
                author = (db.get_user(owner) or {}).get("nickname") or ""
                sid = ts_store.create(uid, ("ТС " + author).strip()[:60])
                if not sid:
                    return self._json({"error": "забагато стратегій", "code": "too_many"}, 409)
                ts_store.put(uid, data, "", sid)
                print("ts-copy: %s забрав ТС у %s окремою стратегією" % (uid, owner), flush=True)
                return self._json({"ok": True, "sid": sid})
            ts_store.put(uid, data, "")
            ts_store.sweep(uid, data, SHOTS, "")   # старі скріни своєї ТС
            print("ts-copy: %s забрав ТС у %s" % (uid, owner), flush=True)
            return self._json({"ok": True})

        if p == "/api/me/public":
            on = bool((body or {}).get("on"))
            db.set_public(uid, on)
            return self._json({"public_journal": on})

        # ---- профіль: новий нік ----
        if p == "/api/me/nick":
            want = str((body or {}).get("nickname") or "").strip()
            keys = ["nick:%d" % uid]
            wait = ratelimit.check(keys, limit=10)
            if wait:
                return self._json({"error": "зачекай %d с" % wait, "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys, limit=10)
            problem = nick_problem(want, uid)
            if problem == "same":
                return self._json({"user": user_public(db.get_user(uid))})
            if problem:
                return self._json({"error": "нік не підходить", "code": problem}, 400 if problem == "bad" else 409)
            if not db.set_nickname(uid, want):
                return self._json({"error": "нік зайнятий", "code": "taken"}, 409)
            return self._json({"user": user_public(db.get_user(uid))})

        # ---- профіль: фото ----
        # Браузер сам обрізає фото в квадрат 256×256, сюди приходить маленька
        # картинка. Перевіряємо розмір і перші байти, як у скрінів угод.
        if p == "/api/me/avatar":
            m = DATAURL_RE.match(str((body or {}).get("data") or ""))
            if not m:
                return self._json({"error": "не картинка", "code": "bad_image"}, 400)
            try:
                raw = base64.b64decode(m.group(2))
            except Exception:
                return self._json({"error": "не картинка", "code": "bad_image"}, 400)
            if len(raw) > AVATAR_MAX:
                return self._json({"error": "завелике фото", "code": "too_big"}, 413)
            ext = filestore.kind(raw)
            if not ext:
                return self._json({"error": "не картинка", "code": "bad_image"}, 400)
            name = "av%d_%s.%s" % (uid, secrets.token_hex(6), ext)
            filestore.put(name, raw)
            old = db.set_avatar(uid, name)
            if own_avatar_file(old) and old != name:
                filestore.delete([old])
            return self._json({"user": user_public(db.get_user(uid))})

        # ---- профіль: готова аватарка замість фото ----
        if p == "/api/me/avatar/preset":
            name = str((body or {}).get("id") or "")
            if name not in AVATAR_PRESETS:
                return self._json({"error": "нема такої аватарки", "code": "bad_preset"}, 400)
            old = db.set_avatar(uid, "preset:" + name)
            if own_avatar_file(old):
                filestore.delete([old])
            return self._json({"user": user_public(db.get_user(uid))})

        if p == "/api/me/avatar/remove":
            old = db.set_avatar(uid, None)
            if own_avatar_file(old):
                filestore.delete([old])
            return self._json({"user": user_public(db.get_user(uid))})

        # ---- часовий пояс ----
        # Його ставлять у розділі «Новини», а живе він у профілі: бот
        # шле зведення тим самим поясом, інакше «о 8:00» означало б різне
        # на сайті й у Телеграмі.
        if p == "/api/me/tz":
            want = str((body or {}).get("tz") or "").strip()
            try:
                ZoneInfo(want)
            except Exception:
                return self._json({"error": "невідомий часовий пояс"}, 400)
            db.set_tz(uid, want)
            return self._json({"tz": want})

        # ---- зміна власного пароля ----
        # Старий пароль питаємо навіть у того, хто вже увійшов: сесія живе
        # 30 днів, і чужий комп'ютер із незакритою вкладкою не повинен
        # давати змогу перебити пароль і забрати акаунт. Перебір старого
        # обмежуємо так само, як вхід.
        # ---- надіслати підтвердження пошти ще раз ----
        if p == "/api/me/confirm":
            me = db.get_user(uid)
            if not me:
                return self._json({"error": "no user"}, 404)
            if me["email_confirmed_at"] is not None:
                return self._json({"ok": True, "confirmed": True})
            keys = ["confirm:%d" % uid]
            wait = ratelimit.check(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys)
            in_background(authmail.start_confirm, me, self._base(),
                          str((body or {}).get("lang") or "ru"))
            return self._json({"ok": True, "sent": True})

        if p == "/api/me/password":
            old = str((body or {}).get("old") or "")
            new = str((body or {}).get("new") or "")
            if len(new) < 6:
                return self._json({"error": "пароль від 6 символів",
                                   "code": "short"}, 400)
            keys = ["pw:%d" % uid]
            wait = ratelimit.locked(keys)
            if wait:
                return self._json({"error": "забагато спроб — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            me = db.get_user(uid)
            if not me or not auth.verify_password(old, me["pw_hash"], me["pw_salt"],
                                                  me["pw_iters"]):
                ratelimit.fail(keys)
                return self._json({"error": "старий пароль не підходить",
                                   "code": "bad_old"}, 403)
            ratelimit.clear(keys)
            pw_hash, pw_salt, iters = auth.hash_password(new)
            db.set_password(uid, pw_hash, pw_salt, iters)
            seclog.event("пароль", True, user=me, ip=self._guest(), як="сам")
            # новий пароль — нове покоління: хто зайшов зі старим, вилітає
            return self._fresh_login(uid, {"ok": True})

        # ---- вийти на всіх пристроях, крім цього ----
        if p == "/api/me/logout-all":
            return self._fresh_login(uid, {"ok": True})

        # ---- 2FA: увімкнення ----
        # Спершу ключ (setup), і лише коли людина ввела з застосунку перший
        # код — пишемо в базу. Інакше можна «увімкнути» захист, якого
        # застосунок не знає, і замкнути себе поза журналом.
        if p == "/api/me/2fa/setup":
            me = db.get_user(uid)
            if twofa.enabled(me):
                return self._json({"error": "вже увімкнено", "code": "twofa_on"}, 409)
            secret = twofa.new_secret()
            return self._json({"secret": secret,
                               "uri": twofa.uri(secret, me["email"] or me["nickname"]),
                               "setup": auth.make_setup(uid, secret)})

        if p == "/api/me/2fa/enable":
            keys = self._twofa_limit(uid)
            if keys is None:
                return
            me = db.get_user(uid)
            if twofa.enabled(me):
                return self._json({"error": "вже увімкнено", "code": "twofa_on"}, 409)
            secret = auth.read_setup(str((body or {}).get("setup") or ""), uid)
            if not secret:
                return self._json({"error": "час вийшов — почни заново", "code": "twofa_expired"}, 400)
            step = twofa.match_step(secret, (body or {}).get("code"))
            if step is None:
                ratelimit.fail(keys)
                return self._json({"error": "код не підходить", "code": "twofa_bad"}, 400)
            ratelimit.clear(keys)
            codes = twofa.new_backup_codes()
            db.twofa_enable(uid, secret, [twofa.backup_hash(c) for c in codes], step)
            seclog.event("2fa", True, user=me, ip=self._guest(), стан="увімкнено")
            return self._fresh_login(uid, {"backup_codes": codes})

        # ---- 2FA: вимкнути або нові запасні коди ----
        # Лише з кодом (із застосунку чи запасним): інакше чужа незакрита
        # вкладка тихо зняла б захист. Пароль тут не питаємо — у тих, хто
        # заходить через Google, його просто немає.
        if p in ("/api/me/2fa/disable", "/api/me/2fa/backup"):
            keys = self._twofa_limit(uid)
            if keys is None:
                return
            me = db.get_user(uid)
            if not twofa.enabled(me):
                return self._json({"error": "2FA вимкнено", "code": "twofa_off"}, 409)
            ok, _ = twofa.verify(me, (body or {}).get("code"))
            if not ok:
                ratelimit.fail(keys)
                return self._json({"error": "код не підходить", "code": "twofa_bad"}, 400)
            ratelimit.clear(keys)
            if p.endswith("/disable"):
                db.twofa_disable(uid)
                seclog.event("2fa", True, user=me, ip=self._guest(), стан="вимкнено")
                return self._fresh_login(uid, {"ok": True})
            codes = twofa.new_backup_codes()
            db.twofa_set_backup(uid, [twofa.backup_hash(c) for c in codes])
            return self._fresh_login(uid, {"backup_codes": codes})

        if p == "/api/telegram/link-code":
            bot = bot_username()
            if not bot:
                return self._json({"error": "бот не налаштований — немає BOT_TOKEN"}, 503)
            code = db.create_link_code(uid)
            return self._json({"code": code, "bot": bot,
                               "link": "https://t.me/%s?start=%s" % (bot, code)})

        if p == "/api/telegram/unlink":
            db.unlink_telegram(uid)
            return self._json({"ok": True})

        if p == "/api/assistant/ask":
            # Кожне питання — платний запит до моделі. 20 за хвилину на
            # людину вистачає для живої розмови, а скрипт далі не піде.
            keys = ["ask:%s" % uid]
            wait = ratelimit.check(keys, limit=ASK_LIMIT)
            if wait:
                return self._json({"error": "забагато питань поспіль — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys, limit=ASK_LIMIT)
            question = str((body or {}).get("question") or "").strip()
            if not question:
                return self._json({"error": "порожнє питання"}, 400)
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає DEEPSEEK_API_KEY"}, 503)
            # Місячна порція звернень до моделі. Списуємо одразу й одне на
            # питання, навіть якщо всередині модель смикають двічі (правка
            # «Моєї ТС», добір угод на видалення): людина спитала раз.
            # Дозвіл і списання одним запитом: пачка одночасних питань
            # інакше проходила перевірку всі разом (див. billing.take_ai).
            ok, why = billing.take_ai(uid)
            if not ok:
                return self._json(billing.deny(uid, why), 402)
            # історія розмови приходить з браузера — беремо тільки останні репліки
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            lang = str((body or {}).get("lang") or "")
            lang = lang if lang in ("uk", "ru", "en") else None
            # у якому журналі людина зараз: помічник має відповідати про те,
            # що вона перед собою бачить, і прибирати теж саме те
            kind = "bt" if (body or {}).get("kind") == "bt" else ""
            # кілька стратегій: помічник дивиться на угоди й ТС обраної
            kind = kind or db.strat_kind((body or {}).get("ts"))
            # прохання змінити «Мою ТС» — окрема гілка: модель лише каже, ЩО
            # змінити, а перевіряє шляхи й пише в базу код (ts_edit.py).
            # Йде першою, коли прохання явно про ТС: «прибери модель BOS з ТС»
            # інакше перехопить видалення угод — там теж своє «прибери».
            if ts_edit.looks_like(question) and ts_edit.about_ts(question):
                r = ts_edit.plan(uid, question, history, lang, kind)
                if r:
                    return self._json(r)
            # прохання видалити угоди — окрема гілка: модель лише каже, ЩО
            # видаляти, угоди добирає код, а зникають вони тільки після
            # натиснутої кнопки в підтвердженні (delete_ai.py)
            if delete_ai.looks_like(question):
                card = delete_ai.plan(uid, question, history, kind)
                if card:
                    return self._json(card)
            # решта прохань про ТС — без явного слова «ТС» («додай золото в активи»)
            if ts_edit.looks_like(question):
                r = ts_edit.plan(uid, question, history, lang, kind)
                if r:
                    return self._json(r)
            return self._json({"answer": assistant.ask(uid, question, history, lang,
                                                       kind=kind)})

        if p == "/api/assistant/nudge":
            lang = str((body or {}).get("lang") or "ru")
            # Заговорює помічник сам, тому з порції нічого не знімаємо: не
            # людина попросила. Але й платити за це без кінця не будемо —
            # коли порція вичерпана, привід лишається, а слова до нього
            # бере сторінка (у неї свої, на три мови).
            return self._json(assistant.nudge(
                uid, lang if lang in ("uk", "ru", "en") else "ru",
                "bt" if (body or {}).get("kind") == "bt" else db.strat_kind((body or {}).get("ts")),
                talk=billing.can_use_ai(uid)[0]))

        if p == "/api/assistant/review":
            # той самий платний запит до моделі — і лічильник той самий
            keys = ["ask:%s" % uid]
            wait = ratelimit.check(keys, limit=ASK_LIMIT)
            if wait:
                return self._json({"error": "забагато питань поспіль — спробуй за %d с" % wait,
                                   "code": "too_many", "wait": wait}, 429)
            ratelimit.miss(keys, limit=ASK_LIMIT)
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає DEEPSEEK_API_KEY"}, 503)
            # Дозвіл і списання одним запитом: пачка одночасних питань
            # інакше проходила перевірку всі разом (див. billing.take_ai).
            ok, why = billing.take_ai(uid)
            if not ok:
                return self._json(billing.deny(uid, why), 402)
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            # мова журналу: факти під відповіддю показуються як є, і в
            # російському журналі український рядок виглядав чужим
            rlang = str((body or {}).get("lang") or "")
            return self._json(assistant.review(
                uid, history,
                lang=rlang if rlang in ("uk", "ru", "en") else None,
                kind="bt" if (body or {}).get("kind") == "bt" else db.strat_kind((body or {}).get("ts"))))

        # друга половина видалення на прохання: ключ одноразовий, список id
        # у ньому вже зафіксований — тут нічого не добирається заново
        if p == "/api/assistant/delete":
            ids = delete_ai.take(uid, (body or {}).get("token"))
            if ids is None:
                return self._json({"error": "confirm expired"}, 400)
            gone = 0
            for tid in ids:
                old = db.get_trade(tid, uid)
                if not old:
                    continue
                db.delete_trade(uid, tid)
                delete_files([s["file"] for s in old.get("screenshots") or []
                              if s.get("file")])
                gone += 1
            return self._json({"deleted": gone})

        if p == "/api/share":
            if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
                return self._json({"error": "нужен объект data"}, 400)
            raw = json.dumps(body["data"], ensure_ascii=False)
            if len(raw.encode("utf-8")) > SHARE_MAX:
                return self._json({"error": "снимок слишком большой"}, 413)
            rec = share_create(body["data"], body.get("ttl", "7d"), uid)
            # мітка партнера — прямо в адресі: власник спільноти бачить, що
            # посилання рахується йому. Сама мітка й так береться з хазяїна.
            ref = ref_of_user(uid)
            url = "/s/" + rec["id"] + ("?ref=" + ref_short(ref) if ref else "")
            return self._json({"id": rec["id"], "url": url,
                               "expires": rec["expires"]}, 201)

        # ---- одно и то же под разными именами (tidy.py) ----
        if p == "/api/tidy/apply":
            body = body or {}
            field = str(body.get("field") or "")
            to = str(body.get("to") or "").strip()
            values = [str(v) for v in (body.get("from") or [])]
            if not to or not values:
                return self._json({"error": "потрібні написання і головне ім'я"}, 400)
            try:
                n = db.rename_value(uid, field, values, to)
            except ValueError:
                return self._json({"error": "це поле не зводимо"}, 400)
            return self._json({"changed": n})

        if p == "/api/notion/preview":
            body = body or {}
            url = str(body.get("url") or "").strip()
            try:
                data = npub.preview(url, body.get("mapping"), body.get("table"))
            except notion.NotionError as ex:
                return self._json({"error": str(ex)}, 400)
            except Exception as ex:
                return self._json({"error": "не вдалося прочитати сторінку: %s" % ex}, 502)
            conf = notion_conf(uid)
            conf.update({"url": url, "title": data.get("title") or "",
                         "mapping": data.get("mapping") or {}})
            notion_save(uid, conf)
            data["fields"] = [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS]
            data.pop("source", None)
            return self._json(data)
        if p.startswith("/api/notion/undo/"):
            n = drop_import(uid, p[len("/api/notion/undo/"):])
            return self._json({"removed": n})

        # Відв'язати базу — разом з її угодами, як і «undo» вище. Маршрут
        # лишається для сторінок, що ще тримають старий notion.js у кеші.
        if p.startswith("/api/notion/off/"):
            n = drop_import(uid, p[len("/api/notion/off/"):])
            conf = notion_conf(uid)
            return self._json({"ok": True, "removed": n,
                               "left": len(conf.get("sources") or [])})

        if p == "/api/notion/forget":
            try:
                os.remove(notion_file(uid))
            except Exception:
                pass
            return self._json({"ok": True})

        if p == "/api/notion/import":
            body = body or {}
            url = str(body.get("url") or "").strip()
            mapping = body.get("mapping") or {}
            tables = [t for t in (body.get("tables") or [])
                      if isinstance(t, dict) and t.get("collection") and t.get("view")]
            if not tables or not mapping.get("pair"):
                return self._json({"error": "потрібні таблиця і колонка з інструментом"}, 400)
            # Три перенесення в перші 30 днів — далі тільки з підпискою.
            # Бектест з Notion — тільки з підпискою одразу.
            # Дивимось до запуску потоку: скасувати його потім нічим.
            kind = "bt" if body.get("kind") == "bt" else ""
            ok, why = billing.can_import(uid, kind)
            if not ok:
                return self._json(billing.deny(uid, why), 402)
            conf = notion_conf(uid)
            title = body.get("title") or ""
            run = (str(body.get("bt_run") or "").strip() or title.strip() or "Notion")[:80]
            # Ліміт бектесту рахує нові бази. Ту саму базу (ті самі таблиці
            # Notion) перечитати, щоб підтягнути нові угоди, можна скільки
            # завгодно — і після «Відв'язати» теж: список не чиститься.
            if kind == "bt":
                bkey = ",".join(sorted(str(t["collection"]) for t in tables))
                if bkey not in (conf.get("bt_keys") or []):
                    ok, why = billing.take_bt_import(uid)
                    if not ok:
                        return self._json(billing.deny(uid, why), 402)
                    conf["bt_keys"] = (conf.get("bt_keys") or []) + [bkey]
            if not kind:
                conf.update({"url": url, "mapping": mapping, "title": title})
            tsid = str(body.get("ts") or "")
            tsid = tsid if tsid.isdigit() and tsid != "0" and not kind else ""
            job = start_import(uid, tables, mapping, body.get("options") or {}, kind, run, tsid)
            billing.spend_import(uid)
            when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            # запись про базу кладём до того, как перенос закончится: браузер
            # могут закрыть посреди работы, а сделки уже поедут в журнал
            notion_add_source(conf, {"id": job.batch, "url": url, "title": title,
                                     "when": when, "mapping": mapping, "kind": kind})
            conf["last"] = {"id": job.batch, "count": 0, "when": when}
            notion_save(uid, conf)
            return self._json(job.snapshot(), 202)

        # ---- аналіз дня ----
        if p == "/api/share/shot":
            # картинка для превью посилання: малює її сторінка, ми лише
            # кладемо поруч зі знімком і віддаємо ім'я
            try:
                name = day_store.save_shot(uid, (body or {}).get("data") or "", SHOTS, "sg")
            except ValueError as e:
                return self._json({"error": str(e), "code": getattr(e, "code", "")},
                                  getattr(e, "status", 400))
            return self._json({"file": name})

        # ---- рахунки ----
        if p == "/api/accounts":
            acc = (body or {}).get("account") or {}
            name = str(acc.get("name") or "").strip()
            if not name:
                return self._json({"error": "no name"}, 400)
            acc_id = acc.get("id")
            try:
                acc_id = int(acc_id) if acc_id not in (None, "") else None
            except (TypeError, ValueError):
                return self._json({"error": "bad id"}, 400)
            # Двох рахунків з однією назвою бути не може: угоди звʼязані
            # саме по імені, і розрізнити їх було б нічим. Але відмовляти
            # через це — погана відповідь: два челенджі однієї фірми
            # одного розміру людина заводить постійно. Тому сервер сам
            # дописує номер («FTMO 100k 2») і повертає підсумкову назву.
            if acc_id is None:
                return self._json({"account": accounts_store.add(uid, acc)})
            saved = accounts_store.put(uid, acc_id, acc)
            if not saved:
                return self._json({"error": "not found"}, 404)
            return self._json({"account": saved})

        if p == "/api/accounts/drop":
            try:
                acc_id = int((body or {}).get("id"))
            except (TypeError, ValueError):
                return self._json({"error": "bad id"}, 400)
            accounts_store.drop(uid, acc_id)
            return self._json({"ok": True})

        # ---- нотатки ----
        if p == "/api/notes":
            n = notes_store.save(uid, (body or {}).get("note"))
            if not n:
                return self._json({"error": "not saved"}, 400)
            return self._json({"note": n})

        if p == "/api/notes/drop":
            try:
                nid = int((body or {}).get("id"))
            except (TypeError, ValueError):
                return self._json({"error": "bad id"}, 400)
            notes_store.drop(uid, nid)
            return self._json({"ok": True})

        # ---- журнали бектесту ----
        if p == "/api/bt/journals":
            j = (body or {}).get("journal") or {}
            if not str(j.get("name") or "").strip():
                return self._json({"error": "no name"}, 400)
            jid = j.get("id")
            try:
                jid = int(jid) if jid not in (None, "", 0) else None
            except (TypeError, ValueError):
                return self._json({"error": "bad id"}, 400)
            if jid is None:
                # `adopt` — під яким імʼям угоди лежать зараз (і порожнім
                # теж): новий журнал забирає їх собі.
                adopt = (body or {}).get("adopt")
                adopt = str(adopt) if adopt is not None else None
                return self._json({"journal": bt_journals_store.add(uid, j, adopt)})
            saved = bt_journals_store.put(uid, jid, j)
            if not saved:
                return self._json({"error": "not found"}, 404)
            return self._json({"journal": saved})

        if p == "/api/bt/journals/drop":
            try:
                jid = int((body or {}).get("id"))
            except (TypeError, ValueError):
                return self._json({"error": "bad id"}, 400)
            got = bt_journals_store.drop(uid, jid)
            if got is None:
                return self._json({"error": "not found"}, 404)
            delete_files(got[1])
            return self._json({"ok": True, "removed": got[0]})

        if p == "/api/day/shot":
            # затискання Ctrl+V сотнями — не робочий сценарій: понад 60 картинок
            # за хвилину від однієї людини притримуємо
            if ratelimit.check(["shot:%s" % uid], limit=60):
                return self._json({"error": "занадто багато картинок за хвилину"}, 429)
            ratelimit.miss(["shot:%s" % uid], limit=60)
            try:
                name = day_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e), "code": getattr(e, "code", "")},
                                  getattr(e, "status", 400))
            return self._json({"file": name})

        if p.startswith("/api/day/"):
            date = p[len("/api/day/"):]
            if not day_store.valid_date(date):
                return self._json({"error": "bad date"}, 400)
            data = (body or {}).get("day")
            if data is None:
                day_store.drop(uid, date)
            else:
                day_store.put(uid, date, dict(data))
            return self._json({"ok": True})

        # ---- торгова стратегія ----
        if p == "/api/ts":
            data = dict((body or {}).get("ts") or {})
            # правки лягають у ту стратегію, яку людина зараз бачить
            kind = "bt" if (body or {}).get("kind") == "bt" else ""
            sid = (body or {}).get("sid") or 0
            ts_store.put(uid, data, kind, sid)
            ts_store.sweep(uid, data, SHOTS, kind, sid)  # старі скріни за собою прибираємо
            return self._json({"ok": True})

        # ---- кілька стратегій: завести, назвати, прибрати ----
        if p == "/api/ts/new":
            b = body or {}
            sid = ts_store.create(uid, b.get("name") or "",
                                  b.get("copy") if b.get("copy") is not None else None)
            if not sid:
                return self._json({"error": "too many"}, 400)
            return self._json({"id": sid, "list": ts_store.lst(uid)})

        if p == "/api/ts/rename":
            b = body or {}
            ts_store.rename(uid, b.get("sid") or 0, b.get("name") or "")
            return self._json({"list": ts_store.lst(uid)})

        if p == "/api/ts/drop":
            sid = (body or {}).get("sid") or 0
            if not ts_store.drop(uid, sid):
                return self._json({"error": "can't"}, 400)
            ts_store.sweep(uid, {}, SHOTS, "", sid)
            return self._json({"list": ts_store.lst(uid)})

        # Звірка щойно записаної угоди з ТС. Окремим запитом, а не всередині
        # POST /api/trades: збереження має бути миттєвим, а тут ще й модель.
        if p == "/api/ts/check":
            tid = str((body or {}).get("id") or "").strip()
            trade = db.get_trade(tid, uid) if tid else None
            # звіряємо з тією стратегією, під якою угоду записали
            ts = ts_store.get(uid, sid=(trade or {}).get("ts") or 0)
            if not trade or not ts:
                return self._json({"items": [], "text": ""})
            # Бэктест с торговой системой не сверяем: список дня собирается
            # из реальных сделок, и самой сделки в нём нет.
            if trade.get("kind") == "bt":
                return self._json({"items": [], "text": ""})
            day = ts_check.same_day(db.list_trades(uid, db.strat_kind(trade.get("ts") or "0")), trade)
            items = ts_check.check(ts, trade, day)
            lang = str((body or {}).get("lang") or "ru")
            # Розходження рахує код і вони безкоштовні завжди; модель тут
            # лише переказує їх по-людськи. Скінчилась порція — лишаємо
            # сам перелік, підписи до кодів у сторінки свої.
            text = (ts_check.say(items, lang if lang in ("uk", "ru", "en") else "ru")
                    if billing.can_use_ai(uid)[0] else "")
            # мовчазний помічник виглядає зламаним: коли звіряти нема за
            # що, кажемо про це прямо, а не вдаємо, що все гаразд
            return self._json({"items": items, "text": text,
                               "hint": "" if items else ts_check.gaps(ts, trade)})

        if p == "/api/ts/clear":
            kind = "bt" if (body or {}).get("kind") == "bt" else ""
            sid = (body or {}).get("sid") or 0
            ts_store.sweep(uid, {}, SHOTS, kind, sid)
            ts_store.clear(uid, kind, sid)
            return self._json({"ok": True})

        if p == "/api/ts/shot":
            if ratelimit.check(["shot:%s" % uid], limit=60):
                return self._json({"error": "занадто багато картинок за хвилину"}, 429)
            ratelimit.miss(["shot:%s" % uid], limit=60)
            try:
                name = ts_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e), "code": getattr(e, "code", "")},
                                  getattr(e, "status", 400))
            return self._json({"file": name})

        if p == "/api/ts/notion":
            # Сторінок може бути кілька: у Notion систему розкладають по
            # розділах — контекст окремо, моделі входу окремо. Старий виклик
            # з одним "url" лишається робочим.
            b = body or {}
            # Дозвіл і списання одним запитом: пачка одночасних питань
            # інакше проходила перевірку всі разом (див. billing.take_ai).
            ok, why = billing.take_ai(uid)
            if not ok:
                return self._json(billing.deny(uid, why), 402)
            links = b.get("urls") if isinstance(b.get("urls"), list) else None
            try:
                draft = ts_notion.read(links if links else (b.get("url") or ""),
                                       uid, SHOTS)
            except Exception as e:
                return self._json({"error": str(e) or "не вдалось прочитати сторінку"}, 400)
            return self._json({"ts": draft})

        if p == "/api/trades":
            if not isinstance(body, dict) or not str(body.get("pair", "")).strip():
                return self._json({"error": "bad json or empty pair"}, 400)
            # Ключ від форми: та сама угода, надіслана вдруге (відповідь на
            # перше збереження загубилась у мережі), — віддаємо записану, а
            # не робимо двійника. Перевіряємо до ліміту: повтор не має
            # з'їдати ще одну безкоштовну угоду.
            cid = str(body.get("cid") or "")
            tid = cid if re.fullmatch(r"w[0-9a-z]{12,32}", cid) else new_id()
            if tid == cid:
                old = db.get_trade(tid, uid)
                if old:
                    return self._json(old, 201)
            t = clean_trade(body, tid)
            user = db.get_user(uid)
            # Спершу дозвіл, і лише потім робота: скріни важкі, а відмова
            # їх однаково викине. Це швидка відмова, а не застава — межу
            # тримає take_trade нижче, вже разом зі списанням.
            ok, why = billing.can_add_trade(user, t.get("kind"))
            if not ok:
                return self._json(billing.deny(user, why), 402)
            try:
                save_screenshots(t, uid)
            except filestore.ShotError as e:
                return self._shot_reply(e)
            # Місце займаємо до запису: інакше пачка одночасних запитів
            # проходить перевірку всі разом і кладе більше, ніж дозволено.
            ok, why = billing.take_trade(user, t.get("kind"))
            if not ok:
                return self._json(billing.deny(user, why), 402)
            # У бэктеста эмоции нет: входа не было, спрашивать не о чем.
            ask = (t.get("kind") != "bt"
                   and not str(t.get("emotion") or "").strip()
                   and user["telegram_id"] is not None)
            try:
                db.insert_trade(uid, t, "pending" if ask else "na")
            except Exception:
                # Записати не вийшло — місце віддаємо назад, інакше воно
                # згорить ні за що.
                billing.release_trade(user, t.get("kind"))
                raise
            if ask:
                ask_emotion_later(user, t)
            return self._json(t, 201)

        if p == "/api/import":
            if body is None:
                return self._json({"error": "bad json"}, 400)
            # Перенесення файлом — те саме перенесення, що й з Notion, і
            # ліміт у них спільний: три рази в перші 30 днів. Інакше повз
            # заслон на 20 угод можна було б завезти хоч тисячу таблицею.
            ok, why = billing.take_import(uid)
            if not ok:
                return self._json(billing.deny(uid, why), 402)
            items = body if isinstance(body, list) else body.get("trades") or []
            batch = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = clean_trade(it, new_id())
                try:
                    save_screenshots(t, uid)
                except filestore.ShotError:
                    t["screenshots"] = []   # угоду з файлу беремо, битий скрін — ні
                batch.append(t)
            # Перенесення вже зайнято вище (take_import), тому тут рахувати
            # нема чого. Порожній файл — окремий випадок: людині не додали
            # нічого, і з'їдати за це одне з трьох було б несправедливо.
            added = db.insert_trades(uid, batch)
            if not added:
                billing.release_import(uid)
            return self._json({"ok": True, "added": added})

        self.send_response(404); self.end_headers()

    # ---------- PUT ----------
    def do_PUT(self):
        if self._flooding(): return
        if self._old_host(): return
        p = urlparse(self.path).path
        # Тіло читаємо тут, а не в кожній гілці: замок нижче відповідає
        # замкненому одразу, а відповідь без забраних байтів лишила б їх
        # у з'єднанні (див. do_POST).
        body = self._body()
        if self._too_big:
            return self._too_big_reply()
        if self._locked_out(p): return

        if p == "/api/prefs":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            if len(json.dumps(body, ensure_ascii=False)) > PREFS_MAX:
                return self._json({"error": "too big"}, 413)
            prefs_save(uid, body)
            return self._json({"ok": True})

        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        uid = self._uid()
        if not uid:
            return self._json({"error": "auth required"}, 401)
        tid = m.group(1)
        if not isinstance(body, dict):
            return self._json({"error": "bad json"}, 400)
        old = db.get_trade(tid, uid)
        if not old:
            return self._json({"error": "not found"}, 404)
        t = clean_trade(body, tid)
        # Тип ставится при записи и правкой не меняется: иначе сделка
        # переехала бы между реальным журналом и бэктестом.
        t["kind"] = old.get("kind") or ""
        # хто правив без поля стратегії (бот, старий кеш сторінки) — не скидаємо її
        if "ts" not in body:
            t["ts"] = old.get("ts") or ""
        try:
            save_screenshots(t, uid, old)
        except filestore.ShotError as e:
            return self._shot_reply(e)
        old_files = {s["file"] for s in old.get("screenshots") or [] if s.get("file")}
        new_files = {s["file"] for s in t["screenshots"] if s.get("file")}
        db.update_trade(uid, t)
        delete_files(old_files - new_files)
        return self._json(t)

    # ---------- DELETE ----------
    def do_DELETE(self):
        if self._flooding(): return
        if self._old_host(): return
        p = urlparse(self.path).path
        if self._locked_out(p): return
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        uid = self._uid()
        if not uid:
            return self._json({"error": "auth required"}, 401)
        tid = m.group(1)
        old = db.get_trade(tid, uid)
        if not old:
            return self._json({"error": "not found"}, 404)
        db.delete_trade(uid, tid)
        delete_files([s["file"] for s in old.get("screenshots") or [] if s.get("file")])
        return self._json({"ok": True})


class Server(HTTPServer):
    """Сервер із постійною бригадою робітників.

    Було: на кожне з'єднання народжувався окремий потік. Поки людина одна —
    непомітно, а на сотні одночасних відвідувачів це сотні потоків, кожен зі
    своїм стеком; пам'ять закінчується раніше, ніж процесор.

    Стало: робітників рівно стільки, скільки ми дозволили (WEB_WORKERS), і
    вони не помирають після відповіді, а беруть наступне з'єднання. Зайві
    з'єднання чекають у черзі операційної системи — довше, але сервер живий.

    Чому саме 64. Робітник більшість часу не рахує, а чекає: то базу, то
    відповідь Gemini для «Помічника». Той, хто чекає, процесор не їсть, тож
    робітників має сенс мати більше, ніж ядер.
    """
    # Довжина черги з'єднань, які ще ніхто не взяв. За замовчуванням 5 —
    # на сплеску решта отримувала б «з'єднання скинуто».
    request_queue_size = 128
    allow_reuse_address = True

    def __init__(self, addr, handler, workers):
        super().__init__(addr, handler)
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="web")

    def process_request(self, request, client_address):
        self._pool.submit(self._serve, request, client_address)

    def _serve(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self._pool.shutdown(wait=False)


if __name__ == "__main__":
    db.init()
    _ref_init()
    _emo_init()
    _emo_init2()
    _pairs_init()
    # календар гріємо одразу: помічник підкладає новини до кожного питання,
    # а поки кеш порожній, перше питання після перезапуску летить до моделі
    # без них — і вона чесно відповідає, що новин немає
    threading.Thread(target=calendar_feed.cached_events, daemon=True).start()
    if config.RUN_JOBS:
        # щоденний зліпок журналу: тихо, у фоні, раз на добу
        backup.start()
        # розсилка: черга листів, не більше MAIL_DAILY на добу
        mailout.start()
        # оплата криптою: дивимось у блокчейн, чи не прийшли гроші
        crypto_pay.start()
    if config.RUN_BOT and config.BOT_TOKEN:
        # бот живе поруч із сайтом: на безкоштовному хостингу другий
        # процес тримати ніде, а опитування Телеграма нікому не заважає
        import bot
        threading.Thread(target=bot.main, daemon=True).start()
        print("Telegram bot -> у тому самому процесі")
    print("Trading Journal -> http://localhost:%d/  (%d робітників, Ctrl+C stop)"
          % (PORT, config.WEB_WORKERS))
    Server((config.HOST, PORT), H, config.WEB_WORKERS).serve_forever()
