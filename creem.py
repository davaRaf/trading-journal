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
import urllib.parse
import urllib.request

from config import (CREEM_API, CREEM_API_KEY, CREEM_BT_PACK_PRODUCT,
                    CREEM_PRODUCTS, CREEM_RETURN, CREEM_WEBHOOK_SECRET)

UA = "StatsAI/1.0 (+https://statsai.xyz)"
TIMEOUT = 20


def enabled():
    """Чи можемо взагалі приймати оплату. Без ключа кнопка має чесно
    сказати «скоро», а не вести в нікуди."""
    return bool(CREEM_API_KEY)


def product(price_set, plan):
    """Товар на боці Creem під набір цін і тариф цієї людини."""
    return (CREEM_PRODUCTS.get(price_set or "std") or {}).get(plan, "")


def _say(ex):
    """Помилку від Creem — словами, а не «HTTP Error 400: Bad Request».

    У відмові завжди лежить тіло з причиною («немає такої знижки», «товар
    не той»), і без нього в логу стоїть голий код, за яким не зрозуміти
    нічого. Читаємо тіло один раз і чіпляємо до тексту: далі воно піде в
    лог поруч із запитом, який упав.
    """
    try:
        txt = ex.read().decode("utf-8", "replace")[:400]
    except Exception:
        txt = ""
    return "HTTP %s %s" % (ex.code, txt or ex.reason)


def _post(path, body):
    req = urllib.request.Request(
        CREEM_API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": CREEM_API_KEY,
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": UA},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:
        raise RuntimeError("POST %s: %s" % (path, _say(ex)))


def checkout(user_id, plan, price_set="std", email="", return_url="", discount=""):
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
    # промокод: знижку «once» рахує Creem — лише перший платіж
    if discount:
        body["discount_code"] = discount
        body["metadata"]["promo"] = discount
    res = _post("/v1/checkouts", body)
    url = res.get("checkout_url") or res.get("url")
    if not url:
        raise ValueError("Creem не повернув адресу каси: %s" % res)
    return url


# Як ми позначаємо разову докупку бектест-перенесень у metadata каси.
# Те саме слово читаємо назад з події (pack_of) — на ньому тримається
# розвилка у вебхуку, бо тип події в разової оплати той самий, що в першої
# оплати підписки.
PACK_BT = "bt_imports"


def pack_checkout(user_id, n, cents, email="", return_url=""):
    """Каса на разову докупку бектест-перенесень.

    Товар один на всі кількості, а ціну передаємо свою: custom_price — це
    ціна за одиницю, тож беремо units=1 і кладемо туди всю суму. Інакше під
    кожне з вісімнадцяти значень ползунка треба було б окремий товар.

    Суму рахує той, хто кличе (config.bt_pack_cents), і рахує з кількості —
    з браузера сюди ціна не доходить ніколи.
    """
    if not CREEM_BT_PACK_PRODUCT:
        raise ValueError("немає товару під докупку бектест-перенесень")
    n, cents = int(n), int(cents)
    if n <= 0 or cents <= 0:
        raise ValueError("кількість і сума мають бути додатні")
    body = {
        "product_id": CREEM_BT_PACK_PRODUCT,
        "units": 1,
        "custom_price": cents,
        # Номер має бути свій на кожну покупку: та сама людина докуповує не
        # один раз, а Creem по однаковому request_id віддає стару касу.
        "request_id": "u%s-%s%d-%d" % (user_id, PACK_BT, n,
                                       int(datetime.datetime.now().timestamp())),
        "success_url": return_url or CREEM_RETURN,
        "metadata": {"user_id": str(user_id), "kind": PACK_BT, "n": str(n)},
    }
    if email:
        body["customer"] = {"email": email}
    res = _post("/v1/checkouts", body)
    url = res.get("checkout_url") or res.get("url")
    if not url:
        raise ValueError("Creem не повернув адресу каси: %s" % res)
    return url


def pack_of(obj):
    """Скільки бектест-перенесень оплачено цією подією, або 0.

    Нуль означає «це не докупка» — і тоді подію розбирають як підписку.
    Розрізнити їх інакше не можна: разова оплата приходить тим самим
    checkout.completed, що й перша оплата підписки, і без цієї перевірки
    покупка за чотири євро видавала б місяць підписки.

    Шукаємо в тих самих місцях, що й who(): metadata лежить то в самому
    об'єкті, то в замовленні чи касі всередині нього.
    """
    for src in (obj, obj.get("order") or {}, obj.get("checkout") or {},
                obj.get("subscription") or {}):
        if not isinstance(src, dict):
            continue
        meta = src.get("metadata") or {}
        if (meta.get("kind") or "") != PACK_BT:
            continue
        try:
            n = int(meta.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n
    return 0


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
    try:
        return hmac.compare_digest(mine, str(signature).strip())
    except TypeError:
        # compare_digest не порівнює рядки з не-ASCII і кидає TypeError.
        # Підпис у Creem — шістнадцяткове число, тож усе інше їхнім бути
        # не може. Але точка відкрита всьому світу: заголовок з кирилицею
        # валив обробник трейсбеком і 502 замість чесних 400.
        return False


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


def customer_of(obj):
    """Номер людини на боці Creem — те, чим відкривається її кабінет.

    Лежить то рядком, то об'єктом з полем id, то на крок глибше — у
    підписці всередині події. Шукаємо в тих самих місцях, що й номер
    нашої людини, і першу знахідку віддаємо.
    """
    for src in (obj, obj.get("subscription") or {}, obj.get("order") or {},
                obj.get("checkout") or {}):
        if not isinstance(src, dict):
            continue
        cust = src.get("customer")
        if isinstance(cust, dict):
            cust = cust.get("id")
        cust = str(cust or "").strip()
        if cust:
            return cust
    return ""


def portal(customer_id):
    """Разове посилання в кабінет Creem: там людина сама скасує продовження
    чи змінить картку.

    Посилання одноразове й живе недовго, тому не зберігаємо його — беремо
    нове щоразу, коли натиснули кнопку.
    """
    cid = str(customer_id or "").strip()
    if not cid:
        raise ValueError("немає номера покупця")
    res = _post("/v1/customers/billing", {"customer_id": cid})
    url = res.get("customer_portal_link") or res.get("url") or ""
    if not url:
        raise RuntimeError("Creem не дав посилання на кабінет: %r" % (res,))
    return url


# ------------------------------------------------------- повернення з каси ----
# Після оплати Creem відправляє людину назад і додає до адреси свої
# опізнавачі й підпис. Порядок полів у підписі саме такий — вони
# склеюються через «|» у тому ж порядку, в якому Creem їх перелічує,
# а сіллю служить наш API-ключ. Міняти порядок не можна: підпис не зійдеться.
RETURN_KEYS = ("request_id", "checkout_id", "order_id", "customer_id",
               "subscription_id", "product_id")


def return_signature(params):
    """Порахувати підпис адреси повернення так, як його рахує Creem."""
    parts = ["%s=%s" % (k, params[k]) for k in RETURN_KEYS if params.get(k)]
    parts.append("salt=" + CREEM_API_KEY)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def verify_return(params):
    """Чи справді ця адреса від Creem.

    Підпис доводить одне: людину повернув Creem, а не хтось підставив
    адресу руками. Він **не** доводить, що гроші дійшли — платіж міг
    лишитись в обробці. Тому на самому підписі рішення не ухвалюємо:
    далі питаємо в Creem, що з підпискою насправді.
    """
    got = str(params.get("signature") or "")
    if not got or not CREEM_API_KEY:
        return False
    return hmac.compare_digest(got, return_signature(params))


def _get(path):
    req = urllib.request.Request(
        CREEM_API + path,
        headers={"x-api-key": CREEM_API_KEY,
                 "Accept": "application/json",
                 "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:
        raise RuntimeError("GET %s: %s" % (path, _say(ex)))


def subscription(sub_id):
    """Спитати Creem, що з підпискою зараз. Джерело правди — тут."""
    sid = str(sub_id or "").strip()
    if not sid:
        raise ValueError("немає номера підписки")
    return _get("/v1/subscriptions?subscription_id=" + urllib.parse.quote(sid))


# Стани, за яких підписка справді працює. Решта — очікування, борг або
# кінець; вмикати за ними не можна.
LIVE_STATUSES = ("active", "trialing")
