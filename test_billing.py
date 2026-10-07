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
import antifraud
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
           "free_trades_used": 0, "free_trades_cap": 20,
           "free_bt_used": 0, "free_bt_cap": 20,
           "imports_used": 0, "imports_cap": 3,
           "ai_used": 0, "ai_cap": 15, "ai_reset_at": None,
           "price_plan": "std", "own_price_cents": None,
           "imports_until": None,
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
    case("залишок справжніх", out["trades_left"], 20)
    case("залишок прогонів", out["bt_left"], 20)
    case("залишок перенесень", out["imports_left"], 3)
    case("днів вікна перенесення", out["import_days_left"], 25)
    case("дати оплати немає", out["paid_until"], None)

    # Несиметрія лімітів — головне правило.
    dry = person(free_trades_used=20)
    case("скінчились справжні — відмова", billing.can_add_trade(dry),
         (False, "trades_limit"))
    case("скінчились справжні — бектест теж закрито",
         billing.can_add_trade(dry, "bt"), (False, "trades_limit"))
    case("залишок не йде в мінус", billing.state(dry)["trades_left"], 0)

    bt_dry = person(free_trades_used=10, free_bt_used=20)
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

    old = paid(days=-1, free_trades_used=20)
    case("прострочена підписка не діє", billing.active(old), False)
    case("прострочений тариф — free", billing.plan_of(old), "free")
    case("після прострочення ліміт знову діє", billing.can_add_trade(old),
         (False, "trades_limit"))

    # Довічна підписка: дата кінця порожня, а відкрито все.
    life = person(plan="life", paid_until=None, free_trades_used=99)
    case("довічна діє", billing.active(life), True)
    case("довічна називається life", billing.plan_of(life), "life")
    case("з довічною угоди пишуться", billing.can_add_trade(life), (True, ""))
    case("з довічною бектест пишеться", billing.can_add_trade(life, "bt"), (True, ""))
    case("з довічною переносити можна",
         billing.can_import(person(plan="life", paid_until=None, imports_used=9,
                                   created_at=NOW - datetime.timedelta(days=400))),
         (True, ""))
    case("довічна підіймає стелю звернень", billing.ai_cap(life), 300)
    case("довічна без дати кінця", billing.state(life)["paid_until"], None)
    case("прострочений тариф — не довічна",
         billing.plan_of(person(plan="year",
                                paid_until=NOW - datetime.timedelta(days=1))), "free")

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
    # «Ранній»: зареєструвався рік тому, але міграція відкрила йому вікно
    # наново — від created_at воно давно б минуло.
    early_imp = person(price_plan="early",
                       created_at=NOW - datetime.timedelta(days=400),
                       imports_until=NOW + datetime.timedelta(days=30))
    case("ранньому вікно відкрито наново",
         billing.can_import(early_imp), (True, ""))
    case("ранньому лишилось 30 днів",
         billing.import_days_left(early_imp), 30)
    gone = person(imports_until=NOW - datetime.timedelta(hours=1))
    case("задане вікно теж закінчується",
         billing.can_import(gone), (False, "import_window"))
    case("задане вікно минуло — днів нуль",
         billing.import_days_left(gone), 0)
    case("останній день вікна — ще день",
         billing.import_days_left(person(
             imports_until=NOW + datetime.timedelta(hours=5))), 1)

    # Бектест-журнали з Notion — окремий рахунок: тільки з підпискою, зате
    # ні вікно перших днів, ні витрачені звичайні перенесення їх не
    # закривають. Скінчилась своя стеля — перенесення докуповують
    # (test_bt_pack.py).
    case("без підписки бектест не переносять",
         billing.can_import(person(), "bt"), (False, "bt_notion"))
    case("з підпискою — переносять",
         billing.can_import(paid(), "bt"), (True, ""))
    case("бектест не впирається у звичайні перенесення",
         billing.can_import(paid(imports_used=3), "bt"), (True, ""))
    case("бектест переносять і після вікна",
         billing.can_import(paid(created_at=NOW - datetime.timedelta(days=90)),
                            "bt"), (True, ""))

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

    # Нік власника — це права адміна, тому його не можна ні взяти в
    # профілі, ні привезти іменем з Google чи Discord (там пробіли
    # дозволені, і саме цим шляхом ім'я власника проходило як своє).
    print("\nніки власників")
    for nick in config.ADMIN_NICKS:
        case("не віддаємо нік %r" % nick, config.nick_reserved(nick), True)
        case("не віддаємо його ж іншим регістром",
             config.nick_reserved(nick.upper()), True)
    case("службовий нік теж зайнятий", config.nick_reserved("admin"), True)
    case("звичайний нік вільний", config.nick_reserved("trader7"), False)

    # Одна скринька — один безкоштовний журнал. Хвіст після «+» і крапки в
    # gmail нічого не змінюють, а чужі домени з крапками не чіпаємо.
    print("\nодна пошта — один журнал")
    same = [("ivan@gmail.com", "ivan+1@gmail.com"),
            ("ivan@gmail.com", "i.v.a.n@gmail.com"),
            ("ivan@gmail.com", "IVAN+хвіст@Gmail.com"),
            ("ivan@googlemail.com", "i.van+2@googlemail.com"),
            ("ivan@mail.com", "ivan+7@mail.com")]
    for a, b in same:
        case("%s = %s" % (a, b), db.email_key(a) == db.email_key(b), True)
    case("крапки поза gmail значать своє",
         db.email_key("i.van@mail.com") == db.email_key("ivan@mail.com"), False)
    case("різні люди лишаються різними",
         db.email_key("ivan@gmail.com") == db.email_key("petro@gmail.com"), False)

    print("\nодноразова пошта")
    for bad in ("kto@mailinator.com", "kto@temp-mail.org", "kto@sub.yopmail.com"):
        case("не приймаємо %s" % bad, antifraud.throwaway_mail(bad), True)
    for good in ("kto@gmail.com", "kto@ukr.net", "kto@company.co.uk"):
        case("приймаємо %s" % good, antifraud.throwaway_mail(good), False)


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

    # Промокод FXLAB «раннім» ні до чого: у них та сама ціна, і код мусить
    # відбитись, а не переводити їх у партнерський набір — інакше в обліку FX LAB
    # опинились би люди, які прийшли самі.
    case("ранньому FXLAB не потрібен",
         billing.redeem(person(price_plan="early"), "FXLAB"),
         (False, "promo_same"))
    case("двічі той самий код не проходить",
         billing.redeem(person(price_plan="fxlab"), "FXLAB"),
         (False, "promo_same"))
    case("вигаданий код", billing.redeem(person(), "ХАЛЯВА"),
         (False, "promo_bad"))
    # Знижка йде в касу тільки тому, хто на звичайних цінах. Набір міг
    # змінитись уже після того, як код прийняли, — тоді товар у Creem інший,
    # і знижка до нього не кріпиться.
    case("код у касу: звичайний набір",
         billing.promo_discount(person(promo_code="FXLAB"), "month"), "FXLAB-M")
    case("код у касу: ранній — без знижки",
         billing.promo_discount(person(promo_code="FXLAB", price_plan="early"), "month"), "")
    case("код у касу: партнерський набір — без знижки",
         billing.promo_discount(person(promo_code="FXLAB", price_plan="fxlab"), "year"), "")
    case("код у касу: коду немає — порожньо",
         billing.promo_discount(person(), "month"), "")
    case("код у касу: оплачений код не йде",
         billing.promo_discount(person(promo_code="FXLAB", promo_used_at=NOW), "year"), "")
    # Промокод — один раз: після оплати по ньому вдруге не приймається
    case("по коду вже платили — вдруге ні",
         billing.redeem(person(promo_code="FXLAB", promo_used_at=NOW), "FXLAB"),
         (False, "promo_used"))
    case("підписка вже йде — код тільки на першу оплату",
         billing.redeem(paid(plan="month", price_plan="std"), "FXLAB"),
         (False, "promo_active"))
    pr = billing.prices(person(promo_code="FXLAB"))
    case("введений код: місяць як у ранніх", (pr["set"], pr["month"]["cents"]), ("promo", 799))
    case("введений код: квартал як у ранніх", pr["quarter"]["cents"], 2097)
    case("введений код: рік як у ранніх", pr["year"]["cents"], 7188)
    case("після оплати по коду — звичайні ціни",
         billing.prices(person(promo_code="FXLAB", promo_used_at=NOW))["month"]["cents"], 1199)
    case("ранньому й вигаданий код не допоможе",
         billing.redeem(person(price_plan="early"), "ХАЛЯВА"),
         (False, "promo_bad"))
    case("поле промокоду ранньому не показуємо",
         billing.prices(person(price_plan="early"))["set"] == "std", False)

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
           "billing_note", "imports_until")
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
        case("новому 20 справжніх", billing.state(uid)["trades_left"], 20)

        billing.spend_trade(uid)
        billing.spend_trade(uid)
        billing.spend_trade(uid, "bt")
        s = billing.state(uid)
        case("дві справжні витрачено", s["trades_left"], 18)
        case("один прогін витрачено", s["bt_left"], 19)
        case("перенесення не чіпали", s["imports_left"], 3)

        billing.spend_import(uid)
        case("перенесення витрачено", billing.state(uid)["imports_left"], 2)

        # Межа тримається самою базою, а не парою «спитали → списали».
        # Перевіряємо саме те, чим її обходили: сервер відповідає в багато
        # потоків, і пачка одночасних запитів проходила перевірку всі
        # разом, поки лічильник ще не встиг вирости.
        #
        # Лічильники тут крутимо як хочемо, тому спершу запам'ятовуємо їх:
        # перевірки нижче рахують від того, що було до цього місця.
        SPENT = ("free_trades_used", "free_bt_used", "imports_used",
                 "ai_used", "ai_reset_at")
        spent_was = {k: db.get_user(uid)[k] for k in SPENT}
        with db.connect() as c2:
            c2.execute("UPDATE users SET free_trades_used=0, free_bt_used=0, "
                       "imports_used=0 WHERE id=%s", (uid,))
            c2.commit()
        took = [billing.take_trade(uid)[0] for _ in range(25)]
        case("зайняти вдалось рівно двадцять", sum(took), 20)
        case("двадцять перших пройшли", all(took[:20]), True)
        case("решті відмовили", any(took[20:]), False)
        case("лічильник рівно на межі",
             db.get_user(uid)["free_trades_used"], 20)
        case("за межею причина зрозуміла", billing.take_trade(uid),
             (False, "trades_limit"))

        # Повернення місця: угоду зайняли, а записати не вийшло.
        billing.release_trade(uid)
        case("місце повернулось", db.get_user(uid)["free_trades_used"], 19)
        case("і його можна зайняти знову", billing.take_trade(uid), (True, ""))

        # Те саме для перенесень.
        with db.connect() as c2:
            c2.execute("UPDATE users SET imports_used=0 WHERE id=%s", (uid,))
            c2.commit()
        took = [billing.take_import(uid)[0] for _ in range(6)]
        case("перенесень зайнято рівно три", sum(took), 3)
        case("четверте перенесення відбито", billing.take_import(uid),
             (False, "imports_limit"))

        # Бектест-бази з Notion: та сама межа в три, але своїм лічильником
        # і тільки з підпискою — її тут і даємо, бо людина поки free.
        with db.connect() as c2:
            c2.execute("UPDATE users SET bt_imports_used=0 WHERE id=%s", (uid,))
            c2.commit()
        case("без підписки бектест-база не займається",
             billing.take_bt_import(uid), (False, "bt_notion"))
        billing.grant(uid, 30, "month")
        took = [billing.take_bt_import(uid)[0] for _ in range(6)]
        case("бектест-баз зайнято рівно три", sum(took), 3)
        case("четверта база бектесту відбита", billing.take_bt_import(uid),
             (False, "bt_notion_limit"))
        case("звичайні перенесення бектест не чіпав",
             db.get_user(uid)["imports_used"], 3)
        # Підписку знімаємо назад: далі в цьому ж тілі перевіряється
        # безкоштовна порція звернень до моделі, а з підпискою стеля там інша.
        billing.revoke(uid)

        # Порція звернень до моделі — так само однією дією.
        with db.connect() as c2:
            c2.execute("UPDATE users SET ai_used=0, ai_reset_at=NULL WHERE id=%s", (uid,))
            c2.commit()
        took = [billing.take_ai(uid)[0] for _ in range(20)]
        case("звернень зайнято рівно п'ятнадцять", sum(took), 15)
        case("шістнадцяте відбито", billing.take_ai(uid), (False, "ai_limit"))
        with db.connect() as c2:
            c2.execute("UPDATE users SET " + ", ".join(k + "=%s" for k in SPENT)
                       + " WHERE id=%s", tuple(spent_was[k] for k in SPENT) + (uid,))
            c2.commit()

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
             billing.state(uid)["trades_left"], 18)
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
        case("бонус на справжні", s["trades_left"], 23)
        case("бонус на прогони", s["bt_left"], 21)
        case("бонус на перенесення", s["imports_left"], 3)

        # Міграція «ранніх». База тут жива й боєва, тому пробуємо не саму
        # функцію, а її запит — у власній транзакції, яку одразу
        # відкочуємо: роздати знижку всім за дні до викладки означало б
        # зіпсувати саму акцію.
        if config.EARLY_MIGRATION:
            print("  ПРОПУЩЕНО  міграцію ранніх: EARLY_MIGRATION=1")
        else:
            db._grandfather_early()
            case("без вимикача міграція не чіпає базу",
                 db.meta_get("early_marked"), None)
            conn = db.psycopg.connect(config.DATABASE_URL,
                                      row_factory=db.dict_row)
            try:
                conn.execute(db.EARLY_SQL, (config.IMPORT_WINDOW_DAYS,))
                r = conn.execute(
                    "SELECT price_plan, imports_until, plan, paid_until "
                    "FROM users WHERE id=%s", (uid,)).fetchone()
                case("міграція робить ранніми", r["price_plan"], "early")
                # Годинник бази й наш розходяться на секунди, тому не
                # рівність, а межі: вікно щойно відкрите на 30 днів.
                left = billing.import_days_left(r)
                case("міграція відкриває вікно перенесення",
                     config.IMPORT_WINDOW_DAYS <= left
                     <= config.IMPORT_WINDOW_DAYS + 1, True)
                case("міграція не чіпає оплачене", r["plan"], "month")
                case("міграція не чіпає дату оплати", bool(r["paid_until"]), True)
            finally:
                conn.rollback()
                conn.close()
            case("відкат повернув звичайні ціни",
                 db.get_user(uid)["price_plan"], "std")

            # Запуск лімітів. Так само на живій базі — тому запит, а не
            # функція, і теж під відкат: запустити відлік усім за дні до
            # викладки означало б з'їсти людям безкоштовні угоди.
            db._start_limits()
            case("без вимикача ліміти не запускаються",
                 db.meta_get("limits_started"), None)
            # Далі підміняємо лічильники цьому акаунту, тож спершу
            # запам'ятовуємо їх — наступні перевірки рахують від них.
            KEEP = ("free_trades_cap", "free_bt_cap", "free_trades_used",
                    "free_bt_used", "imports_used", "ai_used")
            was = {k: db.get_user(uid)[k] for k in KEEP}
            with db.connect() as c2:
                c2.execute("UPDATE users SET free_trades_used=7, free_bt_used=3, "
                           "imports_used=2, ai_used=4, free_trades_cap=30, "
                           "free_bt_cap=30 WHERE id=%s", (uid,))
                c2.commit()
            conn = db.psycopg.connect(config.DATABASE_URL, row_factory=db.dict_row)
            try:
                conn.execute(db.LIMITS_SQL, (config.FREE_TRADES, config.FREE_BT))
                r = conn.execute(
                    "SELECT free_trades_cap, free_bt_cap, free_trades_used, "
                    "free_bt_used, imports_used, ai_used, ai_reset_at, "
                    "plan, paid_until FROM users WHERE id=%s", (uid,)).fetchone()
                case("стеля угод стала двадцяткою", r["free_trades_cap"], 20)
                case("стеля бектесту стала двадцяткою", r["free_bt_cap"], 20)
                case("старі угоди в ліміт не пішли", r["free_trades_used"], 0)
                case("старий бектест у ліміт не пішов", r["free_bt_used"], 0)
                case("перенесення з нуля", r["imports_used"], 0)
                case("звернення з нуля", r["ai_used"], 0)
                case("вікно звернень скинуто", r["ai_reset_at"], None)
                case("запуск лімітів не чіпає оплачене", r["plan"], "month")
                case("запуск лімітів не чіпає дату оплати", bool(r["paid_until"]), True)
            finally:
                conn.rollback()
                conn.close()
            # Бонус адміна стелею не є: його міграція обходить.
            with db.connect() as c2:
                c2.execute("UPDATE users SET free_trades_cap=35 WHERE id=%s", (uid,))
                c2.commit()
            conn = db.psycopg.connect(config.DATABASE_URL, row_factory=db.dict_row)
            try:
                conn.execute(db.LIMITS_SQL, (config.FREE_TRADES, config.FREE_BT))
                r = conn.execute("SELECT free_trades_cap FROM users WHERE id=%s",
                                 (uid,)).fetchone()
                case("бонус адміна лишається", r["free_trades_cap"], 35)
            finally:
                conn.rollback()
                conn.close()
            with db.connect() as c2:
                c2.execute("UPDATE users SET " + ", ".join(k + "=%s" for k in KEEP)
                           + " WHERE id=%s", tuple(was[k] for k in KEEP) + (uid,))
                c2.commit()

        # Промокод на живому акаунті: звичайному він знижує ціну, а тому,
        # хто вже «ранній», — відбивається.
        billing.set_price(uid, price_plan="std")
        billing.revoke(uid)
        with db.connect() as conn:
            conn.execute("UPDATE users SET promo_code=NULL, promo_used_at=NULL WHERE id=%s", (uid,))
            conn.commit()
        case("код приймається", billing.redeem(uid, "fxlab"), (True, ""))
        case("після коду перший платіж знижено", billing.prices(uid)["month"]["cents"], 799)
        case("набір цін не змінився", db.get_user(uid)["price_plan"], "std")
        case("до оплати код можна ввести ще раз", billing.redeem(uid, "FXLAB"), (True, ""))
        billing.promo_paid(uid)
        case("після оплати — звичайна ціна", billing.prices(uid)["month"]["cents"], 1199)
        case("після оплати код удруге не проходить", billing.redeem(uid, "FXLAB"),
             (False, "promo_used"))
        case("код лишився в картці", db.get_user(uid)["promo_code"], "FXLAB")

        # Довічна з адмінки: тариф life, дати кінця немає, підписка діє.
        billing.grant_life(uid)
        s2 = billing.state(uid)
        case("довічну видано", s2["plan"], "life")
        case("довічна активна", s2["active"], True)
        case("у довічної немає дати", s2["paid_until"], None)
        case("довічну видно в базі", db.get_user(uid)["plan"], "life")
        billing.revoke(uid)
        case("довічну можна зняти", billing.state(uid)["active"], False)
        billing.grant(uid, 30)

        billing.set_price(uid, price_plan="early")
        case("ранні ціни ввімкнено", billing.prices(uid)["month"]["cents"], 799)
        case("ранньому код відбивається", billing.redeem(uid, "FXLAB"),
             (False, "promo_same"))
        case("набір раннього код не змінив",
             db.get_user(uid)["price_plan"], "early")

        billing.revoke(uid)
        s = billing.state(uid)
        case("підписку знято", s["active"], False)
        case("тариф після зняття", s["plan"], "free")
        case("витрачене нікуди не поділось", s["trades_left"], 23)
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
