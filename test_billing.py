# -*- coding: utf-8 -*-
"""
Ядро платної підписки: python test_billing.py

Дві частини. Перша — самі правила, без бази: користувача підставляємо
словником, час підміняємо. Друга — жива, вона йде в базу з .env: перевіряє,
що db.init() кладе колонки й таблиці підписки, рахує витрати й підписку
руками. Живу частину видно за написом «жива база»; немає DATABASE_URL —
просто пропускається.

Найголовніше тут — несиметрія лімітів: скінчились прогони бектесту,
справжні угоди пишуться далі; скінчились справжні — закрито все.
"""
import datetime
import sys

import config
import db
import billing

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

_fails = []


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    if not ok:
        _fails.append(name)
    return ok


def person(**kw):
    """Людина, яка щойно зареєструвалась і нічого ще не витратила."""
    row = {"id": 1, "plan": "free", "paid_until": None,
           "free_trades_used": 0, "free_trades_cap": 30,
           "free_bt_used": 0, "free_bt_cap": 30,
           "imports_used": 0, "imports_cap": 3,
           "ai_used": 0, "ai_cap": 15, "ai_reset_at": None,
           "price_plan": "std", "own_price_cents": None,
           "created_at": NOW - datetime.timedelta(days=5)}
    row.update(kw)
    return row


def paid(days=10, plan="year", **kw):
    return person(plan=plan, paid_until=NOW + datetime.timedelta(days=days), **kw)


# --------------------------------------------------------------- правила ----

def check_rules():
    print("\nправила (без бази)")
    free = person()
    case("новому все можна", billing.can_add_trade(free), (True, ""))
    case("новому можна й бектест", billing.can_add_trade(free, "bt"), (True, ""))
    case("новий — без підписки", billing.active(free), False)
    case("тариф новенького", billing.plan_of(free), "free")

    out = billing.state(free)
    case("залишок справжніх", out["trades_left"], 30)
    case("залишок прогонів", out["bt_left"], 30)
    case("залишок перенесень", out["imports_left"], 3)
    case("днів вікна перенесення", out["import_days_left"], 25)
    case("дати оплати немає", out["paid_until"], None)

    # Несиметрія лімітів — головне правило.
    dry = person(free_trades_used=30)
    case("скінчились справжні — відмова", billing.can_add_trade(dry),
         (False, "trades_limit"))
    case("скінчились справжні — бектест теж закрито",
         billing.can_add_trade(dry, "bt"), (False, "trades_limit"))
    case("залишок не йде в мінус", billing.state(dry)["trades_left"], 0)

    bt_dry = person(free_trades_used=10, free_bt_used=30)
    case("скінчились прогони — бектест закрито",
         billing.can_add_trade(bt_dry, "bt"), (False, "bt_limit"))
    case("скінчились прогони — справжні пишуться далі",
         billing.can_add_trade(bt_dry), (True, ""))

    # Підписка відкриває все, зокрема й людині за лімітом.
    rich = paid(free_trades_used=99, free_bt_used=99, imports_used=99)
    case("підписка активна", billing.active(rich), True)
    case("підписці ліміт не заважає", billing.can_add_trade(rich), (True, ""))
    case("підписці бектест теж", billing.can_add_trade(rich, "bt"), (True, ""))
    case("тариф підписки", billing.plan_of(rich), "year")
    case("підписка в стані", billing.state(rich)["active"], True)

    old = paid(days=-1, free_trades_used=30)
    case("прострочена підписка не діє", billing.active(old), False)
    case("прострочений тариф — free", billing.plan_of(old), "free")
    case("після прострочення ліміт знову діє", billing.can_add_trade(old),
         (False, "trades_limit"))

    # Перенесення з Notion: три рази і тільки в перші 30 днів.
    case("перенести можна", billing.can_import(person()), (True, ""))
    case("три перенесення витрачено",
         billing.can_import(person(imports_used=3)), (False, "imports_limit"))
    late = person(created_at=NOW - datetime.timedelta(days=31))
    case("вікно перенесення минуло", billing.can_import(late),
         (False, "import_window"))
    case("вікно минуло — днів нуль", billing.import_days_left(late), 0)
    case("з підпискою переносити можна завжди",
         billing.can_import(paid(created_at=NOW - datetime.timedelta(days=400))),
         (True, ""))

    # Нічне оновлення: воно з тих самих баз, тому лічильник перенесень не
    # чіпає — дивиться тільки на вікно й на підписку.
    case("нічне оновлення в перші 30 днів", billing.can_autosync(person()), (True, ""))
    case("витрачені перенесення оновленню не заважають",
         billing.can_autosync(person(imports_used=3)), (True, ""))
    case("після 30 днів оновлення спиняється", billing.can_autosync(late),
         (False, "import_window"))
    case("з підпискою оновлюємо завжди",
         billing.can_autosync(paid(created_at=NOW - datetime.timedelta(days=400))),
         (True, ""))

    # Звернення до моделі: 15 на місяць без підписки. Розділи журналу при
    # цьому відкриті всі — платимо ми саме за відповіді моделі.
    case("новому ШІ відкрито", billing.can_use_ai(person()), (True, ""))
    case("новому 15 звернень", billing.state(person())["ai_left"], 15)

    live = NOW + datetime.timedelta(days=10)
    spent = person(ai_used=15, ai_reset_at=live)
    case("15 витрачено — відмова", billing.can_use_ai(spent), (False, "ai_limit"))
    case("залишок звернень нуль", billing.state(spent)["ai_left"], 0)
    case("чотирнадцяте ще проходить",
         billing.can_use_ai(person(ai_used=14, ai_reset_at=live)), (True, ""))

    fresh = person(ai_used=15, ai_reset_at=NOW - datetime.timedelta(days=1))
    case("вікно минуло — знову можна", billing.can_use_ai(fresh), (True, ""))
    case("вікно минуло — залишок повний", billing.state(fresh)["ai_left"], 15)
    case("минуле вікно не показуємо", billing.state(fresh)["ai_reset_at"], None)

    # Підписка не робить звернення безмежними — просто піднімає стелю.
    case("підписці 15 замало не буде",
         billing.can_use_ai(paid(ai_used=15, ai_reset_at=live)), (True, ""))
    case("стеля підписки", billing.ai_cap(paid()), 300)
    case("підписка впирається в стелю",
         billing.can_use_ai(paid(ai_used=300, ai_reset_at=live)), (False, "ai_cap"))
    case("свій ліміт від адміна більший за загальний",
         billing.ai_cap(person(ai_cap=40)), 40)

    case("невідомої людини немає", billing.can_add_trade(None), (False, "no_user"))

    no = billing.deny(dry, "trades_limit")
    case("відмова — один код", no["code"], "need_sub")
    case("відмова каже привід", no["reason"], "trades_limit")
    case("відмова несе стан", no["state"]["trades_left"], 0)


def check_prices():
    print("\nціни")
    std = billing.prices(person())
    case("місяць", std["month"]["cents"], 1199)
    case("квартал", std["quarter"]["cents"], 2799)
    case("рік", std["year"]["cents"], 9999)
    case("валюта", std["currency"], "EUR")

    early = billing.prices(person(price_plan="early"))
    case("ранні: місяць", early["month"]["cents"], 799)
    case("ранні: квартал", early["quarter"]["cents"], 2097)
    case("ранні: рік", early["year"]["cents"], 7188)
    case("ранні бачать перекреслену звичайну", early["year"]["std_cents"], 9999)
    case("набір цін названо", early["set"], "early")
    case("своя ціна видно", billing.prices(person(own_price_cents=500))["own_cents"], 500)

    case("30 днів — місячний", billing._plan_by_days(30), "month")
    case("45 днів — усе ще місячний", billing._plan_by_days(45), "month")
    case("90 днів — квартал", billing._plan_by_days(90), "quarter")
    case("365 днів — рік", billing._plan_by_days(365), "year")
    case("400 днів — теж рік", billing._plan_by_days(400), "year")


# ------------------------------------------------------------ жива база ----

COLUMNS = ("plan", "paid_until", "free_trades_used", "free_trades_cap",
           "free_bt_used", "free_bt_cap", "imports_used", "imports_cap",
           "ai_used", "ai_cap", "ai_reset_at",
           "price_plan", "own_price_cents", "signup_ip", "signup_device",
           "billing_note")
TABLES = ("payments", "signup_ips", "ip_allow")


def check_db():
    print("\nжива база")
    db.init()
    db.init()          # другий раз нічого не має зламати
    print("  ok    db.init() двічі поспіль проходить")

    with db.connect() as conn:
        have = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users'").fetchall()}
        tabs = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public'").fetchall()}
    for c in COLUMNS:
        case("колонка users.%s" % c, c in have, True)
    for t in TABLES:
        case("таблиця %s" % t, t in tabs, True)

    tag = "billing_test_%d" % int(datetime.datetime.now().timestamp())
    u = db.create_user(tag + "@example.com", tag, "h", "s", 1)
    uid = u["id"]
    try:
        case("новий у базі — free", billing.state(uid)["plan"], "free")
        case("новому 30 справжніх", billing.state(uid)["trades_left"], 30)

        billing.spend_trade(uid)
        billing.spend_trade(uid)
        billing.spend_trade(uid, "bt")
        s = billing.state(uid)
        case("дві справжні витрачено", s["trades_left"], 28)
        case("один прогін витрачено", s["bt_left"], 29)
        case("перенесення не чіпали", s["imports_left"], 3)

        billing.spend_import(uid)
        case("перенесення витрачено", billing.state(uid)["imports_left"], 2)

        # Звернення до моделі: 15 проходять, 16-те — ні.
        for _ in range(15):
            billing.spend_ai(uid)
        s = billing.state(uid)
        case("15 звернень витрачено", s["ai_left"], 0)
        case("вікно звернень відкрилось", bool(s["ai_reset_at"]), True)
        case("шістнадцяте не проходить", billing.can_use_ai(uid),
             (False, "ai_limit"))

        billing.bonus(uid, ai=5)
        case("бонус на звернення", billing.state(uid)["ai_left"], 5)
        case("з бонусом знову можна", billing.can_use_ai(uid), (True, ""))

        billing.grant(uid, 30)
        s = billing.state(uid)
        case("підписка стала активною", s["active"], True)
        case("тариф місячний", s["plan"], "month")
        case("дата оплати є", bool(s["paid_until"]), True)

        billing.spend_trade(uid)
        case("з підпискою безкоштовне не витрачається",
             billing.state(uid)["trades_left"], 28)
        case("підписка підняла стелю звернень", billing.state(uid)["ai_cap"], 300)
        case("з підпискою помічник знову відповідає",
             billing.can_use_ai(uid), (True, ""))

        before = db.get_user(uid)["paid_until"]
        billing.grant(uid, 30)
        after = db.get_user(uid)["paid_until"]
        case("продовження додається до оплаченого",
             (after - before).days, 30)

        billing.bonus(uid, trades=5, bt=2, imports=1)
        s = billing.state(uid)
        case("бонус на справжні", s["trades_left"], 33)
        case("бонус на прогони", s["bt_left"], 31)
        case("бонус на перенесення", s["imports_left"], 3)

        billing.set_price(uid, price_plan="early")
        case("ранні ціни ввімкнено", billing.prices(uid)["month"]["cents"], 799)

        billing.revoke(uid)
        s = billing.state(uid)
        case("підписку знято", s["active"], False)
        case("тариф після зняття", s["plan"], "free")
        case("витрачене нікуди не поділось", s["trades_left"], 33)
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id=%s", (uid,))
            conn.commit()
        print("  ok    тимчасового користувача прибрано")


def main():
    # Час підміняємо тільки в частині без бази: жива частина працює
    # зі справжнім «зараз», інакше підписка «до вчора» не перевіриться.
    real_now = db.now
    db.now = lambda: NOW
    check_rules()
    check_prices()
    db.now = real_now

    if config.DATABASE_URL and "x/y" not in config.DATABASE_URL:
        try:
            check_db()
        except Exception as e:
            print("  ПРОПУЩЕНО  жива база недоступна: %s" % e)
    else:
        print("\n  ПРОПУЩЕНО  живу базу: DATABASE_URL не заданий")

    print("\n" + ("усе добре" if not _fails else
                  "є помилки: " + ", ".join(_fails)))
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
