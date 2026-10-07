# -*- coding: utf-8 -*-
"""
Докупка бектест-перенесень: python test_bt_pack.py

Три частини, як у test_billing.py. Перша — правила й ціни без бази.
Друга — жива, йде в базу з .env (видно за написом «жива база»); немає
DATABASE_URL — просто пропускається. Третя стукає у вебхук справжнім
підписом на піднятий сервер, її вмикає HOOK_PORT у оточенні.

Найголовніше тут три речі:
  * ціну рахує сервер, і тільки він — з браузера приходить кількість;
  * разова покупка НЕ видає підписку: вона приходить тим самим
    checkout.completed, що й перша оплата тарифу;
  * повторна доставка тієї самої події не піднімає стелю вдруге.
"""
import datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

# config читає .env — спершу він, інакше заглушка нижче перекрила б
# справжню адресу бази, і жива частина мовчки пропускалась би
import config

LIVE = bool(config.DATABASE_URL)
if not LIVE:
    os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import billing
import creem
import db

_fails = []


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    if not ok:
        _fails.append(name)
    return ok


def person(**kw):
    """Підписчик, який ще не докуповував перенесень."""
    row = {"id": 1, "plan": "month",
           "paid_until": db.now() + datetime.timedelta(days=10),
           "free_trades_used": 0, "free_trades_cap": 20,
           "free_bt_used": 0, "free_bt_cap": 20,
           "imports_used": 0, "imports_cap": 3,
           "bt_imports_used": 0, "bt_imports_cap": 3,
           "ai_used": 0, "ai_cap": 15, "ai_reset_at": None,
           "price_plan": "std", "own_price_cents": None,
           "imports_until": None, "created_at": db.now(),
           "promo_code": None, "promo_used_at": None}
    row.update(kw)
    return row


# ------------------------------------------------------------------ ціни ----

def check_prices():
    print("\nціну рахує сервер")
    case("три перенесення", config.bt_pack_cents(3), 399)
    case("двадцять", config.bt_pack_cents(20), 1899)
    case("між опорами — прямою", config.bt_pack_cents(7), 799)
    case("менше мінімуму — нуль", config.bt_pack_cents(2), 0)
    case("більше максимуму — нуль", config.bt_pack_cents(21), 0)
    case("сміття замість числа — нуль", config.bt_pack_cents("двадцять"), 0)
    case("пусто — нуль", config.bt_pack_cents(None), 0)
    case("дріб зводиться до цілого", config.bt_pack_cents(7.9),
         config.bt_pack_cents(7))

    span = list(range(config.BT_PACK_MIN, config.BT_PACK_MAX + 1))
    cents = [config.bt_pack_cents(n) for n in span]
    case("є ціна на кожну кількість", all(c > 0 for c in cents), True)
    case("усі ціни кінчаються на 9", all(c % 10 == 9 for c in cents), True)
    case("сума росте з кількістю",
         all(cents[i] > cents[i - 1] for i in range(1, len(cents))), True)
    per = [c / float(n) for c, n in zip(cents, span)]
    # Головна умова сітки: за штуку завжди дешевше, ніж на крок раніше.
    # Інакше брати більше невигідно, і ползунок стає ловушкою.
    case("ціна за штуку падає на кожному кроці",
         all(per[i] < per[i - 1] for i in range(1, len(per))), True)

    print("\nумови докупки назовні")
    p = billing.bt_pack(person())
    case("межі ті самі", (p["min"], p["max"]), (3, 20))
    case("валюта", p["currency"], "EUR")
    case("віддано всі вісімнадцять цін", len(p["prices"]), 18)
    case("ціни ті самі, що рахує config", p["prices"]["10"],
         config.bt_pack_cents(10))
    case("стеля людини", billing.bt_pack(person(bt_imports_cap=7))["cap"], 7)
    case("каса ввімкнена тільки з ключем і товаром", p["on"],
         bool(config.CREEM_API_KEY and config.CREEM_BT_PACK_PRODUCT))


# --------------------------------------------------------------- дозволи ----

def check_rules():
    print("\nбектест з Notion — тільки з підпискою")
    free = person(plan="free", paid_until=None)
    case("без підписки не переносимо", billing.can_import(free, "bt"),
         (False, billing.BT_NOTION))
    case("з підпискою — можна", billing.can_import(person(), "bt"), (True, ""))
    case("вікно перших днів бектесту не стосується",
         billing.can_import(
             person(created_at=db.now() - datetime.timedelta(days=90)), "bt"),
         (True, ""))
    case("звичайне перенесення живе за своїми правилами",
         billing.can_import(free, ""), (True, ""))

    print("\nкаса на докупку")
    try:
        creem.pack_checkout(1, 3, 0)
        got = "пустило"
    except ValueError as ex:
        # Товару може не бути — тоді падає раніше, і це теж відмова,
        # яка нас влаштовує.
        got = "нуль" if "додатні" in str(ex) else "товару немає"
    case("нульову суму каса не бере", got in ("нуль", "товару немає"), True)

    print("\nрозпізнаємо покупку серед подій платіжки")
    case("підписка — не докупка",
         creem.pack_of({"metadata": {"user_id": "5", "plan": "month"}}), 0)
    case("докупка в самій події",
         creem.pack_of({"metadata": {"user_id": "5", "kind": "bt_imports",
                                     "n": "7"}}), 7)
    case("докупка в замовленні всередині",
         creem.pack_of({"order": {"metadata": {"kind": "bt_imports",
                                               "n": "20"}}}), 20)
    case("порожня подія", creem.pack_of({}), 0)
    case("кількість зіпсована — не докупка",
         creem.pack_of({"metadata": {"kind": "bt_imports", "n": "усі"}}), 0)
    case("номер людини читається і з докупки",
         creem.who({"metadata": {"user_id": "42", "kind": "bt_imports",
                                 "n": "7"}}), 42)


# ------------------------------------------------------------- жива база ----

def live():
    print("\nжива база")
    db.init()
    tag = "btpack_test_%d" % int(datetime.datetime.now().timestamp())
    uid = db.create_user(tag + "@example.com", tag, "h", "s", 1)["id"]
    try:
        case("стеля з коробки", db.get_user(uid)["bt_imports_cap"],
             config.BT_PACK_MIN)

        # --- без підписки перенести не дають, навіть у межах стелі ---
        case("без підписки не займається", billing.take_bt_import(uid),
             (False, billing.BT_NOTION))
        case("лічильник не зрушив", db.get_user(uid)["bt_imports_used"], 0)

        billing.grant(uid, 30, "month")
        case("з підпискою перше зайнялось", billing.take_bt_import(uid),
             (True, ""))

        # --- стеля тримає ---
        billing.take_bt_import(uid)
        billing.take_bt_import(uid)
        case("три зайнято", db.get_user(uid)["bt_imports_used"], 3)
        case("четверте — межа", billing.take_bt_import(uid),
             (False, billing.BT_NOTION_LIMIT))

        # --- оплата піднімає стелю ---
        billing.bt_pack_add(uid, 7)
        case("стеля піднялась", db.get_user(uid)["bt_imports_cap"], 10)
        case("витрачене не чіпали", db.get_user(uid)["bt_imports_used"], 3)
        case("після оплати знову можна", billing.take_bt_import(uid), (True, ""))

        # --- повернення грошей забирає куплене, але не базові три ---
        billing.bt_pack_drop(uid, 7)
        case("стеля повернулась", db.get_user(uid)["bt_imports_cap"], 3)
        billing.bt_pack_drop(uid, 99)
        case("нижче трьох не падає", db.get_user(uid)["bt_imports_cap"],
             config.BT_PACK_MIN)
        billing.bt_pack_add(uid, 0)
        case("нуль нічого не робить", db.get_user(uid)["bt_imports_cap"],
             config.BT_PACK_MIN)

        # --- докуплене не згорає разом з підпискою, але й не працює без неї ---
        billing.bt_pack_add(uid, 5)
        billing.revoke(uid)
        case("без підписки куплене лежить",
             db.get_user(uid)["bt_imports_cap"], 8)
        case("але скористатись ним не можна", billing.take_bt_import(uid),
             (False, billing.BT_NOTION))

        # --- повтор події: заслон стоїть на id, а не на сумі ---
        ev = "evt_btpack_%s" % uid
        first = db.payment_once(ev, uid, "checkout.completed", 399, "EUR", {})
        again = db.payment_once(ev, uid, "checkout.completed", 399, "EUR", {})
        case("першу подію записали", first, True)
        case("ту саму вдруге — ні", again, False)
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id=%s", (uid,))
            conn.commit()
        print("  ok    тимчасового користувача прибрано")


# ------------------------------------------------ вебхук по-справжньому ----

def hook(port, body):
    """Постукати у вебхук справжнім підписом."""
    raw = json.dumps(body).encode("utf-8")
    sign = hmac.new(config.CREEM_WEBHOOK_SECRET.encode("utf-8"), raw,
                    hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        "http://127.0.0.1:%s/api/creem/webhook" % port, data=raw,
        headers={"Content-Type": "application/json", "creem-signature": sign},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as ex:
        return ex.code, {}


def webhook(port):
    print("\nвебхук на порті %s" % port)
    tag = "bthook_test_%d" % int(datetime.datetime.now().timestamp())
    uid = db.create_user(tag + "@example.com", tag, "h", "s", 1)["id"]
    try:
        billing.grant(uid, 30, "month")
        cap0 = db.get_user(uid)["bt_imports_cap"]
        until = db.get_user(uid)["paid_until"]
        ev = {"id": "evt_%s_1" % tag, "eventType": "checkout.completed",
              "object": {"metadata": {"user_id": str(uid),
                                      "kind": "bt_imports", "n": "7"},
                         "amount": 1099, "currency": "EUR"}}
        st, _ = hook(port, ev)
        case("подію прийняли", st, 200)
        case("стеля піднялась на сім",
             db.get_user(uid)["bt_imports_cap"], cap0 + 7)
        case("підписку покупка не продовжила",
             db.get_user(uid)["paid_until"], until)

        st, out = hook(port, ev)
        case("повтор прийняли теж", st, 200)
        case("повтор позначено", out.get("repeat"), True)
        case("стеля не піднялась удвічі",
             db.get_user(uid)["bt_imports_cap"], cap0 + 7)

        # --- те саме людині без підписки: покупка підписки не дає ---
        tag2 = tag + "b"
        uid2 = db.create_user(tag2 + "@example.com", tag2, "h", "s", 1)["id"]
        try:
            st, _ = hook(port, {
                "id": "evt_%s_2" % tag, "eventType": "checkout.completed",
                "object": {"metadata": {"user_id": str(uid2),
                                        "kind": "bt_imports", "n": "3"},
                           "amount": 399, "currency": "EUR"}})
            case("покупка без підписки прийнята", st, 200)
            case("стеля виросла", db.get_user(uid2)["bt_imports_cap"],
                 config.BT_PACK_MIN + 3)
            case("але підписки покупка не видала",
                 billing.active(db.get_user(uid2)), False)
            case("тариф лишився безкоштовним",
                 billing.plan_of(db.get_user(uid2)), "free")
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM users WHERE id=%s", (uid2,))
                conn.commit()

        # --- повернення грошей за докупку не знімає підписку ---
        st, _ = hook(port, {
            "id": "evt_%s_3" % tag, "eventType": "refund.created",
            "object": {"metadata": {"user_id": str(uid),
                                    "kind": "bt_imports", "n": "7"}}})
        case("повернення прийняли", st, 200)
        case("стелю забрали", db.get_user(uid)["bt_imports_cap"], cap0)
        case("підписку не зняли", billing.active(db.get_user(uid)), True)
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id=%s", (uid,))
            conn.commit()
        print("  ok    тимчасових користувачів прибрано")


def main():
    check_prices()
    check_rules()
    if LIVE:
        live()
        port = os.environ.get("HOOK_PORT") or ""
        if port and config.CREEM_WEBHOOK_SECRET:
            webhook(port)
        else:
            print("\nвебхук пропущено: немає HOOK_PORT (піднятий сервер) "
                  "або CREEM_WEBHOOK_SECRET")
    else:
        print("\nжива база пропущена: немає DATABASE_URL")
    print("\n" + ("усе добре" if not _fails
                  else "є помилки: " + ", ".join(_fails)))
    return 0 if not _fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
