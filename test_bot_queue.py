# -*- coding: utf-8 -*-
"""Черга оновлень у боті: чужа відповідь не має чекати на чужу модель.

Ловимо те, через що бот «то відповідає одразу, то мовчить пів хвилини»:
раніше оновлення оброблялись одне за одним, і поки модель думала над
питанням в одному чаті, кнопки в іншому стояли в тій самій черзі.
"""
import threading
import time

import bot


def check(name, cond):
    print("  %-5s %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def msg(chat_id, text):
    import time as _t
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text,
                                        "from": {"id": chat_id}, "date": int(_t.time())}}


def run():
    done = []
    started = threading.Event()

    def fake_handle(u):
        text = u["message"]["text"]
        if text == "повільне":
            started.set()
            time.sleep(0.6)                 # модель «думає»
        done.append(text)

    real, bot.handle_update = bot.handle_update, fake_handle
    try:
        bot.dispatch(msg(1, "повільне"))
        started.wait(1)                     # переконуємось, що воно вже в роботі
        bot.dispatch(msg(2, "чужий чат"))
        bot.dispatch(msg(1, "своє друге"))
        time.sleep(0.25)
        check("чужий чат не чекав на модель", "чужий чат" in done)
        check("своє друге ще чекає своєї черги", "своє друге" not in done)
        time.sleep(0.7)
        check("усе оброблено", len(done) == 3)
        check("порядок усередині чату збережено",
              done.index("повільне") < done.index("своє друге"))
    finally:
        bot.handle_update = real


run()
print("\nусе добре")
