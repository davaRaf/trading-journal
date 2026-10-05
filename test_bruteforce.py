# -*- coding: utf-8 -*-
"""Підбір пароля: чи справді спроби впираються в стінку, що росте.

Ловимо те, заради чого сходинки й з'явились: сама хвилинна межа пропускає
п'ять спроб щохвилини цілодобово — понад сім тисяч паролів на добу, а це
вже перебір словника. Тут перевіряємо, що після десятка невдач пауза стає
хвилинами, після двох десятків — півгодиною, і що вдалий вхід усе це
забуває.

Годинник підміняємо своїм: чекати по пів години в тесті нікуди не годиться.
"""
import ratelimit


class Clock:
    """Свій час замість справжнього: крутимо стрілки скільки треба."""

    def __init__(self, start=1_000_000.0):
        self.t = start

    def time(self):
        return self.t

    def tick(self, sec):
        self.t += sec


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def fresh(clock):
    """Чистий лічильник із нашим годинником."""
    ratelimit._hits.clear()
    ratelimit._slow.clear()
    ratelimit._flood.clear()
    ratelimit.time = clock            # модуль кличе time.time()


def minute_wall():
    """П'ять невдач за хвилину — далі просимо зачекати."""
    clock = Clock()
    fresh(clock)
    keys = ["who:test"]
    for _ in range(ratelimit.LIMIT):
        check("до межі пускаємо", ratelimit.locked(keys) == 0)
        ratelimit.fail(keys)
    check("п'ята невдача зачиняє двері", ratelimit.locked(keys) > 0)
    clock.tick(ratelimit.WINDOW + 1)
    check("за хвилину знову пускаємо", ratelimit.locked(keys) == 0)


def steps_grow():
    """Упертість карається довшою паузою: 10 невдач — хвилини, 20 — півгодини."""
    clock = Clock()
    fresh(clock)
    keys = ["who:stubborn"]
    need1, pause1 = ratelimit.STEPS[0]
    need2, pause2 = ratelimit.STEPS[1]

    # десять невдач, розкладених так, щоб хвилинне вікно не заважало
    for _ in range(need1):
        ratelimit.fail(keys)
        clock.tick(ratelimit.WINDOW + 1)
    wait = ratelimit.locked(keys)
    check("після %d невдач пауза вже не хвилинна" % need1, wait > ratelimit.WINDOW)
    check("пауза — перша сходинка", wait <= pause1 + 1)

    clock.tick(pause1 + 1)
    check("сходинку відстояв — пускаємо", ratelimit.locked(keys) == 0)

    for _ in range(need2 - need1):
        ratelimit.fail(keys)
        clock.tick(1)
    check("після %d невдач пауза виросла" % need2, ratelimit.locked(keys) > pause1)
    check("але не більша за свою сходинку", ratelimit.locked(keys) <= pause2 + 1)


def hour_forgets():
    """Невдачі старші за годину не рахуються: вчорашня помилка не карає."""
    clock = Clock()
    fresh(clock)
    keys = ["who:old"]
    for _ in range(ratelimit.STEPS[0][0]):
        ratelimit.fail(keys)
    check("сходинка спрацювала", ratelimit.locked(keys) > ratelimit.WINDOW)
    clock.tick(ratelimit.LONG_WINDOW + 1)
    check("через годину все забуто", ratelimit.locked(keys) == 0)
    check("і лічильник порожній", ratelimit.fails("who:old") == 0)


def login_clears():
    """Зайшов — попередні промахи не тягнуться за людиною."""
    clock = Clock()
    fresh(clock)
    keys = ["who:lucky"]
    for _ in range(ratelimit.STEPS[0][0]):
        ratelimit.fail(keys)
    check("до входу пауза є", ratelimit.locked(keys) > 0)
    ratelimit.clear(keys)
    check("після вдалого входу паузи немає", ratelimit.locked(keys) == 0)
    check("і годинний лічильник чистий", ratelimit.fails("who:lucky") == 0)


def counter_for_alert():
    """fails() рахує саме те, за чим вирішуємо, чи попереджати хазяїна."""
    clock = Clock()
    fresh(clock)
    key = "user:42"
    for n in range(1, 4):
        ratelimit.fail([key])
        check("порахували %d-ту спробу" % n, ratelimit.fails(key) == n)


def ordinary_keys_untouched():
    """Звичайні запити сходинок не знають: там лишається сама хвилинна межа."""
    clock = Clock()
    fresh(clock)
    keys = ["ask:7"]
    for _ in range(ratelimit.STEPS[0][0] * 2):
        ratelimit.miss(keys, limit=20)      # miss, а не fail — як на питаннях помічнику
        clock.tick(ratelimit.WINDOW + 1)
    check("довгих пауз без fail() не з'являється", ratelimit.locked(keys, limit=20) == 0)


def flood_wall():
    """Загальна межа: наплив з однієї адреси впирається, сусіди — ні."""
    clock = Clock()
    fresh(clock)
    me, other = "flood:1.2.3.4", "flood:5.6.7.8"

    passed = all(ratelimit.flood(me) == 0 for _ in range(ratelimit.FLOOD_LIMIT))
    check("усі %d запитів до межі пройшли" % ratelimit.FLOOD_LIMIT, passed)
    check("за межею — відмова", ratelimit.flood(me) > 0)
    check("сусідня адреса не постраждала", ratelimit.flood(other) == 0)

    clock.tick(ratelimit.FLOOD_WINDOW + 1)
    check("нове вікно — знову пускаємо", ratelimit.flood(me) == 0)


def flood_keeps_memory_small():
    """Наплив з тисяч адрес не з'їдає пам'ять: словник не росте без краю."""
    clock = Clock()
    fresh(clock)
    for i in range(ratelimit.MAX_KEYS + 500):
        ratelimit.flood("flood:10.0.%d.%d" % (i // 256, i % 256))
    check("словник лічильника не розрісся", len(ratelimit._flood) <= ratelimit.MAX_KEYS + 1)


def main():
    real_time = ratelimit.time
    try:
        print("хвилинна межа")
        minute_wall()
        print("сходинки за впертість")
        steps_grow()
        print("пам'ять на годину")
        hour_forgets()
        print("вдалий вхід")
        login_clears()
        print("лічильник для попередження")
        counter_for_alert()
        print("звичайні запити")
        ordinary_keys_untouched()
        print("загальна межа запитів")
        flood_wall()
        flood_keeps_memory_small()
    finally:
        ratelimit.time = real_time
        ratelimit._hits.clear()
        ratelimit._slow.clear()
        ratelimit._flood.clear()
    print("\nвсе гаразд")


if __name__ == "__main__":
    main()
