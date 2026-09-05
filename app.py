# -*- coding: utf-8 -*-
"""
Trading Journal — сервер журнала.
Только стандартная библиотека Python плюс драйвер Postgres. Запуск:  python app.py
Данные: Postgres (DATABASE_URL), скриншоты: data/screenshots/
"""
import base64
import datetime
import gzip
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from urllib.parse import urlparse, unquote

import assistant
import delete_ai
import auth
import backup
import config
import db
import emotions
import filestore
import share_store
import llm
from psycopg.types.json import Jsonb

import notion_import as notion
import notion_public as npub
import notion_sync
import oauth
import ratelimit
import day_store
import tg_api
import tidy
import ts_check
import ts_notion
import ts_store
import calendar_feed
import tv_calendar
from calendar_feed import calendar_events, event_history

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


DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)


def save_screenshots(trade):
    """Скриншоты с base64-данными сохраняем в файлы; уже сохранённые оставляем."""
    out = []
    shots = trade.get("screenshots") or []
    for i, s in enumerate(shots):
        tf = re.sub(r"[^0-9A-Za-zА-Яа-я]", "", str(s.get("tf") or "img"))[:8] or "img"
        if s.get("data"):
            m = DATAURL_RE.match(s["data"])
            if not m:
                continue
            ext = m.group(1).replace("jpeg", "jpg")
            try:
                raw = base64.b64decode(m.group(2))
            except Exception:
                continue
            name = "%s_%d_%s.%s" % (trade["id"], int(time.time() * 1000) % 100000000 + i, tf, ext)
            keep_file(name, raw)
            out.append({"tf": s.get("tf") or "", "file": name})
        elif s.get("file"):
            out.append({"tf": s.get("tf") or "", "file": s["file"]})
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
    try:
        filestore.delete([os.path.basename(n) for n in names if n])
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
SHARE_MAX = 256 * 1024          # больше снимку не нужно
SHARE_TTL = {                   # что можно выбрать в интерфейсе, в секундах
    "1h":   3600,
    "24h":  86400,
    "7d":   604800,
    "30d":  2592000,
    "forever": 0,               # 0 — без срока
}
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


def tf_rank(tf):
    t = str(tf or "").upper().replace(" ", "")
    return TF_ORDER.index(t) if t in TF_ORDER else len(TF_ORDER)


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
    esc_ = lambda x: str(x).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    tags = [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="StatsAI">',
        '<meta property="og:title" content="%s">' % esc_(title),
        '<meta property="og:description" content="%s">' % esc_(desc),
        '<meta property="og:url" content="%s/s/%s">' % (base, sid),
        '<meta name="twitter:title" content="%s">' % esc_(title),
        '<meta name="twitter:description" content="%s">' % esc_(desc),
    ]
    if shot:
        img = "%s/api/share/%s/shot/%s" % (base, sid, shot)
        tags += ['<meta property="og:image" content="%s">' % img,
                 '<meta name="twitter:image" content="%s">' % img,
                 '<meta name="twitter:card" content="summary_large_image">']
    else:
        tags += ['<meta name="twitter:card" content="summary">']
    return "\n".join(tags)


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
    верна, даже если браузер закрыли посреди переноса. Перенесение, от
    которого в журнале ничего не осталось, из списка выпадает само.
    """
    conf = notion_conf(uid) if conf is None else conf
    counts = db.count_imports(uid)
    out = []
    for s in conf.get("sources") or []:
        n = counts.get(s["id"]) or 0
        if n:
            out.append(dict(s, count=n))
    out.sort(key=lambda s: s.get("when") or "", reverse=True)
    return out


def notion_add_source(conf, rec):
    src = [s for s in (conf.get("sources") or []) if s["id"] != rec["id"]]
    src.append(rec)
    conf["sources"] = src[-NOTION_SOURCES_MAX:]
    return conf


def add_trades(user_id, items):
    """Кладём пачку сделок в журнал. Вызывается из фонового потока импорта."""
    batch = []
    for it in items:
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
    if not removed:
        return 0
    delete_files(orphan_files)
    conf = notion_conf(user_id)
    conf["sources"] = [s for s in conf.get("sources") or [] if s["id"] != batch]
    if (conf.get("last") or {}).get("id") == batch:
        conf.pop("last", None)
    notion_save(user_id, conf)
    return removed


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


def start_import(user_id, tables, mapping, opts):
    jid = secrets.token_urlsafe(6)
    job = notion.Job(jid)
    job.user_id = user_id          # чтобы чужое задание нельзя было подсмотреть
    with _jobs_lock:
        _jobs[jid] = job
        # старые задания не копим
        for old_id in list(_jobs)[:-8]:
            _jobs.pop(old_id, None)
    known, seen = db.notion_known(user_id)
    # отпечатки того, что уже в журнале: по ним узнаём сделку, записанную
    # в другой базе Notion, — там у неё свой notion_id, и он не совпадёт
    rows = db.list_trades(user_id)
    marks = tidy.prints(rows)
    th = threading.Thread(
        target=npub.run_public_import,
        args=(job, tables, mapping, opts, SHOTS, known, seen,
              lambda items: add_trades(user_id, items), marks),
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


def user_public(user):
    return {"id": user["id"], "email": user["email"], "nickname": user["nickname"],
            "telegram": user["telegram_username"] or (str(user["telegram_id"])
                                                      if user["telegram_id"] else None),
            "telegram_linked": user["telegram_id"] is not None,
            "digest_hour": user["digest_hour"], "digest_minute": user["digest_minute"],
            "digest_enabled": user["digest_enabled"],
            "public_journal": bool(user["public_journal"])}


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
    out["screenshots"] = [{"tf": s.get("tf") or "", "file": s.get("file") or ""}
                          for s in (t.get("screenshots") or []) if s.get("file")]
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
    # Скільки чекати на самого клієнта. Без цього браузер, який відкрив
    # з'єднання і замовк (обірваний вай-фай, вкладка в сплячці), тримав би
    # робітника вічно — а їх обмежена кількість.
    timeout = 30

    def log_message(self, fmt, *args):  # тихий лог
        pass

    # ---------- ответы ----------
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

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _uid(self):
        return auth.current_user_id(self)

    def _guest(self):
        """Адреса гостя. За проксі хостингу справжня приходить у заголовку,
        а client_address — це вже сам проксі, один на всіх.

        Заголовок можна підробити, тому на ньому одному не тримаємось:
        поруч рахуємо спроби ще й за логіном, і його підробкою не обійти."""
        fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
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

    def do_GET(self):
        p = unquote(urlparse(self.path).path)

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

        if p.startswith("/api/share/"):
            rec = share_read(p[len("/api/share/"):])
            if rec is None:
                return self._json({"error": "посилання не знайдено або прострочене"}, 404)
            # Хазяїна віддаємо ніком і тільки поки журнал відкритий: id
            # користувача назовні не потрібен, а стан питаємо щоразу заново.
            out = {k: v for k, v in rec.items() if k != "user_id"}
            nick = public_owner(rec.get("user_id"))
            if nick:
                out["owner"] = {"nick": nick}
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
                proto = self.headers.get("X-Forwarded-Proto") or "http"
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
                base = "%s://%s" % (proto, host)
                d = rec.get("data") or {}
                html = html.replace("<title>StatsAI</title>",
                                    "<title>%s · StatsAI</title>" % (d.get("title") or "StatsAI")
                                    .replace("<", "&lt;"), 1)
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
            self.send_header("Set-Cookie", oauth.state_cookie(state))
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
                user = oauth.find_or_create_user(prov, ext_id, email, name)
            except Exception as ex:
                print("oauth %s: %s" % (prov, ex))
                self.send_response(302)
                self.send_header("Location", "/login?err=oauth")
                self.send_header("Set-Cookie", oauth.clear_state_cookie())
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", auth.cookie_header(auth.make_session(user["id"])))
            self.send_header("Set-Cookie", oauth.clear_state_cookie())
            self.end_headers()
            return

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
            return self._json(db.list_trades(uid))

        # ---- аналіз дня (day_store.py) ----
        if p.startswith("/api/day/"):
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            rest = p[len("/api/day/"):]
            if rest == "list":
                return self._json({"days": day_store.days(uid)})
            if rest == "stats":
                since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
                return self._json({"notes": day_store.notes_since(uid, since), "since": since})
            if not day_store.valid_date(rest):
                return self._json({"error": "bad date"}, 400)
            return self._json({"day": day_store.get(uid, rest)})

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
            return self._json({"ts": ts_store.get(uid)})

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

        if p == "/api/calendar":
            events, warn = calendar_events()
            return self._json({"events": events, "warning": warn})

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
                # угоди з Notion уже в журналі — значить, підключали, навіть якщо
                # запис про посилання не зберігся
                "imported": bool(db.notion_known(uid)[1]),
                # коли востаннє перечитували Notion самі (notion_sync.py)
                "auto": conf.get("auto") or None,
                "autoHours": notion_sync.EVERY // 3600,
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

        # публічні сторінки: їх вимагає Google для входу через акаунт
        if p in ("/privacy", "/terms"):
            return self._file(os.path.join(STATIC, p.strip("/") + ".html"), "text/html; charset=utf-8")

        if p == "/login":
            # Месенджери хочуть в og:image повну адресу, а у файлі вона
            # відносна — сторінка ж не знає, під яким доменом її відкриють.
            # Дописуємо базу на віддачі.
            try:
                with open(os.path.join(STATIC, "login.html"), "r", encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                self.send_response(404); self.end_headers(); return
            html = html.replace('content="/static/', 'content="%s/static/' % self._base())
            if 'property="og:url"' not in html:
                html = html.replace("</title>",
                                    '</title>\n<meta property="og:url" content="%s/">' % self._base(), 1)
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
            # прототипы: экран входа, новости, знак — чтобы смотреть с того же адреса
            name = os.path.normpath(p[len("/design/"):]).replace("\\", "/")
            if name.startswith("..") or name in ("", "."):
                self.send_response(403); self.end_headers(); return
            full = os.path.join(ROOT, "design", name)
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
            return self._file(os.path.join(STATIC, "index.html"),
                              "text/html; charset=utf-8")

        if p in ("/", "/index.html"):
            if not self._uid():
                return self._redirect("/login")
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")

        if p == "/demo":
            # Журнал без акаунта, на демонстраційних даних. Сюди ведуть
            # сторінка «поділитись» і посилання зі сторінки входу. Сторінка
            # сама зрозуміє, що сесії немає (/api/trades віддасть 401), і
            # ввімкне режим гостя: дивитись можна все, писати — ні.
            if self._uid():
                return self._redirect("/")
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")

        if p.startswith("/static/"):
            name = os.path.normpath(p[len("/static/"):]).replace("\\", "/")
            if name.startswith(".."):
                self.send_response(403); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"css":"text/css; charset=utf-8","js":"application/javascript; charset=utf-8",
                     "html":"text/html; charset=utf-8","png":"image/png","svg":"image/svg+xml"}.get(ext,"application/octet-stream")
            # у файлів є версія в адресі (?v=5), тому кешуємо назавжди:
            # правка версії сама змусить браузер піти за новим
            versioned = "v=" in urlparse(self.path).query
            return self._file(os.path.join(STATIC, name), ctype,
                              self.FOREVER if versioned else None)

        self.send_response(404); self.end_headers()

    # ---------- POST ----------
    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()

        # ---- вход и регистрация ----
        if p == "/api/auth/register":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            email = str(body.get("email") or "").strip()
            nickname = str(body.get("nickname") or "").strip()
            password = str(body.get("password") or "")
            if not email or not nickname or len(password) < 6:
                return self._json({"error": "потрібні пошта, нікнейм і пароль від 6 символів", "code": "need_fields"}, 400)
            pw_hash, pw_salt, iters = auth.hash_password(password)
            try:
                user = db.create_user(email, nickname, pw_hash, pw_salt, iters)
            except Exception as ex:
                if "unique" in str(ex).lower() or "duplicate" in str(ex).lower():
                    return self._json({"error": "така пошта або нікнейм уже зайняті", "code": "taken"}, 409)
                raise
            return self._json({"user": user_public(user)}, 201,
                              cookie=auth.cookie_header(auth.make_session(user["id"])))

        if p == "/api/auth/login":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            # П'ять невдалих спроб за хвилину — і далі просимо зачекати.
            # Рахуємо і за адресою, і за логіном: перебір з одного місця
            # та перебір одного акаунта з різних адрес — це різні речі.
            who = str(body.get("login") or "").strip().lower()
            keys = ["ip:" + self._guest()] + (["who:" + who] if who else [])
            wait = ratelimit.check(keys)
            if wait:
                return self._json(
                    {"error": "забагато спроб входу — спробуй за %d с" % wait, "code": "too_many", "wait": wait}, 429)
            user = db.get_user_by_login(body.get("login"))
            if not user or not auth.verify_password(str(body.get("password") or ""),
                                                    user["pw_hash"], user["pw_salt"],
                                                    user["pw_iters"]):
                ratelimit.miss(keys)
                return self._json({"error": "невірна пошта або пароль", "code": "bad_login"}, 401)
            ratelimit.forget(keys)
            return self._json({"user": user_public(user)},
                              cookie=auth.cookie_header(auth.make_session(user["id"])))

        if p == "/api/auth/logout":
            return self._json({"ok": True}, cookie=auth.clear_cookie_header())

        # ---- дальше всё только для своих ----
        uid = self._uid()
        # ---- разовая заливка скриншотов при переезде ----
        # Работает, только если задан ADMIN_TOKEN. Нужна один раз: перенести
        # накопленные картинки со старой машины. После переезда переменную убрать.
        if p == "/api/admin/upload-shot":
            token = config.ADMIN_TOKEN
            if not token or self.headers.get("X-Admin-Token") != token:
                return self._json({"error": "no"}, 404)
            name = os.path.basename(str((body or {}).get("name") or ""))
            data = (body or {}).get("data") or ""
            if not name or not re.match(r"^[\w.\-]{4,120}$", name):
                return self._json({"error": "bad name"}, 400)
            dest = os.path.join(SHOTS, name)
            if os.path.exists(dest):
                return self._json({"ok": True, "skipped": True})
            try:
                raw = base64.b64decode(data)
            except Exception:
                return self._json({"error": "bad data"}, 400)
            if len(raw) > 8 * 1024 * 1024:
                return self._json({"error": "too big"}, 400)
            with open(dest, "wb") as f:
                f.write(raw)
            return self._json({"ok": True})

        if p.startswith("/api/") and not uid:
            return self._json({"error": "auth required"}, 401)

        if p == "/api/me/public":
            on = bool((body or {}).get("on"))
            db.set_public(uid, on)
            return self._json({"public_journal": on})

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
            question = str((body or {}).get("question") or "").strip()
            if not question:
                return self._json({"error": "порожнє питання"}, 400)
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає GEMINI_API_KEY"}, 503)
            # історія розмови приходить з браузера — беремо тільки останні репліки
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            # прохання видалити угоди — окрема гілка: модель лише каже, ЩО
            # видаляти, угоди добирає код, а зникають вони тільки після
            # натиснутої кнопки в підтвердженні (delete_ai.py)
            if delete_ai.looks_like(question):
                card = delete_ai.plan(uid, question, history)
                if card:
                    return self._json(card)
            lang = str((body or {}).get("lang") or "")
            return self._json({"answer": assistant.ask(
                uid, question, history, lang if lang in ("uk", "ru", "en") else None)})

        if p == "/api/assistant/nudge":
            lang = str((body or {}).get("lang") or "uk")
            return self._json(assistant.nudge(
                uid, lang if lang in ("uk", "ru", "en") else "uk"))

        if p == "/api/assistant/review":
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає GEMINI_API_KEY"}, 503)
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            return self._json(assistant.review(uid, history))

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
            return self._json({"id": rec["id"], "url": "/s/" + rec["id"],
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
            conf = notion_conf(uid)
            title = body.get("title") or ""
            conf.update({"url": url, "mapping": mapping, "title": title})
            job = start_import(uid, tables, mapping, body.get("options") or {})
            when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            # запись про базу кладём до того, как перенос закончится: браузер
            # могут закрыть посреди работы, а сделки уже поедут в журнал
            notion_add_source(conf, {"id": job.batch, "url": url, "title": title,
                                     "when": when, "mapping": mapping})
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
                return self._json({"error": str(e)}, 400)
            return self._json({"file": name})

        if p == "/api/day/shot":
            try:
                name = day_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
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
            ts_store.put(uid, data)
            ts_store.sweep(uid, data, SHOTS)      # старі скріни за собою прибираємо
            return self._json({"ok": True})

        # Звірка щойно записаної угоди з ТС. Окремим запитом, а не всередині
        # POST /api/trades: збереження має бути миттєвим, а тут ще й модель.
        if p == "/api/ts/check":
            tid = str((body or {}).get("id") or "").strip()
            trade = db.get_trade(tid, uid) if tid else None
            ts = ts_store.get(uid)
            if not trade or not ts:
                return self._json({"items": [], "text": ""})
            day = ts_check.same_day(db.list_trades(uid), trade)
            items = ts_check.check(ts, trade, day)
            lang = str((body or {}).get("lang") or "uk")
            text = ts_check.say(items, lang if lang in ("uk", "ru", "en") else "uk")
            # мовчазний помічник виглядає зламаним: коли звіряти нема за
            # що, кажемо про це прямо, а не вдаємо, що все гаразд
            return self._json({"items": items, "text": text,
                               "hint": "" if items else ts_check.gaps(ts, trade)})

        if p == "/api/ts/clear":
            ts_store.sweep(uid, {}, SHOTS)
            ts_store.clear(uid)
            return self._json({"ok": True})

        if p == "/api/ts/shot":
            try:
                name = ts_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"file": name})

        if p == "/api/ts/notion":
            # Сторінок може бути кілька: у Notion систему розкладають по
            # розділах — контекст окремо, моделі входу окремо. Старий виклик
            # з одним "url" лишається робочим.
            b = body or {}
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
            t = clean_trade(body, new_id())
            save_screenshots(t)
            user = db.get_user(uid)
            ask = not str(t.get("emotion") or "").strip() and user["telegram_id"] is not None
            db.insert_trade(uid, t, "pending" if ask else "na")
            if ask:
                ask_emotion_later(user, t)
            return self._json(t, 201)

        if p == "/api/import":
            if body is None:
                return self._json({"error": "bad json"}, 400)
            items = body if isinstance(body, list) else body.get("trades") or []
            batch = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = clean_trade(it, new_id())
                save_screenshots(t)
                batch.append(t)
            return self._json({"ok": True, "added": db.insert_trades(uid, batch)})

        self.send_response(404); self.end_headers()

    # ---------- PUT ----------
    def do_PUT(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        uid = self._uid()
        if not uid:
            return self._json({"error": "auth required"}, 401)
        tid = m.group(1)
        body = self._body()
        if not isinstance(body, dict):
            return self._json({"error": "bad json"}, 400)
        old = db.get_trade(tid, uid)
        if not old:
            return self._json({"error": "not found"}, 404)
        t = clean_trade(body, tid)
        save_screenshots(t)
        old_files = {s["file"] for s in old.get("screenshots") or [] if s.get("file")}
        new_files = {s["file"] for s in t["screenshots"] if s.get("file")}
        db.update_trade(uid, t)
        delete_files(old_files - new_files)
        return self._json(t)

    # ---------- DELETE ----------
    def do_DELETE(self):
        p = urlparse(self.path).path
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
    if config.RUN_JOBS:
        # щоденний зліпок журналу: тихо, у фоні, раз на добу
        backup.start()
        # і сам перечитує Notion раз на дві години
        notion_sync.start(add=add_trades, fill=blank_filler, conf=notion_conf,
                          save=notion_save, shots=SHOTS, busy=import_busy)
    if config.RUN_BOT and config.BOT_TOKEN:
        # бот живе поруч із сайтом: на безкоштовному хостингу другий
        # процес тримати ніде, а опитування Телеграма нікому не заважає
        import bot
        threading.Thread(target=bot.main, daemon=True).start()
        print("Telegram bot -> у тому самому процесі")
    print("Trading Journal -> http://localhost:%d/  (%d робітників, Ctrl+C stop)"
          % (PORT, config.WEB_WORKERS))
    Server((config.HOST, PORT), H, config.WEB_WORKERS).serve_forever()
