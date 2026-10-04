# -*- coding: utf-8 -*-
"""
Замок на акаунт: python test_lock.py

Замок — крок, після якого людина не може працювати, тож перевіряємо
саме те, що робить його замком:

* тримає сервер, а не браузер: гілка стоїть у кожному do_*, і жодна
  дія журналу не проходить повз неї;
* відкритим лишається рівно потрібне: вихід, /api/admin і сторінки
  (інакше не було б чим ні піти, ні зняти, ні показати сам текст);
* чужого замка на себе не ловимо — замкнений лише той, кому поставили;
* база відмовила — замок не вигадуємо й не знімаємо;
* слова несе сервер, а екран замка не збирає з них розмітку.

Бази не треба: дивимось на код і підставляємо свій db.locked_users.
"""
import io
import os
import re

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-lock")

import app
import db


def check(name, cond):
    print("  %-5s %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


# ------------------------------------------------------------------ підробка --

class Fake(app.H):
    """Обробник без сокета: беремо від справжнього сам замок, а відповідь
    і «хто прийшов» підставляємо свої."""

    def __init__(self, uid):
        self.uid = uid
        self.sent = None

    def _uid(self):
        return self.uid

    def _json(self, body, code=200):
        self.sent = (code, body)
        return None


def with_locks(table, fn):
    """Виконати fn, доки db.locked_users повертає table (або кидає)."""
    was = db.locked_users
    # кеш спільний на клас — інакше наступна перевірка побачила б минулу
    with app.H._lock_gate:
        app.H._locks[:] = [0.0, {}]
    db.locked_users = table
    try:
        return fn()
    finally:
        db.locked_users = was
        with app.H._lock_gate:
            app.H._locks[:] = [0.0, {}]


# -------------------------------------------------------------------- гілка --

def gate_in_every_method():
    """Жодного do_*, який забув спитати про замок.

    Саме тут замок і тримається: гілка в одному методі означала б, що
    решта працює — наприклад, правка угоди через PUT.
    """
    src = io.open("app.py", encoding="utf-8").read()
    for name in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
        body = src.split("def %s(self)" % name, 1)[1].split("\n    def ", 1)[0]
        check("%s питає про замок" % name, "_locked_out(p)" in body)


def gate_after_ref_rewrite():
    """У do_GET замок стоїть ПІСЛЯ зняття мітки партнера.

    Мітка на початку шляху переписує адресу: «/fxlab/api/trades» стає
    «/api/trades». Перевірка до переписування бачила б шлях, якого
    обробник не отримає, — і замок обходився б одним префіксом.
    """
    src = io.open("app.py", encoding="utf-8").read()
    body = src.split("def do_GET(self)", 1)[1].split("\n    def ", 1)[0]
    check("замок після переписування шляху",
          body.index("p = unquote(rest)") < body.index("_locked_out(p)"))


def body_read_before_answer():
    """Там, де є тіло, замок відповідає після читання: інакше ненабрані
    байти лишились би в з'єднанні й поїхали як початок наступного запиту."""
    src = io.open("app.py", encoding="utf-8").read()
    for name in ("do_POST", "do_PUT"):
        body = src.split("def %s(self)" % name, 1)[1].split("\n    def ", 1)[0]
        check("%s: тіло забрано до відмови" % name,
              body.index("self._body()") < body.index("_locked_out(p)"))


# ------------------------------------------------------------------- кого --

def locks_only_its_own():
    """Замок стоїть на одній людині — решта журналом користується."""
    def go():
        locked = Fake(7)
        check("замкненого не пускає", locked._locked_out("/api/trades") is True)
        check("відповідь 403", locked.sent[0] == 403)
        check("код locked", locked.sent[1].get("code") == "locked")
        check("слова з бази", locked.sent[1].get("error") == "не бери наше")

        other = Fake(8)
        check("сусіда пускає", other._locked_out("/api/trades") is False)
        check("сусідові нічого не відповіли", other.sent is None)

        guest = Fake(None)
        check("гостя не чіпаємо", guest._locked_out("/api/trades") is False)

    with_locks(lambda: {7: "не бери наше"}, go)


def open_while_locked():
    """Що лишається відкритим під замком — і що ні."""
    def go():
        who = Fake(7)
        for p in ("/api/auth/logout", "/api/admin/set-lock",
                  "/", "/login", "/static/app.js", "/health", "/u/dan"):
            check("відкрито: %s" % p, who._locked_out(p) is False)
        for p in ("/api/trades", "/api/ts", "/api/ts/notion", "/api/prefs",
                  "/api/assistant", "/api/billing/checkout", "/api/pub/trades"):
            check("закрито: %s" % p, who._locked_out(p) is True)

    with_locks(lambda: {7: "стоп"}, go)


def page_opens_to_show_words():
    """Сторінка під замком відкривається: на ній і показується текст.

    Якби замок різав і сторінки, людина побачила б пустку й не дізналась,
    чому журнал не працює і куди писати.
    """
    def go():
        check("сама сторінка журналу відкрита",
              Fake(7)._locked_out("/") is False)
    with_locks(lambda: {7: "стоп"}, go)


# --------------------------------------------------------------- база мовчить --

def db_down_keeps_last_answer():
    """База не відповіла — замок не вигадуємо й не знімаємо."""
    def boom():
        raise RuntimeError("база мовчить")

    def go():
        check("без відомого замка нікого не ріжемо",
              Fake(7)._locked_out("/api/trades") is False)

    with_locks(boom, go)

    # а тепер те саме, але замок уже був прочитаний раніше
    with app.H._lock_gate:
        app.H._locks[:] = [0.0, {}]
    was = db.locked_users
    db.locked_users = lambda: {7: "стоп"}
    try:
        check("замок прочитано", Fake(7)._locked_out("/api/trades") is True)
        db.locked_users = boom
        with app.H._lock_gate:
            app.H._locks[0] = 0.0          # змушуємо перечитати
        check("база впала — замок лишився",
              Fake(7)._locked_out("/api/trades") is True)
    finally:
        db.locked_users = was
        with app.H._lock_gate:
            app.H._locks[:] = [0.0, {}]


def cache_is_shared_and_expires():
    """Список замків лежить у пам'яті, спільний на всіх робітників процесу,
    і протухає — інакше знятий замок тримався б до перезапуску."""
    check("пам'ять одна на клас", app.H._locks is app.H._locks)
    check("час життя скінченний", 0 < app.H.LOCK_TTL <= 60)

    calls = []

    def count():
        calls.append(1)
        return {7: "стоп"}

    def go():
        Fake(7)._locked_out("/api/trades")
        Fake(7)._locked_out("/api/trades")
        Fake(8)._locked_out("/api/trades")
        check("база опитана один раз на всіх", len(calls) == 1)
        with app.H._lock_gate:
            app.H._locks[0] = 0.0
        Fake(7)._locked_out("/api/trades")
        check("після протухання перечитали", len(calls) == 2)

    with_locks(count, go)


# ------------------------------------------------------------------- слова --

def words_come_from_server():
    """Текст замка живе в базі, а не у фронті: слова до кожного замка свої."""
    src = io.open("static/lock.js", encoding="utf-8").read()
    check("екран замка не зашиває текст",
          "Извини" not in src and "идеи" not in src)
    check("текст ставиться як текст, не як розмітка",
          "textContent" in src and ".innerHTML = note" not in src)
    # Шукаємо саме спосіб закрити, а не слово: про Escape у файлі сказано
    # в поясненні, що його тут навмисно не слухають.
    check("закрити нічим",
          "addEventListener" not in src and "onkeydown" not in src
          and "remove()" not in src and "function close" not in src)
    check("контакт підписано як Telegram", "Telegram-контакт" in src)

    adm = io.open("admin_page.py", encoding="utf-8").read()
    check("у полі адмінки є слова за умовчанням", "LOCK_DEFAULT" in adm)


def front_catches_the_lock():
    """Фронт ловить 403 code=locked в одному місці — у api()."""
    src = io.open("static/app.js", encoding="utf-8").read()
    check("api() знає про замок",
          'code==="locked"' in src and "Lock.show" in src)
    page = io.open("static/index.html", encoding="utf-8").read()
    check("lock.js підключено", "/static/lock.js" in page)
    check("lock.css підключено", "/static/lock.css" in page)
    check("lock.js раніше за app.js",
          page.index("/static/lock.js") < page.index("/static/app.js"))


def admin_only():
    """Ставить і знімає замок тільки власник."""
    src = io.open("app.py", encoding="utf-8").read()
    block = src.split('if p == "/api/admin/set-lock"', 1)[1][:2000]
    check("питає, хто прийшов", "_is_admin" in block)
    check("лишає слід у журналі безпеки", "seclog.event" in block)
    check("скидає свій кеш", "_locks[:]" in block)


def main():
    print("Замок на акаунт")
    print(" гілка")
    gate_in_every_method()
    gate_after_ref_rewrite()
    body_read_before_answer()
    print(" кого тримає")
    locks_only_its_own()
    open_while_locked()
    page_opens_to_show_words()
    print(" база мовчить")
    db_down_keeps_last_answer()
    cache_is_shared_and_expires()
    print(" слова й фронт")
    words_come_from_server()
    front_catches_the_lock()
    admin_only()
    print("усе гаразд")


if __name__ == "__main__":
    main()
