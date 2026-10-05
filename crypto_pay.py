# -*- coding: utf-8 -*-
"""Оплата підписки переказом USDT: рахунки й зіставляння з блокчейном.

Друга каса поруч із карткою. Різниця в тому, що між нами й людиною немає
посередника: вона переказує USDT прямо на наш гаманець, а ми дивимось у
відкритий блокчейн і бачимо, що гроші прийшли.

Головна складність — зрозуміти, **чий** це переказ. Адреса в нас одна на
всіх, і в переказі не написано ні імені, ні номера рахунку. Тому кожному
рахунку дається трохи своя сума: не 11,99, а 11,9943, і останні цифри
працюють номером. Побачили 11,9943 — знаємо, кому вмикати підписку.

Через це людина не мусить нічого натискати після оплати й може закрити
вкладку одразу: підписку вмикає фоновий обхід, а не сторінка.

Що робити, коли сума не збіглася (людина округлила, біржа зрізала
комісію): переказ не губимо — він лягає в crypto_orphans. Окремої
сторінки для таких переказів поки немає: дивимось запитом до бази й
прив'язуємо руками. Плюс у людини є запасний шлях «я оплатив, ось
номер переказу» — там ми шукаємо не за сумою.
"""
import datetime
import random
import threading
import time

import billing
import db
import tron
from config import CRYPTO_TTL_MIN, EUR_USDT, PLAN_DAYS, TRON_WALLET

# Крок між сусідніми «хвостиками» суми і скільки їх усього. Сто
# варіантів на тариф, найбільша надбавка — дев'ять копійок; одночасно
# відкритих рахунків у нас на порядки менше, тож вільний знайдеться
# завжди.
#
# Крок обов'язково більший за подвоєний допуск нижче. Інакше вікна двох
# рахунків накладаються, і переказ однієї людини закриває рахунок іншої:
# саме так і було, поки крок вимірювався частками монети, а допуск —
# цілою копійкою.
STEP = 1_000                  # 0,001 USDT між сусідніми сумами
TAIL = 100                    # 0 … 0,099 USDT надбавки
# Наскільки дозволяємо переказу не дотягнути до суми рахунку. Тільки
# зовсім дрібниця: сума — це номер рахунку, і допуск не має з'їдати крок
# між двома різними номерами. Хто округлив — має запасний шлях «я
# оплатив, ось номер переказу», там шукаємо не за сумою.
SLACK_UNITS = 400             # 0,0004 USDT
# Скільки зайвого приймаємо в запасному шляху «я оплатив, ось номер».
# Округлення вгору буває: 79,071 → 80. А от перевищення на кілька монет
# — це вже не округлення, а чужий переказ, підібраний у блокчейні.
CLAIM_OVER = 2_000_000        # 2 USDT
# Наскільки переказ може виявитись «старшим» за рахунок. Годинники в
# мережі й у нас розходяться на секунди; п'ять хвилин — із запасом.
CLAIM_SKEW_MS = 5 * 60 * 1000


def enabled():
    return tron.enabled()


def price_units(uid, plan):
    """Скільки USDT коштує тариф саме цій людині.

    Ціни в нас у євро, а переказ іде в USDT, тож перераховуємо за курсом
    із налаштувань. Курс не питаємо в ринку щохвилини навмисно: сума має
    бути тією самою й тоді, коли людина відкрила сторінку, і тоді, коли
    вона за п'ять хвилин натиснула «переказати».

    Ціну беремо ту саму, що стоїть на картці тарифу, — разом із усіма
    знижками: «ранньою», партнерською і введеним промокодом. Інакше
    людина бачила б на екрані одну суму, а в рахунку — іншу, більшу, і
    мала б рацію, вирішивши, що знижку їй не дали.
    """
    cents = (billing.prices(uid).get(plan) or {}).get("cents")
    if not cents:
        return 0
    return tron.to_units(cents / 100.0 * EUR_USDT)


def _free_units(base):
    """Підібрати суму, якої зараз ніхто інший не чекає.

    Хвостик беремо випадковий, а не по черзі: підряд ідучі суми видали б
    сторонньому, скільки в нас оплат за день.

    Зайнятою вважається не тільки сама сума, а й усе поруч із нею на
    відстані допуску: дві суми, чиї вікна дотикаються, — це вже не два
    різні номери рахунку.
    """
    span = (TAIL - 1) * STEP
    with db.connect() as conn:
        taken = {r["units"] for r in conn.execute(
            "SELECT units FROM crypto_invoices WHERE status='new' "
            "AND units BETWEEN %s AND %s",
            (base - STEP, base + span + STEP)).fetchall()}
    gap = 2 * SLACK_UNITS
    free = [base + i * STEP for i in range(TAIL)
            if all(abs(base + i * STEP - t) > gap for t in taken)]
    return random.choice(free) if free else 0


def create(uid, plan):
    """Виставити рахунок. Повертає його або None, якщо нема чого виставляти."""
    if not enabled() or plan not in billing.PLANS:
        return None
    base = price_units(uid, plan)
    if not base:
        return None
    # Старі рахунки цієї людини гасимо: два відкритих одночасно — це два
    # різні числа на екрані й гарантована плутанина.
    expire_old(uid)
    units = _free_units(base)
    if not units:
        return None
    until = db.now() + datetime.timedelta(minutes=CRYPTO_TTL_MIN)
    with db.connect() as conn:
        row = conn.execute(
            "INSERT INTO crypto_invoices (user_id, plan, units, expires_at) "
            "VALUES (%s,%s,%s,%s) RETURNING *", (uid, plan, units, until)).fetchone()
        conn.commit()
    return row


def public(inv):
    """Рахунок у тому вигляді, в якому його бачить сторінка.

    Суму віддаємо і числом, і рядком: рядок людина копіює кнопкою, і саме
    в ньому важливі останні цифри — це номер її рахунку. Округлити його
    не можна, інакше переказ не впізнається.
    """
    if not inv:
        return None
    left = (inv["expires_at"] - db.now()).total_seconds()
    return {
        "id": inv["id"],
        "plan": inv["plan"],
        "wallet": TRON_WALLET,
        "network": "TRON (TRC-20)",
        "coin": "USDT",
        "amount": tron.to_usdt(inv["units"]),
        # рівно стільки знаків, скільки має монета, без хвоста з нулів
        "amount_text": ("%.6f" % tron.to_usdt(inv["units"])).rstrip("0").rstrip("."),
        "status": inv["status"],
        "seconds_left": max(0, int(left)),
    }


def expire_old(uid=None):
    """Згасити рахунки, яких уже не чекаємо.

    Без цього сума лишалась би зайнятою назавжди, а людина, заплативши
    через добу, чекала б підписки, якої ніхто не ввімкне.
    """
    with db.connect() as conn:
        if uid:
            conn.execute("UPDATE crypto_invoices SET status='expired' "
                         "WHERE user_id=%s AND status='new'", (uid,))
        else:
            conn.execute("UPDATE crypto_invoices SET status='expired' "
                         "WHERE status='new' AND expires_at < now()")
        conn.commit()


def cancel(uid):
    """Людина передумала: гасимо її відкритий рахунок.

    Рядок не видаляємо. «Скасувати» тут означає «більше не чекаємо», а
    не «грошей не було»: переказ міг піти за секунду до натискання, і
    він так само має ввімкнути підписку — його впіймає _match серед
    згаслих. Видалений рахунок не впіймав би нічого.
    """
    with db.connect() as conn:
        got = conn.execute("UPDATE crypto_invoices SET status='expired' "
                           "WHERE user_id=%s AND status='new' RETURNING id",
                           (uid,)).fetchall()
        conn.commit()
    return bool(got)


def current(uid):
    """Рахунок, який людина зараз оплачує, або None."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM crypto_invoices WHERE user_id=%s AND status='new' "
            "AND expires_at > now() ORDER BY id DESC LIMIT 1", (uid,)).fetchone()


def last_paid(uid):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM crypto_invoices WHERE user_id=%s AND status='paid' "
            "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()


def _match(units):
    """Який рахунок чекає саме на цю суму.

    Береться й трохи більша сума: людина могла накинути зайвого, і
    відмовляти їй за це безглуздо. Менша — тільки в межах дрібниці.

    Дивимось і на згаслі рахунки за останню добу. Гроші в блокчейні
    не питають, чи ми ще чекаємо: людина могла переказувати довше за
    годину або натиснути «скасувати», коли переказ уже пішов. Такий
    переказ має вмикати підписку сам, без листування з підтримкою.

    Але згаслий беремо тільки тоді, коли він на цю суму один. Серед
    згаслих однакові суми вже можливі — місце за ними не тримається, —
    і вмикати підписку навмання, коли претендентів двоє, не можна: це
    чужі гроші й чужа підписка. Такий переказ іде в «нічийні», і його
    розбирають руками.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_invoices "
            "WHERE (status='new' OR (status='expired' "
            "       AND created_at > now() - interval '1 day')) "
            "AND units BETWEEN %s AND %s ORDER BY id",
            (units - SLACK_UNITS, units + SLACK_UNITS)).fetchall()
    live = [r for r in rows if r["status"] == "new"]
    if live:
        return live[0]
    return rows[0] if len(rows) == 1 else None


def _settle(inv, tx, payer, when_ms=0):
    """Закрити рахунок і відкрити підписку.

    Позначку ставимо умовно — «поки рахунок ще не оплачений»: той самий
    переказ може приїхати двічі (фоновий обхід і кнопка «я оплатив»
    одночасно), і підписка не має продовжитись на два строки за одні
    гроші. Згаслий рахунок теж закриваємо: людина могла переказувати
    довше, ніж ми чекали, і карати її за це ні до чого.
    """
    with db.connect() as conn:
        got = conn.execute(
            "UPDATE crypto_invoices SET status='paid', tx=%s, payer=%s, "
            "paid_at=now() WHERE id=%s AND status IN ('new','expired') "
            "RETURNING id", (tx, payer or "", inv["id"])).fetchone()
        conn.commit()
    if not got:
        return False
    billing.grant(inv["user_id"], PLAN_DAYS.get(inv["plan"], 30), inv["plan"])
    billing.promo_paid(inv["user_id"])
    print("крипта: оплачено %s для %s, переказ %s"
          % (inv["plan"], inv["user_id"], tx[:16]), flush=True)
    return True


def _orphan(row):
    """Запам'ятати переказ, який не збігся з жодним рахунком."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO crypto_orphans (tx, units, payer, at_ms) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (tx) DO NOTHING",
            (row["tx"], row["units"], row.get("from") or "", row.get("at") or 0))
        conn.commit()


def _credited(tx):
    """Чи закрили цим переказом якийсь рахунок.

    Не те саме, що «бачили». Переказ може лежати серед нічийних — тоді
    гроші прийшли, а підписки ніхто не отримав, і зарахувати його за
    номером ще можна й потрібно.
    """
    with db.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM crypto_invoices WHERE tx=%s",
                                 (tx,)).fetchone())


def _drop_orphan(tx):
    """Переказ знайшов свій рахунок — серед нічийних йому більше не місце."""
    with db.connect() as conn:
        conn.execute("DELETE FROM crypto_orphans WHERE tx=%s", (tx,))
        conn.commit()


def _ms(when):
    try:
        return int(when.timestamp() * 1000)
    except Exception:
        return 0


def _seen(tx):
    with db.connect() as conn:
        a = conn.execute("SELECT 1 FROM crypto_invoices WHERE tx=%s", (tx,)).fetchone()
        b = conn.execute("SELECT 1 FROM crypto_orphans WHERE tx=%s", (tx,)).fetchone()
    return bool(a or b)


def check_new():
    """Один обхід: забрати свіжі перекази й закрити ними рахунки.

    Повертає, скільки підписок увімкнули. None — блокчейн не відповів;
    це не «оплат немає», а «сьогодні не спитали», і поводитись із цим
    треба інакше: переказ нікуди не подінеться, спитаємо ще раз.
    """
    expire_old()
    since = _since_ms()
    rows = tron.incoming(since)
    if rows is None:
        return None
    done = 0
    for r in rows:
        if not r["tx"] or _seen(r["tx"]):
            continue
        inv = _match(r["units"])
        if inv and _settle(inv, r["tx"], r.get("from"), r.get("at")):
            done += 1
        else:
            _orphan(r)
    _remember_ms(rows)
    return done


def _since_ms():
    """З якої миті питати перекази.

    Тримаємо в meta час останнього побаченого: перезапуск сервера не має
    означати ні повторного перебору всієї історії, ні прогалини, в якій
    загубилась би чиясь оплата. Перший запуск бере останню сторінку.
    """
    raw = db.meta_get("crypto_seen_ms", "")
    try:
        return int(raw) if raw else 0
    except (TypeError, ValueError):
        return 0


def _remember_ms(rows):
    if not rows:
        return
    newest = max(r["at"] for r in rows)
    if newest > _since_ms():
        # плюс мілісекунда, щоб той самий переказ не приїхав ще раз
        db.meta_set("crypto_seen_ms", str(newest + 1))


def claim(uid, txid):
    """«Я оплатив, ось номер переказу» — запасний шлях.

    Потрібен тому, хто округлив суму: за сумою такий переказ не знайти,
    а за номером — можна. Перевіряємо в блокчейні, що переказ справді
    наш, справді USDT і справді на нашу адресу; на слово не віримо.

    І перевіряємо, що він саме цієї людини. Номер переказу — річ
    прилюдна: у блокчейні видно всі перекази на наш гаманець, і назвати
    чужий своїм може будь-хто. Тому три правила:

    * переказ, який збігається за сумою з чиїмось рахунком, належить
      власникові того рахунку — його й закриваємо, хто б не назвав
      номер;
    * переказ, зроблений раніше, ніж виставлено рахунок, не приймаємо:
      свій рахунок людина відкриває до того, як платить, а не після
      того, як побачила в мережі чужі гроші;
    * переплату приймаємо в межах округлення, а не будь-яку — інакше
      рахунок на місяць закривався б чужим переказом за рік.

    Повертає (ок, причина).
    """
    if not enabled():
        return False, "off"
    got = tron.by_hash(txid)
    if not got:
        return False, "not_found"
    if _credited(got["tx"]):
        return False, "used"

    # Сума — це номер рахунку. Якщо вона з чимось збігається, питання
    # «чий переказ» вирішене, і назвати його своїм не вийде.
    owner = _match(got["units"])
    if owner:
        ok = _settle(owner, got["tx"], got.get("from"), got.get("at"))
        if ok:
            _drop_orphan(got["tx"])
        if owner["user_id"] != uid:
            return False, "used"
        return (True, "") if ok else (False, "used")

    inv = current(uid) or _last_new(uid)
    if not inv:
        return False, "no_invoice"
    when = got.get("at") or 0
    if when and when + CLAIM_SKEW_MS < _ms(inv["created_at"]):
        return False, "too_old"
    if got["units"] + SLACK_UNITS < inv["units"]:
        # Заплатили менше, ніж коштує тариф: підписку не вмикаємо, але й
        # гроші не ховаємо — переказ лягає в crypto_orphans.
        _orphan(got)
        return False, "too_small"
    if got["units"] > inv["units"] + CLAIM_OVER:
        _orphan(got)
        return False, "too_big"
    ok = _settle(inv, got["tx"], got.get("from"), got.get("at"))
    if ok:
        _drop_orphan(got["tx"])
    return (True, "") if ok else (False, "used")


# --------------------------------------------------------- фоновий обхід ----
# Поки ніхто нічого не оплачує, питати блокчейн ні до чого — тому обхід
# спить довго, а прокидається частіше рівно тоді, коли є що чекати. На
# безкоштовному ключі це тримає нас далеко від будь-яких лімітів.
IDLE = 300         # нема відкритих рахунків — раз на п'ять хвилин
BUSY = 30          # хтось платить просто зараз — раз на півхвилини


def _waiting():
    with db.connect() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM crypto_invoices WHERE status='new' "
            "AND expires_at > now() LIMIT 1").fetchone())


def loop():
    while True:
        try:
            busy = _waiting()
            if busy:
                check_new()
            else:
                expire_old()
        except Exception as ex:
            print("крипта: обхід зірвався:", ex, flush=True)
            busy = False
        time.sleep(BUSY if busy else IDLE)


def start():
    """Завести обхід, якщо оплата криптою взагалі ввімкнена."""
    if not enabled():
        print("крипта: гаманець не заданий, оплату не вмикаємо", flush=True)
        return
    if not tron.valid(TRON_WALLET):
        # Одна переплутана літера в адресі — і гроші йдуть у нікуди.
        # Краще не вмикати касу зовсім, ніж зібрати оплати в порожнечу.
        print("крипта: адреса гаманця не сходиться, оплату не вмикаємо", flush=True)
        return
    threading.Thread(target=loop, daemon=True, name="crypto").start()
    print("крипта: приймаємо USDT на %s" % TRON_WALLET, flush=True)


def _last_new(uid):
    """Останній неоплачений рахунок людини, зокрема й щойно згаслий.

    Доба — навмисно щедро: людина могла переказувати довго, а номер
    переказу принести ще пізніше. Старіше вже не беремо, інакше свіжа
    оплата закрила б рахунок місячної давнини.
    """
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM crypto_invoices WHERE user_id=%s "
            "AND status IN ('new','expired') "
            "AND created_at > now() - interval '1 day' "
            "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
