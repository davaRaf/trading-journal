# -*- coding: utf-8 -*-
"""
Попереднє скачування історії для «Перемотки».

Навіщо. Свічки довантажуються самі, коли людина відкриває прогін, але
перший раз це помітно: незакешований місяць — це два десятки походів у
мережу. Щоб перемотка відкривалась одразу, історію качають наперед —
краще вночі й одним заходом.

Як користуватись:

    # усе, що є, з 2015 року (довго: рахуйте годинами)
    python tools/warm_candles.py --from 2015-01-01

    # тільки те, чим торгують щодня
    python tools/warm_candles.py --from 2015-01-01 --symbols GER40,XAUUSD,EURUSD,US100

    # крипта з біржі
    python tools/warm_candles.py --from 2017-09-01 --symbols BTCUSD,ETHUSD

    # подивитись обсяг, нічого не качаючи
    python tools/warm_candles.py --from 2015-01-01 --plan

Скачане лягає в `data/candles` і не протухає, тож перерваний скрипт можна
запускати скільки завгодно разів: він пропускає те, що вже є. На сервері
зручно пускати через `nohup … &` і дивитись у файл журналу.

Джерела не люблять поспіху й відповідають 503. Скрипт це переживає (пауза
й повтори всередині `candles.py`), але швидше від цього не стає: рахуйте
приблизно півсекунди на день історії одного інструмента.
"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import candles  # noqa: E402


def parse_day(s):
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("дата у вигляді РРРР-ММ-ДД, а не %r" % s)


def human(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return "%d с" % seconds
    if seconds < 5400:
        return "%d хв" % round(seconds / 60)
    return "%.1f год" % (seconds / 3600.0)


def check(names, source):
    """Чи живий код кожного інструмента. Коди в джерел свої й нікому не
    обіцяні: індекси там звуться на кшталт `DEUIDXEUR`, і помилка в літері
    дає тихо порожній графік. Тому качаємо по одному буденному дню на
    інструмент і дивимось, чи прийшли свічки.

    Перевіряємо кілька дат підряд: джерело іноді просто не відповідає, і
    один невдалий день ще не означає, що коду не існує."""
    probe_days = [datetime.date(2025, 6, 11), datetime.date(2024, 9, 11),
                  datetime.date(2023, 3, 8)]
    dead, quiet, ok = [], [], 0
    for i, name in enumerate(names, 1):
        src = candles.pick_source(name, source)
        got, why = 0, ""
        for d in probe_days:
            try:
                got = len(candles.minutes(name, d, src))
            except candles.FeedError as ex:
                why = str(ex)
                continue
            why = ""
            if got:
                break
        mark = "так" if got else ("джерело мовчить" if why else "ПОРОЖНЬО")
        print("[%d/%d] %-8s %-10s %-9s %s"
              % (i, len(names), name, src, mark, "хвилин %d" % got if got else ""),
              flush=True)
        if got:
            ok += 1
        elif why:
            quiet.append(name)
        else:
            dead.append(name)

    print("\nЖивих: %d з %d" % (ok, len(names)))
    if quiet:
        print("Не відповіли (мережа, спробуйте ще раз): %s" % ", ".join(quiet))
    if dead:
        print("Порожні — схоже, код не той, приберіть або виправте в candles.py: %s"
              % ", ".join(dead))
    return 1 if dead else 0


def main():
    ap = argparse.ArgumentParser(description="Качає історію свічок наперед")
    ap.add_argument("--from", dest="since", type=parse_day, required=True,
                    help="з якої дати (РРРР-ММ-ДД)")
    ap.add_argument("--to", dest="until", type=parse_day,
                    default=datetime.date.today() - datetime.timedelta(days=1),
                    help="до якої дати; за замовчуванням учора")
    ap.add_argument("--symbols", default="",
                    help="через кому; порожньо — усі, які знає candles.py")
    ap.add_argument("--source", default="",
                    help="чиїми цінами; порожньо — те, що в інструмента перше")
    ap.add_argument("--plan", action="store_true",
                    help="лише порахувати обсяг роботи")
    ap.add_argument("--check", action="store_true",
                    help="перевірити коди інструментів: по одному дню на кожен")
    a = ap.parse_args()

    if a.source:
        if a.source not in candles.SOURCES:
            print("не знаю такого джерела: %s" % a.source)
            print("є: %s" % ", ".join(candles.SOURCES))
            return 1
        if not candles.source_ready(a.source):
            # Мовчки взяти інше джерело було б найгірше: людина просила
            # саме ці ціни й думала б, що їх і качає.
            print("джерело %s не налаштоване — потрібен ключ у .env "
                  "(для oanda це OANDA_TOKEN)" % a.source)
            return 1

    want = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    for s in want:
        if not candles.known(s):
            print("не знаю такого інструмента: %s" % s)
            print("є: %s" % ", ".join(sorted(candles.SYMBOLS)))
            return 1
    names = want or sorted(candles.SYMBOLS)
    if a.source:
        names = [n for n in names if candles.known(n, a.source)]
        if not names:
            print("жоден інструмент не має джерела %r" % a.source)
            return 1

    if a.check:
        return check(names, a.source or None)

    days = (a.until - a.since).days + 1
    if days <= 0:
        print("кінець раніше за початок")
        return 1

    print("Інструментів: %d, днів у кожного: %d" % (len(names), days))
    print("Разом днів: %d, це приблизно %s"
          % (len(names) * days, human(len(names) * days * 0.5)))
    if a.plan:
        for n in names:
            src = candles.pick_source(n, a.source or None)
            print("  %-8s %-10s уже на диску: %d" % (n, src, candles.cached_days(n, src)))
        return 0

    started = time.time()
    total = {"got": 0, "empty": 0, "bad": 0}
    for i, name in enumerate(names, 1):
        src = candles.pick_source(name, a.source or None)
        t0 = time.time()
        got, empty, bad = candles.warm(
            name, a.since, a.until, src,
            log=lambda msg: print("    %s" % msg, flush=True))
        total["got"] += got
        total["empty"] += empty
        total["bad"] += bad
        print("[%d/%d] %-8s %-10s скачано %d, без торгів %d, не вийшло %d — %s"
              % (i, len(names), name, src, got, empty, bad, human(time.time() - t0)),
              flush=True)

    print("Готово за %s: скачано %d, без торгів %d, не вийшло %d"
          % (human(time.time() - started), total["got"], total["empty"], total["bad"]))
    if total["bad"]:
        print("Дні, які не вийшли, можна добрати повторним запуском — "
              "усе вже скачане він пропустить.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
