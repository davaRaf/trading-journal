# -*- coding: utf-8 -*-
"""
Генератор демо-сделок для публичного демо (static/demo-data.json).

Это ВЫМЫШЛЕННЫЕ сделки. Реальный журнал никогда не попадает в репозиторий —
демо нужно только чтобы человек, открывший ссылку, сразу увидел живой интерфейс.

Запуск:  python tools/make_demo_data.py
"""
import json, os, random, datetime

random.seed(20260830)  # фиксированное зерно: одинаковый результат при каждом запуске

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "static", "demo-data.json")

START = datetime.date(2025, 11, 3)
END   = datetime.date(2026, 8, 21)
COUNT = 150

PAIRS    = [("US100", 45), ("GER40", 40), ("EUR/USD", 10), ("ES500", 5)]
SESSIONS = [("LONDON", 62), ("NY", 25), ("FRANKFURT", 10), ("PH", 3)]
MODELS   = [("cisd", 50), ("bos", 26), ("inversion", 22), ("limit", 2)]
SETUPS   = [("(us100) 1h/15m/1m", 40), ("default 1H3/5m", 22), ("1h,4h imb(rti)", 18),
            ("swing", 12), ("Frank manipulation", 8)]
RISKS    = [(1.0, 88), (0.5, 7), (1.5, 5)]

SESSION_HOURS = {"FRANKFURT": (8, 9), "LONDON": (9, 13), "NY": (14, 18), "PH": (12, 14)}

DETAILS = [
    "тест 1ч имбаланса, вход по 1м cisd, цель — 15м фрактал",
    "снятие азиатского хая, возврат в диапазон, вход после смены характера",
    "работа от 4ч зоны, подтверждение на 5м",
    "продолжение после лондонской манипуляции, цель — предыдущий экстремум",
    "вход на ретесте пробитого уровня, стоп за структуру",
    "закрытие гэпа открытия, цель — середина диапазона",
]
NOTES = [
    "", "", "", "план отработал",
    "вход по чек-листу, без спешки",
    "сессия тонкая, объёмов мало",
    "новостей в окне не было",
]
MISTAKES = [
    "", "", "", "", "", "-",
    "рано перенёс в безубыток",
    "вошёл без подтверждения на младшем",
    "не дождался закрытия свечи",
    "торговал вне своей сессии",
    "увеличил риск после серии стопов",
]

def pick(weighted):
    total = sum(w for _, w in weighted)
    x = random.uniform(0, total)
    acc = 0
    for value, w in weighted:
        acc += w
        if x <= acc:
            return value
    return weighted[-1][0]

def business_days(a, b):
    days, d = [], a
    while d <= b:
        if d.weekday() < 5:
            days.append(d)
        d += datetime.timedelta(days=1)
    return days

# Смысл демо: показать главный вывод журнала — входы против собственного биаса
# стабильно хуже входов по биасу. Поэтому исходы задаются раздельно.
OUTCOME_CONT = [("Win", 38), ("Loss", 41), ("BE-", 17), ("BE+", 4)]
OUTCOME_REV  = [("Win", 17), ("Loss", 64), ("BE-", 15), ("BE+", 4)]

def build():
    days = business_days(START, END)
    chosen = sorted(random.sample(days, COUNT) if COUNT <= len(days)
                    else [random.choice(days) for _ in range(COUNT)])
    trades, tid = [], 1788000000000
    for day in chosen:
        session = pick(SESSIONS)
        h0, h1 = SESSION_HOURS[session]
        when = "%sT%02d:%02d" % (day.isoformat(), random.randint(h0, h1), random.randint(0, 59))

        bias = random.choice(["Long", "Short"])
        reversal = random.random() < 0.13
        position = ("Short" if bias == "Long" else "Long") if reversal else bias

        result = pick(OUTCOME_REV if reversal else OUTCOME_CONT)
        rr = round(random.uniform(1.4, 2.6), 1) if result == "Win" else round(random.uniform(1.2, 2.8), 1)

        tid += random.randint(1000, 90000)
        trades.append({
            "id": "d" + str(tid),
            "pair": pick(PAIRS),
            "date": when,
            "session": session,
            "position": position,
            "bias": bias,
            "direction_type": "Reversal" if reversal else "Continuation",
            "entry_model": pick(MODELS),
            "setup": pick(SETUPS),
            "result": result,
            "rr": rr,
            "risk": pick(RISKS),
            "entry_details": random.choice(DETAILS),
            "notes": random.choice(NOTES),
            "mistakes": random.choice(MISTAKES) if result == "Loss" else random.choice(["", "", "-"]),
            "comments": "",
            "screenshots": [],
        })
    return trades

def net(t):
    if t["result"] == "Win":  return t["risk"] * t["rr"]
    if t["result"] == "Loss": return -t["risk"]
    return 0.0

if __name__ == "__main__":
    trades = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=1)

    total = sum(net(t) for t in trades)
    wins  = sum(1 for t in trades if t["result"] == "Win")
    loss  = sum(1 for t in trades if t["result"] == "Loss")
    cont  = [t for t in trades if t["direction_type"] == "Continuation"]
    rev   = [t for t in trades if t["direction_type"] == "Reversal"]
    print("Записано %d сделок -> %s" % (len(trades), OUT))
    print("Итог: %+.1f%%   winrate %.1f%%   TP/SL/BE %d/%d/%d"
          % (total, 100.0 * wins / (wins + loss), wins, loss, len(trades) - wins - loss))
    print("Continuation: %d сделок, %+.1f%%" % (len(cont), sum(net(t) for t in cont)))
    print("Reversal:     %d сделок, %+.1f%%" % (len(rev), sum(net(t) for t in rev)))
