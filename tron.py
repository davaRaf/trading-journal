# -*- coding: utf-8 -*-
"""Читання переказів USDT у мережі TRON.

Тут немає ані ключів від гаманця, ані підписів, ані відправлення грошей —
тільки читання. Блокчейн відкритий: перекази на будь-яку адресу видно
всім, і щоб побачити свої, володіти нею не треба. Саме тому оплата
криптою не вимагає від нас тримати на сервері ключі: вкрасти звідси
нічого, навіть якщо сайт зламають.

Чому TRON, а не мережа під MetaMask: для USDT це найпоширеніша мережа —
її віддає й приймає будь-яка біржа, тож людина платить звідки завгодно
без обмінів (рішення власника 29.09.2026).

Що робить модуль: питає в TronGrid список переказів USDT **на нашу
адресу** й віддає їх звичайними числами. Зіставляння з рахунками — не
тут, а в crypto.py: цей модуль нічого не знає про підписки.
"""
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from config import (TRON_API, TRON_KEY, TRON_WALLET, USDT_CONTRACT,
                    USDT_DECIMALS)

TIMEOUT = 20
UA = "StatsAI/1.0 (+https://statsai.xyz)"
# За раз беремо стільки переказів. Більше ні до чого: опитуємо часто, і
# за півхвилини сотня оплат на одну адресу — це не наш масштаб.
PAGE = 50

# ------------------------------------------------------------- адреси ----
# TRON показує адресу двома способами. Людині — base58 з великої «T»
# (TGtTx…), а всередині подій контракту — ті самі двадцять байтів у hex
# (0x30760c…). Це одна адреса, просто записана по-різному, тож порівнювати
# їх «як рядки» не можна: саме тут і губляться оплати.
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PREFIX = 0x41          # усі адреси TRON починаються з цього байта


def _b58decode(s):
    n = 0
    for ch in s:
        if ch not in B58:
            raise ValueError("не адреса TRON: %r" % ch)
        n = n * 58 + B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def _b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + out


def valid(addr):
    """Чи це справді адреса TRON — з перевіркою контрольної суми.

    Одна переплутана літера в адресі означає гроші, надіслані в нікуди й
    назавжди. Тому адресу гаманця звіряємо на старті, а не сподіваємось,
    що її набрали без помилок.
    """
    try:
        raw = _b58decode((addr or "").strip())
    except ValueError:
        return False
    if len(raw) != 25 or raw[0] != PREFIX:
        return False
    body, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] == checksum


def to_hex(addr):
    """base58 → двадцять байтів hex, як їх пише контракт USDT."""
    return _b58decode((addr or "").strip())[1:21].hex()


def from_hex(hex_addr):
    """hex із події → звична адреса з «T». Порожнє лишається порожнім."""
    h = (hex_addr or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if h.startswith("41") and len(h) == 42:
        h = h[2:]
    if len(h) != 40:
        return ""
    try:
        body = bytes([PREFIX]) + bytes.fromhex(h)
    except ValueError:
        return ""
    return _b58encode(body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4])


def enabled():
    """Чи можемо приймати крипту взагалі. Без адреси гаманця кнопка має
    чесно мовчати, а не вести людину в нікуди."""
    return bool(TRON_WALLET)


def _get(path, params):
    url = TRON_API.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "User-Agent": UA}
    # Ключ не обов'язковий: без нього TronGrid теж відповідає, просто
    # скупіше за лімітами. Тому вимикати оплату через його брак не будемо.
    if TRON_KEY:
        headers["TRON-PRO-API-KEY"] = TRON_KEY
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _units(raw):
    """Сума з відповіді — ціле число найдрібніших часток. У USDT їх
    мільйон на монету, і рахуємо ми теж у них: у цілих немає копійчаних
    похибок, через які «11,99» раптом не дорівнює «11,99»."""
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 0


def to_usdt(units):
    """Частки → сума для людини. Показуємо рівно шість знаків без округлень."""
    return units / float(10 ** USDT_DECIMALS)


def to_units(usdt):
    """Сума для людини → частки. Округляємо, бо float не зобов'язаний дати
    рівне число: 11.9943 * 1e6 у ньому цілком може бути 11994299.9997."""
    return int(round(float(usdt) * (10 ** USDT_DECIMALS)))


def _rows(data):
    """Залишити з відповіді тільки справжні прибуткові перекази USDT.

    Перевіряємо все, що приїхало: і монету, і напрямок. Відповідь чужа, і
    покладатись на те, що фільтри запиту спрацювали, не можна — інакше
    підписку відкрив би переказ будь-якого сміттєвого токена, якого до
    нашої адреси надіслали навмисно.
    """
    out = []
    for r in data.get("data") or []:
        if not isinstance(r, dict):
            continue
        if (r.get("type") or "") != "Transfer":
            continue
        info = r.get("token_info") or {}
        if (info.get("address") or "") != USDT_CONTRACT:
            continue
        if (r.get("to") or "") != TRON_WALLET:
            continue
        units = _units(r.get("value"))
        if units <= 0:
            continue
        out.append({
            "tx": str(r.get("transaction_id") or ""),
            "from": str(r.get("from") or ""),
            "units": units,
            "at": int(r.get("block_timestamp") or 0),   # мілісекунди
        })
    return out


def incoming(since_ms=0):
    """Перекази USDT, що прийшли до нас після вказаної миті.

    since_ms — час у мілісекундах, як його віддає сам TronGrid. Нуль
    означає «останню сторінку, скільки дасте»: так ми добираємо оплати,
    що прийшли, поки сервер був вимкнений.
    """
    if not enabled():
        return []
    params = {"only_to": "true", "contract_address": USDT_CONTRACT,
              "limit": PAGE, "order_by": "block_timestamp,desc"}
    if since_ms:
        params["min_timestamp"] = int(since_ms)
    try:
        data = _get("/v1/accounts/%s/transactions/trc20" % TRON_WALLET, params)
    except (urllib.error.URLError, OSError, ValueError) as ex:
        # Не відповіли — не біда: переказ нікуди з блокчейну не подінеться,
        # спитаємо наступного разу. Гірше було б вважати, що оплат немає.
        print("tron: не спитали перекази:", ex, flush=True)
        return None
    return _rows(data)


def by_hash(txid):
    """Один переказ за його номером — для «я оплатив, ось номер».

    Той самий список, але звужений до однієї угоди: TronGrid не дає
    зручного запиту «покажи цей переказ токена», тому беремо свіжі й
    шукаємо потрібний серед них.
    """
    txid = (txid or "").strip().lower()
    if not enabled() or not txid:
        return None
    try:
        data = _get("/v1/transactions/%s/events" % urllib.parse.quote(txid), {})
    except (urllib.error.URLError, OSError, ValueError) as ex:
        print("tron: не спитали переказ %s: %s" % (txid[:16], ex), flush=True)
        return None
    mine = to_hex(TRON_WALLET)
    for ev in data.get("data") or []:
        if not isinstance(ev, dict):
            continue
        if (ev.get("event_name") or "") != "Transfer":
            continue
        if (ev.get("contract_address") or "") != USDT_CONTRACT:
            continue
        res = ev.get("result") or {}
        # Адреси тут у hex, а наша — у base58: зводимо до одного вигляду,
        # інакше жоден переказ ніколи не збігся б із нашою адресою.
        to = str(res.get("to") or res.get("1") or "").lower().lstrip("0x")
        if to.startswith("41") and len(to) == 42:
            to = to[2:]
        if to != mine:
            continue
        return {"tx": txid,
                "from": from_hex(str(res.get("from") or res.get("0") or "")),
                "units": _units(res.get("value") or res.get("2")),
                "at": int(ev.get("block_timestamp") or 0)}
    return None
