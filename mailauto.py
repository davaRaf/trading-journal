# -*- coding: utf-8 -*-
"""
Автоматические письма (владельцы, 05.10.2026). Четыре вида, каждый — один
раз на повод, все через ту же очередь, что и рассылки (mailout.py):

  start   — через 2–3 дня после регистрации журнал пустой: зовём перенести
            сделки из Notion (или записать первую руками).
  month   — 1-го числа итог прошлого месяца тем, у кого были сделки.
  lapse   — неделя без новых сделок у того, кто вёл журнал: мягкое
            напоминание, одно на каждый перерыв.
  ending  — подписка без автопродления кончается через 3 дня.

Отписавшимся (mail_news = false) не пишем. Неподтверждённой почте тоже.
Проверка идёт раз в час из mailout.loop(), письма уходят днём по Киеву.
"""
import datetime

import assistant
import config
import db
import mailout

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:                      # pragma: no cover
    KYIV = datetime.timezone(datetime.timedelta(hours=3))

SCHEMA = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sub_canceled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mail_start_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mail_lapse_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mail_ending_for TEXT NOT NULL DEFAULT '';
"""
_ready = False


def init():
    global _ready
    if not _ready:
        mailout.init()
        with db.connect() as conn:
            conn.execute(SCHEMA)
        _ready = True


def lang_of(u):
    lg = (u.get("lang") or "").strip()
    if lg in ("uk", "ru", "en"):
        return lg
    try:
        import botlang
        lg = botlang.of(u)
    except Exception:
        lg = ""
    return lg if lg in ("uk", "ru", "en") else "ru"


SITE = config.SITE_URL.rstrip("/")

TEXT = {
"start": {
  "uk": ("Перенеси журнал з Notion за пару хвилин",
         "Ти зареєструвався в StatsAI, але журнал поки порожній.\n\n"
         "Якщо угоди вже лежать у Notion — не переписуй їх руками. Дай посилання на базу, і журнал перенесе все сам: "
         "угоди, нотатки й скріни.\n\n"
         "Одразу побачиш, які сесії й сетапи приносять гроші, а які їх з'їдають.\n\n"
         "[Перенести з Notion](" + SITE + "/?notion=1)\n\n"
         "Немає Notion? Запиши першу угоду — це пів хвилини."),
  "ru": ("Перенеси журнал из Notion за пару минут",
         "Ты зарегистрировался в StatsAI, но журнал пока пустой.\n\n"
         "Если сделки уже лежат в Notion — не переписывай их руками. Дай ссылку на базу, и журнал перенесёт всё сам: "
         "сделки, заметки и скрины.\n\n"
         "Сразу увидишь, какие сессии и сетапы приносят деньги, а какие их съедают.\n\n"
         "[Перенести из Notion](" + SITE + "/?notion=1)\n\n"
         "Нет Notion? Запиши первую сделку — это полминуты."),
  "en": ("Move your Notion journal over in a couple of minutes",
         "You signed up for StatsAI, but your journal is still empty.\n\n"
         "If your trades already live in Notion, don't retype them. Share the database link and the journal moves "
         "everything for you: trades, notes and screenshots.\n\n"
         "You'll see right away which sessions and setups make money and which eat it.\n\n"
         "[Move from Notion](" + SITE + "/?notion=1)\n\n"
         "No Notion? Log your first trade — it takes half a minute."),
},
"lapse": {
  "uk": ("Тиждень без записів",
         "У журналі тиждень немає нових угод — буває.\n\n"
         "Якщо торгував, але не записував, внеси угоди зараз, поки пам'ятаєш деталі: вхід, емоції, помилки. "
         "Через місяць саме вони покажуть, що працює.\n\n"
         "Якщо взяв паузу — гарний момент перечитати свою ТС і подивитися статистику.\n\n"
         "[Відкрити журнал](" + SITE + "/)"),
  "ru": ("Неделя без записей",
         "В журнале неделю нет новых сделок — бывает.\n\n"
         "Если торговал, но не записывал, внеси сделки сейчас, пока помнишь детали: вход, эмоции, ошибки. "
         "Через месяц именно они покажут, что работает.\n\n"
         "Если взял паузу — хороший момент перечитать свою ТС и посмотреть статистику.\n\n"
         "[Открыть журнал](" + SITE + "/)"),
  "en": ("A week without entries",
         "Your journal has had no new trades for a week — it happens.\n\n"
         "If you traded but didn't log it, add the trades now while you still remember the details: entry, "
         "emotions, mistakes. In a month they're what shows you what works.\n\n"
         "If you're taking a break, it's a good moment to reread your system and look at your stats.\n\n"
         "[Open the journal](" + SITE + "/)"),
},
"ending": {
  "uk": ("Підписка закінчується %s",
         "Твоя підписка StatsAI діє до %s. Після цього журнал лишиться, усі угоди й статистика на місці, "
         "але нові угоди понад безкоштовні записати не вийде.\n\n"
         "[Продовжити підписку](" + SITE + "/#plan)"),
  "ru": ("Подписка заканчивается %s",
         "Твоя подписка StatsAI действует до %s. После этого журнал останется, все сделки и статистика на месте, "
         "но новые сделки сверх бесплатных записать не получится.\n\n"
         "[Продлить подписку](" + SITE + "/#plan)"),
  "en": ("Your subscription ends on %s",
         "Your StatsAI subscription runs until %s. After that the journal stays, with every trade and stat in "
         "place, but you won't be able to log trades beyond the free ones.\n\n"
         "[Renew the subscription](" + SITE + "/#plan)"),
},
}

MONTHS = {
  "uk": ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень", "вересень",
         "жовтень", "листопад", "грудень"],
  "ru": ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
         "ноябрь", "декабрь"],
  "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
         "November", "December"],
}
MONTH_L = {
  "uk": ("Твій %s: %s", "Підсумок місяця в журналі StatsAI.", "Результат", "Угод", "Вінрейт", "TP / SL / BE",
         "Найкращий сетап", "Найслабший сетап", "Відкрити місяць у журналі", "Твій %s у журналі"),
  "ru": ("Твой %s: %s", "Итог месяца в журнале StatsAI.", "Результат", "Сделок", "Винрейт", "TP / SL / BE",
         "Лучший сетап", "Самый слабый сетап", "Открыть месяц в журнале", "Твой %s в журнале"),
  "en": ("Your %s: %s", "Your month in the StatsAI journal.", "Result", "Trades", "Win rate", "TP / SL / BE",
         "Best setup", "Weakest setup", "Open the month in the journal", "Your %s in the journal"),
}


def pct(v):
    return ("+" if v > 0.0001 else "") + ("%.2f" % v).rstrip("0").rstrip(".") + "%"


def month_letter(trades, lang, year, month):
    """(тема, текст) итога месяца или None, если сделок не было."""
    real = [t for t in trades if not assistant.is_skip(t)]
    if not real:
        return None
    st = assistant.stats(real)
    L = MONTH_L[lang]
    name = MONTHS[lang][month - 1]
    be = sum(1 for t in real if t.get("result") in ("BE", "BE-", "BE+"))
    lines = ["%s: %s" % (L[2], pct(st["net"])), "%s: %d" % (L[3], st["n"])]
    if st["wr"] is not None:
        lines.append("%s: %d%%" % (L[4], round(st["wr"])))
    lines.append("%s: %d / %d / %d" % (L[5], st["wins"], st["losses"], be))
    body = L[1] + "\n\n" + "\n".join(lines)
    try:
        setups = {k: v for k, v in assistant.by_field(real, "setup").items() if k and v["n"] >= 2}
    except Exception:
        setups = {}
    if len(setups) >= 2:
        best = max(setups.items(), key=lambda kv: kv[1]["net"])
        worst = min(setups.items(), key=lambda kv: kv[1]["net"])
        body += "\n\n%s: %s (%s)\n%s: %s (%s)" % (L[6], best[0], pct(best[1]["net"]),
                                                  L[7], worst[0], pct(worst[1]["net"]))
    body += "\n\n[%s](%s/#journal)" % (L[8], SITE)
    # минус в теме — не лучший повод открыть письмо: тогда тема без цифры
    head = L[0] % (name, pct(st["net"])) if st["net"] > 0.0001 else L[9] % name
    return (head, body)


# ------------------------------------------------------------ проверки ----

def _people(extra=""):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email_confirmed_at IS NOT NULL AND mail_news "
            "AND email IS NOT NULL AND email <> '' " + extra).fetchall()


def _queue(u, subject, body, kind):
    with db.connect() as conn:
        conn.execute("INSERT INTO mail_queue (user_id, email, subject, body, campaign) VALUES (%s,%s,%s,%s,%s)",
                     (u["id"], u["email"], subject, body, "auto:" + kind))
        conn.commit()


def check(now=None):
    """Разложить по очереди всё, что пора отправить. Возвращает {вид: сколько}."""
    init()
    now = now or datetime.datetime.now(KYIV)
    done = {"start": 0, "month": 0, "lapse": 0, "ending": 0}
    utc = datetime.timezone.utc

    # start — 2–7 дней после регистрации, журнал пустой, ещё не писали
    for u in _people("AND mail_start_at IS NULL AND created_at < now() - interval '2 days' "
                     "AND created_at > now() - interval '7 days'"):
        if db.list_trades(u["id"], "all"):
            continue
        s, b = TEXT["start"][lang_of(u)]
        _queue(u, s, b, "start")
        with db.connect() as conn:
            conn.execute("UPDATE users SET mail_start_at=now() WHERE id=%s", (u["id"],)); conn.commit()
        done["start"] += 1

    # lapse — последняя сделка 7–30 дней назад, было хотя бы 5 сделок, за этот перерыв не писали
    for u in _people():
        trades = [t for t in db.list_trades(u["id"]) if t.get("date")]
        if len(trades) < 5:
            continue
        # дата самой свежей сделки (время сделки, по Киеву)
        try:
            last_dt = datetime.datetime.fromisoformat(max(t["date"] for t in trades)[:16]).replace(tzinfo=KYIV)
        except ValueError:
            continue
        gap = (datetime.datetime.now(utc) - last_dt).days
        if gap < 7 or gap > 30:
            continue
        if u.get("mail_lapse_at") and u["mail_lapse_at"] > last_dt:
            continue                                   # за этот перерыв уже писали
        s, b = TEXT["lapse"][lang_of(u)]
        _queue(u, s, b, "lapse")
        with db.connect() as conn:
            conn.execute("UPDATE users SET mail_lapse_at=now() WHERE id=%s", (u["id"],)); conn.commit()
        done["lapse"] += 1

    # ending — без автопродления (отменили в Creem или выдано руками/криптой), осталось ≤ 3 дней
    for u in _people("AND plan NOT IN ('free','life') AND paid_until IS NOT NULL "
                     "AND paid_until > now() AND paid_until < now() + interval '3 days'"):
        if u.get("creem_customer") and not u.get("sub_canceled"):
            continue                                   # продлится само — пугать незачем
        key = u["paid_until"].strftime("%Y-%m-%d")
        if u.get("mail_ending_for") == key:
            continue
        lg = lang_of(u)
        day = u["paid_until"].astimezone(KYIV).strftime("%d.%m")
        s, b = TEXT["ending"][lg]
        _queue(u, s % day, b % day, "ending")
        with db.connect() as conn:
            conn.execute("UPDATE users SET mail_ending_for=%s WHERE id=%s", (key, u["id"])); conn.commit()
        done["ending"] += 1

    # month — 1-го числа (по Киеву), один раз на месяц для всех
    if now.day == 1:
        prev = (now.replace(day=1) - datetime.timedelta(days=1))
        key = "mail_month_%04d-%02d" % (prev.year, prev.month)
        if not db.meta_get(key):
            db.meta_set(key, now.isoformat())
            ym = "%04d-%02d" % (prev.year, prev.month)
            for u in _people():
                tr = [t for t in db.list_trades(u["id"]) if (t.get("date") or "")[:7] == ym]
                got = month_letter(tr, lang_of(u), prev.year, prev.month)
                if got:
                    _queue(u, got[0], got[1], "month")
                    done["month"] += 1
    return done


def due_hours(now=None):
    """Пишем днём: 9:00–20:59 по Киеву."""
    now = now or datetime.datetime.now(KYIV)
    return 9 <= now.hour < 21
