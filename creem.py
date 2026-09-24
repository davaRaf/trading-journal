# -*- coding: utf-8 -*-
"""Розмова з Creem: створити касу й перевірити підпис вебхука.

Creem у нас merchant of record — продавцем перед покупцем виступає він.
Тому гроші, податок, рахунок і суперечки з банком на його боці, а нам
лишається дві речі: відправити людину на касу з потрібним товаром і
повірити тому, що він потім про цю оплату розкаже.

Найважливіше тут — **номер людини поруч з оплатою**. Creem повертає його
в повідомленні, і тільки завдяки цьому ми знаємо, кому вмикати підписку.
Без нього ми б знали, що хтось заплатив, але не знали б хто.

Перед їхнім API стоїть Cloudflare і відбиває стандартний клієнт Python
кодом 1010 («забанено за підписом браузера»), тому свій User-Agent тут
обов'язковий, а не для краси.
"""
import datetime
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from config import (CREEM_API, CREEM_API_KEY, CREEM_PRODUCTS, CREEM_RETURN,
                    CREEM_WEBHOOK_SECRET)

UA = "StatsAI/1.0 (+https://statsai.xyz)"
TIMEOUT = 20


def enabled():
    """Чи можемо взагалі приймати оплату. Без ключа кнопка має чесно
    сказати «скоро», а не вести в нікуди."""
    return bool(CREEM_API_KEY)


def product(price_set, plan):
    """Товар на боці Creem під набір цін і тариф цієї людини."""
    return (CREEM_PRODUCTS.get(price_set or "std") or {}).get(plan, "")


def _post(path, body):
    req = urllib.request.Request(
        CREEM_API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": CREEM_API_KEY,
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": UA},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def checkout(user_id, plan, price_set="std", email="", return_url=""):
    """Створити касу. Повертає адресу, куди відправити людину.

    request_id і metadata дублюють одне й те саме навмисно: перший
    приходить у відповіді на оплату, друга — в подіях про продовження.
    Нам треба впізнати людину і там, і там.
    """
    pid = product(price_set, plan)
    if not pid:
        raise ValueError("немає товару для %s/%s" % (price_set, plan))
    body = {
        "product_id": pid,
        "request_id": "u%s-%s" % (user_id, plan),
        "success_url": return_url or CREEM_RETURN,
        "metadata": {"user_id": str(user_id), "plan": plan,
                     "price_set": price_set},
    }
    if email:
        body["customer"] = {"email": email}
    res = _post("/v1/checkouts", body)
    url = res.get("checkout_url") or res.get("url")
    if not url:
        raise ValueError("Creem не повернув адресу каси: %s" % res)
    return url


def verify(raw_body, signature):
    """Чи справді це лист від Creem, а не від того, хто вгадав адресу.

    Рахуємо HMAC-SHA256 від сирого тіла на нашому секреті й порівнюємо.
    Порівняння обов'язково стійке до часу: звичайне '==' відповідає тим
    швидше, чим більше збіглося з початку, і цим можна підібрати підпис
    по одному символу.

    Без секрета не пускаємо нікого: краще не прийняти справжню оплату й
    розібрати її руками, ніж увімкнути підписку комусь за так.
    """
    if not CREEM_WEBHOOK_SECRET or not signature:
        return False
    mine = hmac.new(CREEM_WEBHOOK_SECRET.encode("utf-8"),
                    raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mine, str(signature).strip())


def who(obj):
    """Витягти номер нашої людини з того, що прислав Creem.

    Creem кладе metadata то в сам об'єкт, то в підписку всередині нього —
    залежить від події. Тому шукаємо в обох місцях, а не сподіваємось на
    одне.
    """
    for src in (obj, obj.get("subscription") or {}, obj.get("order") or {},
                obj.get("checkout") or {}):
        if not isinstance(src, dict):
            continue
        meta = src.get("metadata") or {}
        uid = meta.get("user_id")
        if uid:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass
        # Запасний шлях: request_id виду «u42-year».
        rid = str(src.get("request_id") or "")
        if rid.startswith("u") and "-" in rid:
            try:
                return int(rid[1:].split("-", 1)[0])
            except ValueError:
                pass
    return None


def plan_of(obj):
    """Який тариф оплачено. Спершу з metadata, далі — за строком товару."""
    for src in (obj, obj.get("subscription") or {}):
        if not isinstance(src, dict):
            continue
        meta = src.get("metadata") or {}
        if meta.get("plan") in ("month", "quarter", "year"):
            return meta["plan"]
    prod = (obj.get("product") or (obj.get("subscription") or {}).get("product")
            or {})
    by_period = {"every-month": "month", "every-three-months": "quarter",
                 "every-year": "year"}
    return by_period.get(prod.get("billing_period") or "", "")


# Як Creem називає дату кінця оплаченого періоду. Полів кілька, бо в
# різних подіях приходить різне; беремо перше, що знайшли.
END_KEYS = ("current_period_end_date", "current_period_end",
            "next_transaction_date", "expires_at")


def period_end(obj):
    """До якого числа оплачено, за словами платіжки. None — не сказали.

    Саме ця дата йде в базу: списувати Creem буде за календарем, а не
    нашими тридцятьма днями, і розходження накопичувалось би.
    """
    for src in (obj, obj.get("subscription") or {}):
        if not isinstance(src, dict):
            continue
        for k in END_KEYS:
            raw = src.get(k)
            if not raw:
                continue
            try:
                txt = str(raw).replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(txt)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
    return None
