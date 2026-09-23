# -*- coding: utf-8 -*-
"""
Платна підписка: хто ще пише безкоштовно, а кому вже час платити.

Усе, що стосується грошей, зібрано тут одним модулем, щоб місця перевірок
(сайт, бот, перенесення з Notion) не знали правил, а тільки питали дозволу:

    ok, why = billing.can_add_trade(uid, kind)
    if not ok:
        <віддати 402 з billing.deny(uid, why)>
    ...
    billing.spend_trade(uid, kind)

Правила (затверджені власником 22.09.2026):

* безкоштовно 30 справжніх угод і **окремо** 30 прогонів бектесту;
* ліміти несиметричні — скінчились прогони, закривається лише бектест;
  скінчились справжні угоди, закрито все, зокрема й бектест;
* перенесення з Notion — 3 рази в перші 30 днів після реєстрації;
* звернень до моделі — 15 на місяць без підписки (рішення власника
  23.09.2026); розділи журналу при цьому відкриті всі, і «Аналітика»
  теж — платимо ми тільки за відповіді моделі;
* нічого не видаляється: читання, статистика й вивантаження працюють
  завжди, закриваються тільки нові записи, перенесення й зайві звернення
  до моделі.

Лічильники монотонні: spend_* їх тільки збільшує. Рахувати COUNT(*) по
угодах не можна — db.delete_trade прибирає рядок фізично, і людина ходила
б по колу «записав 30 → прибрав → записав ще 30».

Поки діє підписка, безкоштовні лічильники не чіпаємо: підписка відкриває
все, а якщо вона скінчиться, людина повернеться рівно туди, де зупинилась.
"""
import datetime

import db
from config import (AI_WINDOW_DAYS, CURRENCY, FREE_AI, FREE_BT, FREE_IMPORTS,
                    FREE_TRADES, IMPORT_WINDOW_DAYS, PAID_AI, PLAN_DAYS, PRICES)

# Платні тарифи. 'free' — не тариф, а його відсутність.
PLANS = ("month", "quarter", "year")

# Причини відмови. Одні й ті самі рядки бачать сайт і бот, текст кожен
# підставляє свій — звідси йде тільки привід.
TRADES_LIMIT = "trades_limit"
BT_LIMIT = "bt_limit"
IMPORTS_LIMIT = "imports_limit"
IMPORT_WINDOW = "import_window"
# Безкоштовні звернення до моделі на місяць скінчились — тут пропонуємо
# підписку. AI_CAP — інше: у стелю впирається вже той, хто платить, і
# підписку йому пропонувати нема чого, йому кажемо зачекати.
AI_LIMIT = "ai_limit"
AI_CAP = "ai_cap"
NO_USER = "no_user"


def _user(u):
    """Приймає і id, і вже прочитаний рядок: у місцях перевірки користувач
    часто вже під рукою, і другий рейс у базу там зайвий."""
    if isinstance(u, dict):
        return u
    return db.get_user(u)


def _int(row, key, default=0):
    v = row.get(key)
    return default if v is None else int(v)


def _cap(row, key, default):
    """Свій ліміт людини; порожнє — загальний з config."""
    v = row.get(key)
    return default if v is None else int(v)


# -------------------------------------------------------------- підписка ----

def active(u):
    """Чи відкрито людині все прямо зараз."""
    row = _user(u)
    if not row:
        return False
    until = row.get("paid_until")
    return bool(until and until > db.now())


def plan_of(u):
    """Тариф, який діє. Прострочений тариф — це 'free': рядок у базі
    лишається (видно, чим платили), але прав він уже не дає."""
    row = _user(u)
    if not row:
        return "free"
    p = (row.get("plan") or "free").strip()
    if not active(row) or p not in PLANS:
        return "free"
    return p


def import_days_left(u):
    """Скільки днів ще триває вікно перенесення з Notion (0 — минуло)."""
    row = _user(u)
    if not row:
        return 0
    born = row.get("created_at")
    if not born:
        return IMPORT_WINDOW_DAYS
    gone = (db.now() - born).days
    return max(0, IMPORT_WINDOW_DAYS - gone)


def state(u):
    """Повна картина по людині — для бота, адмінки й точки /api/billing/state.

    Залишки тут є, але людині їх не показуємо: лічильника «лишилось N із 30»
    в журналі немає ніде (рішення власника 22.09.2026), про вичерпання вона
    дізнається з відмови.
    """
    row = _user(u)
    if not row:
        return {"plan": "free", "active": False, "paid_until": None,
                "trades_left": 0, "bt_left": 0, "imports_left": 0,
                "import_days_left": 0, "ai_left": 0, "ai_cap": 0,
                "ai_reset_at": None, "price_plan": "std"}
    until = row.get("paid_until")
    reset = row.get("ai_reset_at")
    return {
        "plan": plan_of(row),
        "active": active(row),
        "paid_until": until.isoformat() if until else None,
        "trades_left": max(0, _cap(row, "free_trades_cap", FREE_TRADES)
                           - _int(row, "free_trades_used")),
        "bt_left": max(0, _cap(row, "free_bt_cap", FREE_BT)
                       - _int(row, "free_bt_used")),
        "imports_left": max(0, _cap(row, "imports_cap", FREE_IMPORTS)
                            - _int(row, "imports_used")),
        "import_days_left": import_days_left(row),
        # Звернення до моделі — єдине, що людині показати не гріх: вона має
        # розуміти, чому помічник раптом відмовив. Скільки лишилось угод,
        # як і раніше, не показуємо ніде.
        "ai_left": max(0, ai_cap(row) - ai_used(row)),
        "ai_cap": ai_cap(row),
        "ai_reset_at": reset.isoformat() if reset and reset > db.now() else None,
        "price_plan": (row.get("price_plan") or "std"),
    }


def free_terms(u):
    """Що дається без підписки — числами.

    Це умови, а не лічильник: тут «дається 30», а не «лишилось 12». Різниця
    принципова — залишок ми не показуємо ніде, а умови людина має бачити
    перед тим, як платити.
    """
    row = _user(u)
    if not row:
        return {}
    return {
        "trades": _cap(row, "free_trades_cap", FREE_TRADES),
        "bt": _cap(row, "free_bt_cap", FREE_BT),
        "imports": _cap(row, "imports_cap", FREE_IMPORTS),
        "import_days": IMPORT_WINDOW_DAYS,
        # У того, хто платить, у ai_cap стоїть стеля підписки — в умовах
        # безкоштовного вона ні до чого, там завжди місячна порція.
        "ai": FREE_AI if active(row) else _cap(row, "ai_cap", FREE_AI),
    }


def public(u):
    """Те саме, але для браузера й бота.

    Лічильника «лишилось N із 30» немає ніде (рішення власника
    22.09.2026), тому залишки угод, прогонів і перенесень назовні не
    віддаємо зовсім — про вичерпання людина дізнається з відмови. Звернення
    до моделі — виняток: відмова помічника інакше виглядала б поломкою.
    """
    out = state(u)
    for k in ("trades_left", "bt_left", "imports_left", "import_days_left"):
        out.pop(k, None)
    out["prices"] = prices(u)
    out["free"] = free_terms(u)
    return out


def prices(u=None):
    """Ціни, які бачить саме ця людина: звичайні або «ранні».

    std_cents — ціна без знижки; на картці вона йде перекресленою, щоб
    видно було, від чого рахується вигода.
    """
    row = _user(u) if u is not None else None
    name = "early" if (row and row.get("price_plan") == "early") else "std"
    out = {"currency": CURRENCY, "set": name,
           "own_cents": (row or {}).get("own_price_cents")}
    for p in PLANS:
        out[p] = {"cents": PRICES[name][p], "std_cents": PRICES["std"][p],
                  "days": PLAN_DAYS[p]}
    return out


# --------------------------------------------------------------- дозволи ----

def can_add_trade(u, kind=""):
    """(можна, причина). Порожня причина — можна.

    Спершу загальна застава по справжніх угодах: скінчились вони — закрито
    геть усе, зокрема й бектест. І тільки потім окрема застава на прогони.
    """
    row = _user(u)
    if not row:
        return False, NO_USER
    if active(row):
        return True, ""
    if _int(row, "free_trades_used") >= _cap(row, "free_trades_cap", FREE_TRADES):
        return False, TRADES_LIMIT
    if kind == "bt" and _int(row, "free_bt_used") >= _cap(row, "free_bt_cap", FREE_BT):
        return False, BT_LIMIT
    return True, ""


def can_import(u):
    """Перенесення з Notion: три рази і тільки в перші 30 днів."""
    row = _user(u)
    if not row:
        return False, NO_USER
    if active(row):
        return True, ""
    if import_days_left(row) <= 0:
        return False, IMPORT_WINDOW
    if _int(row, "imports_used") >= _cap(row, "imports_cap", FREE_IMPORTS):
        return False, IMPORTS_LIMIT
    return True, ""


def can_autosync(u):
    """Нічне оновлення з Notion.

    Лічильник перенесень воно не чіпає: це та сама база, яку людина вже
    підключила руками, і рахувати щодобовий захід як одне з трьох
    перенесень було б обманом. Правило простіше: або підписка, або ще не
    минули перші 30 днів.
    """
    row = _user(u)
    if not row:
        return False, NO_USER
    if active(row):
        return True, ""
    if import_days_left(row) <= 0:
        return False, IMPORT_WINDOW
    return True, ""


def ai_cap(u):
    """Скільки звернень до моделі належить людині за вікно.

    Підписка не робить їх безмежними: стеля просто піднімається до PAID_AI.
    Якщо адмін дав більше руками (ai_cap), беремо його число.
    """
    row = _user(u)
    if not row:
        return 0
    own = _cap(row, "ai_cap", FREE_AI)
    return max(own, PAID_AI) if active(row) else own


def ai_used(u):
    """Скільки витрачено в поточному вікні. Вікно минуло — нуль: лічильник
    обнуляє перше ж звернення (див. spend_ai), окремого прибирання немає."""
    row = _user(u)
    if not row:
        return 0
    until = row.get("ai_reset_at")
    if not until or until <= db.now():
        return 0
    return _int(row, "ai_used")


def can_use_ai(u):
    """Помічник, розбір дня, звірка «Моєї ТС», розмова з ботом.

    Розділи журналу ми не закриваємо — платне саме це: кожна відповідь
    моделі коштує нам грошей. Без підписки на місяць дається FREE_AI
    звернень, з підпискою — стеля PAID_AI, щоб один акаунт не гнав запити
    скриптом.
    """
    row = _user(u)
    if not row:
        return False, NO_USER
    if ai_used(row) < ai_cap(row):
        return True, ""
    return False, (AI_CAP if active(row) else AI_LIMIT)


def deny(u, reason):
    """Тіло відмови. Один формат на сайт і бота, щоб плашка скрізь була та
    сама: код кажемо ми, текст підставляє той, хто показує."""
    return {"error": reason, "code": "need_sub", "reason": reason,
            "state": state(u)}


# --------------------------------------------------------------- витрати ----

def _bump(uid, column, n=1):
    with db.connect() as conn:
        conn.execute("UPDATE users SET {0}={0}+%s WHERE id=%s".format(column),
                     (n, uid))
        conn.commit()


def spend_trade(u, kind=""):
    """Записали угоду — забираємо одиницю з безкоштовного запасу.

    У того, в кого підписка, не рахуємо нічого: інакше людина, яка платила
    півроку, після закінчення підписки опинилась би одразу за лімітом.
    """
    row = _user(u)
    if not row or active(row):
        return
    _bump(row["id"], "free_bt_used" if kind == "bt" else "free_trades_used")


def spend_import(u):
    row = _user(u)
    if not row or active(row):
        return
    _bump(row["id"], "imports_used")


def spend_ai(u):
    """Звернення до моделі. Рахуємо і в тих, хто платить: стеля в них своя,
    але вона теж стеля.

    Вікно рухаємо тим самим запитом, що й лічильник: перше звернення після
    ai_reset_at ставить одиницю й відсуває дату на місяць уперед. Двома
    запитами тут не можна — два питання одночасно з двох вкладок розійшлися
    б по різних вікнах.
    """
    row = _user(u)
    if not row:
        return
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET "
            " ai_used = CASE WHEN ai_reset_at IS NULL OR ai_reset_at <= now()"
            "                THEN 1 ELSE ai_used + 1 END,"
            " ai_reset_at = CASE WHEN ai_reset_at IS NULL OR ai_reset_at <= now()"
            "                    THEN now() + %s * interval '1 day' ELSE ai_reset_at END"
            " WHERE id=%s", (AI_WINDOW_DAYS, row["id"]))
        conn.commit()


# ------------------------------------------------------- підписка руками ----

def grant(uid, days, plan=""):
    """Дати підписку з адмінки (нею ж продовжуємо після оплати).

    Дні додаються до того, що вже оплачено, а не затирають його: доплата
    посеред місяця не має з'їдати залишок.
    """
    row = db.get_user(uid)
    if not row:
        return None
    base = row.get("paid_until")
    now = db.now()
    if not base or base < now:
        base = now
    until = base + datetime.timedelta(days=int(days))
    if plan not in PLANS:
        plan = _plan_by_days(days)
    with db.connect() as conn:
        conn.execute("UPDATE users SET plan=%s, paid_until=%s WHERE id=%s",
                     (plan, until, uid))
        conn.commit()
    return state(uid)


def _plan_by_days(days):
    """Яким тарифом підписати, коли дні дали руками. Беремо найближчий
    знизу: 45 днів — це все ще місячний."""
    days = int(days)
    best = "month"
    for p in PLANS:
        if days >= PLAN_DAYS[p] and PLAN_DAYS[p] >= PLAN_DAYS[best]:
            best = p
    return best


def revoke(uid):
    """Зняти підписку. Оплачені дні при цьому зникають — це кнопка для
    повернення грошей, а не для «людина відмовилась продовжувати»: відмова
    від продовження просто не рухає paid_until."""
    with db.connect() as conn:
        conn.execute("UPDATE users SET plan='free', paid_until=NULL WHERE id=%s",
                     (uid,))
        conn.commit()
    return state(uid)


def bonus(uid, trades=0, bt=0, imports=0, ai=0, note=None):
    """Підняти безкоштовний ліміт саме цій людині (в адмінці).

    Піднімаємо межу, а не зменшуємо витрачене: так видно і скільки людина
    записала, і скільки їй додали.
    """
    sets, vals = [], []
    for col, n in (("free_trades_cap", trades), ("free_bt_cap", bt),
                   ("imports_cap", imports), ("ai_cap", ai)):
        if n:
            sets.append("{0}={0}+%s".format(col))
            vals.append(int(n))
    if note is not None:
        sets.append("billing_note=%s")
        vals.append(note)
    if not sets:
        return state(uid)
    with db.connect() as conn:
        conn.execute("UPDATE users SET %s WHERE id=%%s" % ", ".join(sets),
                     vals + [uid])
        conn.commit()
    return state(uid)


def set_price(uid, price_plan=None, own_cents=None, note=None):
    """Набір цін ('std' / 'early') і разова своя ціна. Ціна в центах,
    None лишає поле як було, 0 — прибирає її."""
    sets, vals = [], []
    if price_plan in ("std", "early"):
        sets.append("price_plan=%s")
        vals.append(price_plan)
    if own_cents is not None:
        sets.append("own_price_cents=%s")
        vals.append(int(own_cents) or None)
    if note is not None:
        sets.append("billing_note=%s")
        vals.append(note)
    if not sets:
        return state(uid)
    with db.connect() as conn:
        conn.execute("UPDATE users SET %s WHERE id=%%s" % ", ".join(sets),
                     vals + [uid])
        conn.commit()
    return state(uid)
