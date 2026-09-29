# -*- coding: utf-8 -*-
"""Оплата криптою: рахунки, зіставляння переказів і запасні шляхи.

Блокчейн тут не питаємо — його підміняємо. Перевіряти треба нашу логіку
(чий це переказ, чи не зарахували двічі, що робити з округленою сумою), а
не те, що TronGrid віддає відповідь: для цього довелось би платити
справжніми грошима за кожен прогін.

Адреси й розбір відповіді перевіряються окремо, на живих даних, — див.
кінець файлу.
"""
import os
import sys

os.environ.setdefault("TRON_WALLET", "TGtTxZNutxhhNDPPjPusv3svqYHXDWuLXN")

import billing                                                # noqa: E402
import config                                                 # noqa: E402
import crypto_pay                                             # noqa: E402
import db                                                     # noqa: E402
import tron                                                   # noqa: E402

BAD = []


def case(name, got, want):
    ok = got == want
    print("  %-6s %s" % ("ok" if ok else "ПОМИЛКА", name), end="")
    print("" if ok else "  → отримали %r, чекали %r" % (got, want))
    if not ok:
        BAD.append(name)


def check_addresses():
    """Адреса, її контрольна сума й переклад між двома написаннями."""
    print("\nадреси TRON")
    w = "TGtTxZNutxhhNDPPjPusv3svqYHXDWuLXN"
    case("наша адреса сходиться", tron.valid(w), True)
    case("одна змінена літера — не адреса",
         tron.valid(w[:-1] + ("M" if w[-1] != "M" else "N")), False)
    case("порожнє — не адреса", tron.valid(""), False)
    case("чуже сміття — не адреса", tron.valid("не адреса зовсім"), False)
    case("hex і назад", tron.from_hex(tron.to_hex(w)), w)
    case("hex із префіксом 41", tron.from_hex("41" + tron.to_hex(w)), w)
    case("hex із 0x", tron.from_hex("0x" + tron.to_hex(w)), w)
    case("обрізаний hex не проходить", tron.from_hex("0x1234"), "")

    print("\nсуми")
    case("частки з монет", tron.to_units(11.9943), 11994300)
    case("монети з часток", tron.to_usdt(11994300), 11.9943)
    case("копійки не губляться", tron.to_usdt(tron.to_units(0.000001)), 0.000001)


def check_rows():
    """Розбір відповіді: чуже й підроблене не має ставати оплатою."""
    print("\nщо вважаємо переказом")
    ours = tron.TRON_WALLET
    good = {"type": "Transfer", "transaction_id": "a" * 64,
            "token_info": {"address": config.USDT_CONTRACT},
            "to": ours, "from": "T" + "x" * 33, "value": "11994300",
            "block_timestamp": 1700000000000}
    case("справжній переказ беремо", len(tron._rows({"data": [good]})), 1)

    other_coin = dict(good, token_info={"address": "TFake" + "x" * 29})
    case("чужий токен не рахуємо", len(tron._rows({"data": [other_coin]})), 0)

    not_us = dict(good, to="T" + "z" * 33)
    case("переказ не нам не рахуємо", len(tron._rows({"data": [not_us]})), 0)

    approve = dict(good, type="Approval")
    case("не переказ не рахуємо", len(tron._rows({"data": [approve]})), 0)

    zero = dict(good, value="0")
    case("нуль не рахуємо", len(tron._rows({"data": [zero]})), 0)


def check_flow():
    """Повний шлях: рахунок → переказ → підписка. На живій базі."""
    print("\nрахунок і оплата")
    tag = "crypto_test_%d" % int(db.now().timestamp())
    u = db.create_user(tag + "@example.com", tag, "h", "s", 1)
    uid = u["id"]
    seen = []
    u2 = None
    try:
        inv = crypto_pay.create(uid, "month")
        case("рахунок виставлено", bool(inv), True)
        case("тариф записано", inv["plan"], "month")
        case("рахунок чекає оплати", inv["status"], "new")

        base = crypto_pay.price_units(uid, "month")
        span = crypto_pay.TAIL * crypto_pay.STEP
        case("сума близька до ціни",
             base <= inv["units"] < base + span, True)
        case("надбавка непомітна для гаманця",
             crypto_pay.TAIL * crypto_pay.STEP <= 100_000, True)
        # Крок між сумами має перекривати допуск з обох боків, інакше два
        # рахунки ловлять той самий переказ.
        case("крок більший за подвійний допуск",
             crypto_pay.STEP > 2 * crypto_pay.SLACK_UNITS, True)

        pub = crypto_pay.public(inv)
        case("сторінці віддали адресу", pub["wallet"], tron.TRON_WALLET)
        case("сторінці віддали мережу", pub["network"], "TRON (TRC-20)")
        case("сума рядком без зайвих нулів",
             pub["amount_text"].endswith("0"), False)

        # Другий рахунок гасить перший: два числа на екрані — це плутанина.
        inv2 = crypto_pay.create(uid, "year")
        case("новий рахунок виставлено", bool(inv2), True)
        case("старий згас", crypto_pay.current(uid)["id"], inv2["id"])

        # Переказ рівно на суму рахунку.
        tx = "b" * 64
        seen.append(tx)
        row = {"tx": tx, "from": "T" + "y" * 33, "units": inv2["units"],
               "at": 1700000000000}
        found = crypto_pay._match(row["units"])
        case("рахунок знайдено за сумою", found["id"], inv2["id"])
        case("оплату зараховано",
             crypto_pay._settle(found, row["tx"], row["from"]), True)
        case("підписка ввімкнулась", billing.state(uid)["active"], True)
        case("тариф той, що оплатили", billing.state(uid)["plan"], "year")

        # Той самий переказ удруге не має продовжити підписку.
        case("повтор не проходить",
             crypto_pay._settle(found, row["tx"], row["from"]), False)

        # Трохи більша сума — зараховуємо: людина накинула зайвого.
        inv3 = crypto_pay.create(uid, "month")
        case("рахунок під дрібницю виставлено", bool(inv3), True)
        case("невелика переплата підходить",
             (crypto_pay._match(inv3["units"] + 300) or {}).get("id"), inv3["id"])
        case("недобір у межах дрібниці підходить",
             (crypto_pay._match(inv3["units"] - 300) or {}).get("id"), inv3["id"])
        case("округлена сума вже не підходить",
             crypto_pay._match(inv3["units"] + 1_000_000), None)

        # Два відкритих рахунки на той самий тариф: суми мають розходитись
        # більше, ніж на допуск, інакше переказ одного закриє рахунок іншого.
        tag2 = tag + "_b"
        u2 = db.create_user(tag2 + "@example.com", tag2, "h", "s", 1)  # noqa: F841
        other = crypto_pay.create(u2["id"], "month")
        case("другому дали іншу суму", other["units"] == inv3["units"], False)
        case("суми розійшлись більше за допуск",
             abs(other["units"] - inv3["units"]) > 2 * crypto_pay.SLACK_UNITS, True)
        case("кожен переказ знаходить свій рахунок",
             (crypto_pay._match(other["units"]) or {}).get("id"), other["id"])
        case("і навпаки", (crypto_pay._match(inv3["units"]) or {}).get("id"), inv3["id"])

        # «Скасувати рахунок»: чекати перестали, але гроші, що вже пішли,
        # мають дійти самі.
        case("рахунок скасовано", crypto_pay.cancel(u2["id"]), True)
        case("більше його не чекаємо", crypto_pay.current(u2["id"]), None)
        late = crypto_pay._match(other["units"])
        case("переказ навздогін усе одно знайшов рахунок",
             (late or {}).get("id"), other["id"])
        tx2 = "d" * 64
        seen.append(tx2)
        case("підписку ввімкнули й після скасування",
             crypto_pay._settle(late, tx2, "T" + "v" * 33), True)
        case("підписка в другого діє", billing.state(u2["id"])["active"], True)
        case("скасовувати вдруге нема чого", crypto_pay.cancel(u2["id"]), False)

        # Переказ, що не збігся ні з чим, не губимо.
        orphan = {"tx": "c" * 64, "from": "T" + "w" * 33,
                  "units": 999_000_000, "at": 1700000000000}
        seen.append(orphan["tx"])
        crypto_pay._orphan(orphan)
        case("незрозумілий переказ запам'ятали",
             crypto_pay._seen(orphan["tx"]), True)
        crypto_pay._orphan(orphan)     # вдруге — без падіння
        case("той самий переказ не задвоївся", _orphans(orphan["tx"]), 1)
    finally:
        with db.connect() as conn:
            for tx in seen:
                conn.execute("DELETE FROM crypto_orphans WHERE tx=%s", (tx,))
            for who in [uid] + ([u2["id"]] if u2 else []):
                conn.execute("DELETE FROM crypto_invoices WHERE user_id=%s", (who,))
                conn.execute("DELETE FROM users WHERE id=%s", (who,))
            conn.commit()
        print("  тимчасовий акаунт прибрано")


def _orphans(tx):
    with db.connect() as conn:
        return conn.execute("SELECT count(*) AS n FROM crypto_orphans WHERE tx=%s",
                            (tx,)).fetchone()["n"]


if __name__ == "__main__":
    print("оплата криптою")
    check_addresses()
    check_rows()
    if not config.DATABASE_URL:
        print("\nбази немає — шлях оплати не перевіряємо")
    else:
        db.init()
        check_flow()
    print("\n" + ("усе добре" if not BAD else "є помилки: " + ", ".join(BAD)))
    sys.exit(1 if BAD else 0)
