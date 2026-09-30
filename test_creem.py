# -*- coding: utf-8 -*-
"""Підтвердження оплати від Creem: чи правильно ми на нього реагуємо.

Creem до localhost не достукається, тому підписуємо й шлемо повідомлення
самі — рівно так, як це робить він: HMAC-SHA256 від сирого тіла на секреті,
підпис у заголовку creem-signature.

Перевіряємо не «чи прийшло», а те, на чому такі речі ламаються:
підроблений підпис, повторна доставка тієї самої події, відмова від
продовження (оплачені дні мають дожити) і повернення грошей.

Сервер має бути піднятий на 8173 із CREEM_WEBHOOK_SECRET=local-test-secret.
"""
import datetime
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request

import auth
import db

HOST = "http://127.0.0.1:8173"
SECRET = "local-test-secret"

bad = 0


def check(name, cond, extra=""):
    global bad
    if not cond:
        bad += 1
    print("  %-6s %s%s" % ("ok" if cond else "ПАДАЄ", name,
                           ("  -> " + str(extra)) if extra else ""))


def post(path, body, sign=True, secret=None):
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new((secret or SECRET).encode(), raw, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["creem-signature"] = sig
    req = urllib.request.Request(HOST + path, data=raw, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8", "replace")[:120]


def event(ev, uid, plan="year", end=None, eid=None):
    """Повідомлення в тому вигляді, в якому його шле Creem."""
    end = end or (db.now() + datetime.timedelta(days=365))
    return {
        "id": eid or ("evt_" + ev + "_" + str(uid)),
        "eventType": ev,
        "object": {
            "id": "sub_test",
            "metadata": {"user_id": str(uid), "plan": plan, "price_set": "std"},
            "current_period_end_date": end.isoformat(),
            "amount": 9999, "currency": "EUR",
            "customer": {"id": "cust_test_%d" % uid},
        },
    }


def state(uid):
    tok = auth.make_session(uid, gen=db.get_user(uid)["session_gen"])
    req = urllib.request.Request(HOST + "/api/billing/state",
                                 headers={"Cookie": "%s=%s" % (auth.COOKIE, tok)})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def as_user(path, uid, method="POST"):
    """Запит від імені людини — з її пічкою, як із браузера."""
    tok = auth.make_session(uid, gen=db.get_user(uid)["session_gen"])
    req = urllib.request.Request(
        HOST + path, data=b"{}", method=method,
        headers={"Cookie": "%s=%s" % (auth.COOKIE, tok),
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", "replace")
        try:
            return ex.code, json.loads(body)
        except ValueError:
            return ex.code, body[:120]


def main():
    email = "creem-test-%d@example.com" % int(db.now().timestamp())
    uid = db.create_user(email, email.split("@")[0], "x", "y", 1)["id"]
    print("тимчасовий акаунт:", uid)
    print()

    try:
        print("підпис")
        code, _ = post("/api/creem/webhook", event("subscription.active", uid),
                       sign=False)
        check("без підпису не пускаємо", code == 400, code)
        code, _ = post("/api/creem/webhook", event("subscription.active", uid),
                       secret="wrong-secret")
        check("чужий підпис не пускаємо", code == 400, code)
        check("підписка досі не ввімкнена", not state(uid)["active"])

        print("\nкабінет підписки до оплати")
        check("кнопки немає", not state(uid).get("portal"))
        code, res = as_user("/api/billing/portal", uid)
        check("кабінет не відкривається — платежів не було", code == 404, code)
        check("сказали чому", isinstance(res, dict)
              and res.get("code") == "no_customer", res)
        req = urllib.request.Request(HOST + "/api/billing/portal", data=b"{}",
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=15)
            check("без входу не пускаємо", False, "пустило")
        except urllib.error.HTTPError as ex:
            check("без входу не пускаємо", ex.code == 401, ex.code)

        print("\nоплата")
        # людина ввела промокод до оплати — після оплати він має згоріти
        import billing
        check("промокод прийнято до оплати", billing.redeem(uid, "FXLAB") == (True, ""))
        end = db.now() + datetime.timedelta(days=365)
        code, res = post("/api/creem/webhook",
                         event("subscription.active", uid, "year", end))
        st = state(uid)
        check("прийняли", code == 200, code)
        check("тариф річний", st["plan"] == "year", st["plan"])
        check("підписка активна", st["active"])
        check("дата взята з платіжки, а не порахована нами",
              st["paid_until"][:10] == end.date().isoformat(),
              st["paid_until"][:10])
        check("після оплати промокод використано",
              bool(db.get_user(uid).get("promo_used_at")))
        check("вдруге не приймається", billing.redeem(uid, "FXLAB")[1] == "promo_used")

        print("\nповторна доставка")
        code, res = post("/api/creem/webhook",
                         event("subscription.active", uid, "year", end))
        check("сказали, що вже бачили", isinstance(res, dict) and res.get("repeat"),
              res)
        check("дата не змінилась", state(uid)["paid_until"][:10] == end.date().isoformat())

        print("\nвідмова від продовження")
        post("/api/creem/webhook",
             event("subscription.canceled", uid, "year", end, eid="evt_cancel"))
        st = state(uid)
        check("оплачені дні на місці", st["active"], st["paid_until"])
        check("тариф не зник", st["plan"] == "year", st["plan"])

        print("\nпродовження на новий строк")
        end2 = end + datetime.timedelta(days=365)
        post("/api/creem/webhook",
             event("subscription.paid", uid, "year", end2, eid="evt_paid_2"))
        check("дата посунулась уперед",
              state(uid)["paid_until"][:10] == end2.date().isoformat(),
              state(uid)["paid_until"][:10])

        print("\nповернення грошей")
        post("/api/creem/webhook",
             event("refund.created", uid, "year", end2, eid="evt_refund"))
        st = state(uid)
        check("підписку знято", not st["active"], st["paid_until"])
        check("тариф вільний", st["plan"] == "free", st["plan"])

        print("\nкабінет підписки після оплати")
        want = "cust_test_%d" % uid
        check("номер покупця збережено",
              (db.get_user(uid) or {}).get("creem_customer") == want,
              (db.get_user(uid) or {}).get("creem_customer"))
        check("кнопка з'явилась", state(uid).get("portal") is True)
        code, res = as_user("/api/billing/portal", uid)
        # Номер вигаданий, тому Creem його не впізнає — важливо, що ми
        # доходимо до нього й віддаємо зрозумілу відмову, а не падаємо.
        check("до платіжки достукались", code in (200, 502), code)
        if code == 502:
            check("відмову переклали по-людськи", isinstance(res, dict)
                  and res.get("code") == "portal_failed", res)

        print("\nчужа людина")
        body = event("subscription.active", 10 ** 9, "year", end, eid="evt_nobody")
        body["object"]["metadata"] = {}
        body["object"]["request_id"] = ""
        code, res = post("/api/creem/webhook", body)
        check("відповіли згодою, щоб не повторював", code == 200, code)
        check("позначили, що людину не впізнали",
              isinstance(res, dict) and res.get("unknown_user"), res)
    finally:
        with db.connect() as c:
            c.execute("DELETE FROM payments WHERE user_id=%s OR id LIKE 'evt_%%'",
                      (uid,))
            c.execute("DELETE FROM users WHERE id=%s", (uid,))
            c.commit()
        print("\nтимчасовий акаунт прибрано")

    print("\n" + ("ЄСТЬ ПАДІННЯ: %d" % bad if bad else "усе сходиться"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
