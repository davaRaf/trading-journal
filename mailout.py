# -*- coding: utf-8 -*-
"""
Рассылки по почте: письмо из админки всем (или части людей).

Как устроено.
- Письмо пишет владелец в /admin/mail: тема, текст, кому. «Себе» уходит
  сразу — посмотреть, как выглядит. «Всем» кладётся в очередь (mail_queue).
- Очередь разбирает фоновый поток понемногу: у бесплатного тарифа Resend
  не больше 100 писем в сутки (MAIL_DAILY). Не влезло сегодня — уйдёт завтра,
  письма не теряются и не дублируются.
- В каждом письме ссылка «Отписаться» (подписанная, без входа), в профиле —
  тот же переключатель. Отписавшимся не пишем ничего, кроме служебного
  (пароль, подтверждение почты — это authmail.py, не сюда).

Отправка — mailer.send: Resend по API, если задан RESEND_API_KEY, иначе
старый SMTP.
"""
import datetime
import hashlib
import hmac
import html
import threading
import time

import auth
import config
import db
import mailer

SCHEMA = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS mail_news BOOLEAN NOT NULL DEFAULT TRUE;
CREATE TABLE IF NOT EXISTS mail_queue (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
  email      TEXT NOT NULL,
  subject    TEXT NOT NULL,
  body       TEXT NOT NULL,
  campaign   TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at    TIMESTAMPTZ,
  error      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS mail_queue_wait ON mail_queue (sent_at, id);
"""

_ready = False
_lock = threading.Lock()


def init():
    global _ready
    if _ready:
        return
    with _lock:
        if not _ready:
            with db.connect() as conn:
                conn.execute(SCHEMA)
            _ready = True


# ------------------------------------------------------------ отписка ----

def unsub_token(uid):
    return hmac.new(auth._secret(), ("unsub.%d" % int(uid)).encode(), hashlib.sha256).hexdigest()[:32]


def unsub_url(uid):
    return "%s/unsub?u=%d&t=%s" % (config.SITE_URL.rstrip("/"), int(uid), unsub_token(uid))


def unsubscribe(uid, token):
    """Отписка по ссылке из письма. True — получилось."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if not hmac.compare_digest(unsub_token(uid), str(token or "")):
        return False
    set_news(uid, False)
    return True


def set_news(uid, on):
    init()
    with db.connect() as conn:
        conn.execute("UPDATE users SET mail_news=%s WHERE id=%s", (bool(on), uid))
        conn.commit()


# ------------------------------------------------------------ письмо ----

def render(body, uid=None):
    """Текст владельца → письмо в стиле журнала. Абзацы — по пустой строке,
    строка «[Кнопка](https://…)» становится кнопкой."""
    parts = []
    for block in [b.strip() for b in (body or "").replace("\r", "").split("\n\n") if b.strip()]:
        if block.startswith("[") and "](" in block and block.endswith(")"):
            label, url = block[1:-1].split("](", 1)
            if url.startswith("https://") or url.startswith("http://"):
                parts.append('<p style="margin:26px 0"><a href="%s" style="display:inline-block;padding:13px 22px;'
                             'border-radius:10px;background:#3ccf8e;color:#0b120e;font-weight:600;text-decoration:none">%s</a></p>'
                             % (html.escape(url, quote=True), html.escape(label)))
                continue
        parts.append('<p style="margin:0 0 16px;line-height:1.65">%s</p>'
                     % html.escape(block).replace("\n", "<br>"))
    foot = ""
    if uid:
        foot = ('<p style="margin:28px 0 0;font-size:12px;color:#8a8f98">Это письмо от StatsAI — журнала трейдера. '
                'Не хочешь получать новости? <a href="%s" style="color:#8a8f98">Отписаться</a>.</p>'
                % html.escape(unsub_url(uid), quote=True))
    return ('<!doctype html><html><body style="margin:0;background:#f2f4f8;padding:24px 12px;'
            'font-family:Segoe UI,Arial,sans-serif;color:#171b24">'
            '<div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:16px;padding:30px 28px">'
            '<div style="font-weight:700;font-size:18px;margin-bottom:22px">Stats<span style="color:#3ccf8e">AI</span></div>'
            + "".join(parts) + foot + "</div></body></html>")


def plain(body, uid=None):
    """Текстовая версия — для почтовиков без HTML и для антиспама."""
    text = (body or "").replace("\r", "")
    if uid:
        text += "\n\n—\nОтписаться: " + unsub_url(uid)
    return text


def send_one(email, subject, body, uid=None):
    return mailer.send(email, subject, plain(body, uid), html=render(body, uid),
                       headers={"List-Unsubscribe": "<%s>" % unsub_url(uid)} if uid else None)


# ------------------------------------------------------------ кому ----

AUDIENCES = {
    "all":  "Всем, кто подтвердил почту",
    "paid": "Только с подпиской",
    "free": "Только без подписки",
}


def recipients(audience, ref=""):
    """[(uid, email)] — подтверждённая почта, не отписались."""
    init()
    import billing
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE email_confirmed_at IS NOT NULL AND mail_news "
            "AND email IS NOT NULL AND email <> '' ORDER BY id").fetchall()
    out = []
    for u in rows:
        if ref and (u.get("ref_source") or "") != ref:
            continue
        if audience in ("paid", "free"):
            paid = billing.active(u)
            if (audience == "paid") != paid:
                continue
        out.append((u["id"], u["email"]))
    return out


def enqueue(subject, body, audience="all", ref=""):
    init()
    people = recipients(audience, ref)
    camp = "%s %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), subject[:60])
    with db.connect() as conn:
        for uid, email in people:
            conn.execute("INSERT INTO mail_queue (user_id, email, subject, body, campaign) "
                         "VALUES (%s,%s,%s,%s,%s)", (uid, email, subject, body, camp))
        conn.commit()
    return len(people)


# ------------------------------------------------------------ очередь ----

def stats():
    init()
    with db.connect() as conn:
        r = conn.execute(
            "SELECT count(*) FILTER (WHERE sent_at IS NULL AND error='') AS wait, "
            "count(*) FILTER (WHERE sent_at >= date_trunc('day', now())) AS today, "
            "count(*) FILTER (WHERE error <> '') AS failed FROM mail_queue").fetchone()
        last = conn.execute("SELECT campaign, count(*) AS n, count(sent_at) AS sent FROM mail_queue "
                            "GROUP BY campaign ORDER BY max(id) DESC LIMIT 5").fetchall()
    return {"wait": r["wait"], "today": r["today"], "failed": r["failed"],
            "limit": config.MAIL_DAILY, "campaigns": [dict(x) for x in last]}


def run_once():
    """Отправить, сколько позволяет суточный лимит. Возвращает, сколько ушло."""
    init()
    if not mailer.enabled():
        return 0                       # почта не настроена — очередь ждёт, а не сгорает
    st = stats()
    room = max(0, config.MAIL_DAILY - st["today"])
    if not room or not st["wait"]:
        return 0
    with db.connect() as conn:
        batch = conn.execute("SELECT q.*, u.mail_news FROM mail_queue q LEFT JOIN users u ON u.id=q.user_id "
                             "WHERE q.sent_at IS NULL AND q.error='' ORDER BY q.id LIMIT %s",
                             (room,)).fetchall()
    sent = 0
    for m in batch:
        if m["user_id"] and not m["mail_news"]:
            err, ok = "отписался", False            # отписался, пока письмо ждало
        else:
            ok = send_one(m["email"], m["subject"], m["body"], m["user_id"])
            err = "" if ok else "не ушло"
        with db.connect() as conn:
            conn.execute("UPDATE mail_queue SET sent_at=CASE WHEN %s THEN now() ELSE sent_at END, "
                         "error=%s WHERE id=%s", (ok, err, m["id"]))
            conn.commit()
        sent += ok
        time.sleep(0.6)                              # Resend: не больше 2 писем в секунду
    return sent


def loop():
    time.sleep(120)
    import mailauto
    checked = 0
    while True:
        # автоматические письма раскладываем раз в час и только днём по Киеву
        try:
            if time.time() - checked > 3600 and mailauto.due_hours():
                checked = time.time()
                got = mailauto.check()
                if any(got.values()):
                    print("рассылка: автописьма в очереди —", got, flush=True)
        except Exception as ex:
            print("автописьма:", ex, flush=True)
        try:
            n = run_once()
            if n:
                print("рассылка: ушло писем —", n, flush=True)
        except Exception as ex:
            print("рассылка:", ex, flush=True)
        time.sleep(600)


def start():
    threading.Thread(target=loop, daemon=True, name="mailout").start()
