# -*- coding: utf-8 -*-
"""Завести тарифи в Creem — без тридцяти кліків і без описок.

Шість товарів: три звичайні й три зі зниженою ціною. Назви в парах
однакові навмисно — їх бачить покупець на касі й у чеку, і людині зі
знижкою нема чого читати «для старих». У кабінеті вони різняться сумою.

Ціни беремо з config.PRICES, а не вписуємо сюди: інакше одного дня ми
змінимо їх у журналі й забудемо змінити в платіжці, а людина побачить на
картці одну суму, а на касі іншу.

Податок — inclusive: у Євросоюзі ціна для звичайної людини має показуватись
одразу з податком, і на сайті в нас написано саме кінцеву суму.

Спершу прогін без записів — показує, що саме піде на той бік:

    py -3 creem_setup.py                # тестовий режим, тільки показати
    py -3 creem_setup.py --go           # тестовий режим, створити
    py -3 creem_setup.py --live --go    # бойовий режим, створити

Ключ береться з .env (CREEM_API_KEY). Для тестового й бойового режимів
ключі різні, тому перед --live його треба замінити.
"""
import json
import sys
import urllib.error
import urllib.request

from config import CURRENCY, PRICES

TEST_API = "https://test-api.creem.io"
LIVE_API = "https://api.creem.io"

# Наші назви строків → їхні. Квартал у них зветься «кожні три місяці».
PERIOD = {"month": "every-month", "quarter": "every-three-months",
          "year": "every-year"}
TITLE = {"month": "місяць", "quarter": "квартал", "year": "рік"}
# Як часто списують — єдине, чим описи різняться між собою. Суму в опис
# не пишемо: вона й так на касі, а продублювавши, ми одного дня змінимо
# ціну й забудемо поправити текст.
WHEN = {"month": "щомісяця", "quarter": "раз на три місяці", "year": "раз на рік"}

DESC = ("Підписка на журнал угод StatsAI. Угоди й бектест без обмежень, "
        "перенесення з Notion і щоденна синхронізація, помічник без "
        "місячної порції. Поновлюється %s, скасувати можна будь-коли.")

# Куди повертати після оплати. На товарі це не задається — Creem приймає
# адресу при створенні каси, і так навіть краще: на локальній перевірці
# повертати треба на localhost, а не на бойовий сайт.
RETURN_URL = "https://statsai.xyz/?paid=1"


def products():
    """Шість товарів у тому порядку, в якому їх зручно читати в кабінеті."""
    out = []
    for kind in ("std", "early"):
        for plan in ("month", "quarter", "year"):
            out.append({
                "kind": kind, "plan": plan,
                "body": {
                    "name": "StatsAI — " + TITLE[plan],
                    "description": DESC % WHEN[plan],
                    "price": PRICES[kind][plan],
                    "currency": CURRENCY,
                    "billing_type": "recurring",
                    "billing_period": PERIOD[plan],
                    "tax_mode": "inclusive",
                    "tax_category": "saas",
                },
            })
    return out


def create(base, key, body):
    req = urllib.request.Request(
        base + "/v1/products",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": key,
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 # Без свого User-Agent Cloudflare перед їхнім API віддає
                 # 403 з кодом 1010 — «забанено за підписом браузера».
                 # Стандартний рядок urllib він вважає ботом.
                 "User-Agent": "StatsAI-setup/1.0 (+https://statsai.xyz)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    live = "--live" in sys.argv
    go = "--go" in sys.argv
    base = LIVE_API if live else TEST_API

    import os
    key = os.environ.get("CREEM_API_KEY", "").strip()

    print("режим:   %s" % ("БОЙОВИЙ" if live else "тестовий"))
    print("адреса:  %s" % base)
    print("ключ:    %s" % ("є, %d символів" % len(key) if key else "НЕМАЄ"))
    print()

    items = products()
    print("%-22s %9s  %-20s %s" % ("назва", "ціна", "період", "набір"))
    print("-" * 72)
    for it in items:
        b = it["body"]
        print("%-22s %6.2f %s  %-20s %s" % (
            b["name"], b["price"] / 100, b["currency"],
            b["billing_period"], it["kind"]))
    print()
    print("податок: %s | категорія: %s" % (items[0]["body"]["tax_mode"],
                                           items[0]["body"]["tax_category"]))
    print("повернення після оплати задається при оплаті: %s" % RETURN_URL)
    print()

    if not go:
        print("Це був показ без записів. Щоб створити — додай --go")
        return
    if not key:
        print("Ключа немає: впиши CREEM_API_KEY у .env")
        return

    print("створюю...\n")
    ids = {}
    for it in items:
        b = it["body"]
        try:
            res = create(base, key, b)
        except urllib.error.HTTPError as ex:
            print("  ПОМИЛКА %s — %s %.2f: %s" % (
                ex.code, b["name"], b["price"] / 100,
                ex.read().decode("utf-8", "replace")[:300]))
            continue
        except Exception as ex:
            print("  ПОМИЛКА — %s: %s" % (b["name"], ex))
            continue
        pid = res.get("id") or res.get("product_id") or "?"
        ids["%s_%s" % (it["kind"], it["plan"])] = pid
        print("  ok  %-22s %6.2f  %s" % (b["name"], b["price"] / 100, pid))

    if ids:
        print("\nдодай у .env:")
        for k in sorted(ids):
            print("CREEM_PRODUCT_%s=%s" % (k.upper(), ids[k]))


if __name__ == "__main__":
    main()
