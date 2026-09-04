"""
Скільки разів поспіль можна не вгадати пароль.

До цього /api/auth/login приймав спроби без ліку: скрипт міг перебирати
паролі до відомої пошти скільки завгодно швидко. Тут простий лічильник —
5 невдалих спроб за хвилину, далі відповідь «зачекай», аж поки найстаріша
з тих п'яти не випаде з хвилинного вікна.

Рахуємо по двох ключах одразу: за адресою гостя (один комп'ютер не може
довбати різні акаунти) і за самим логіном (розподілений перебір одного
акаунта з різних адрес теж упреться в межу).

Тримаємо в пам'яті процесу: сервер у нас один, а переживати перезапуск
такому лічильнику не треба — після перезапуску всім і так дається нові
п'ять спроб, і це не робить перебір реальним.
"""
import threading
import time

LIMIT = 5                 # невдалих спроб
WINDOW = 60               # за скільки секунд
MAX_KEYS = 5000           # більше в пам'яті не тримаємо

_lock = threading.Lock()
_hits = {}                # ключ -> моменти невдалих спроб, за зростанням


def _fresh(now, times):
    return [t for t in times if now - t < WINDOW]


def _sweep(now):
    """Прибрати ключі, у яких усі спроби вже застаріли."""
    for k in list(_hits):
        left = _fresh(now, _hits[k])
        if left:
            _hits[k] = left
        else:
            _hits.pop(k, None)


def check(keys):
    """Скільки секунд чекати цьому гостю. 0 — можна пробувати."""
    now = time.time()
    wait = 0
    with _lock:
        for k in keys:
            times = _fresh(now, _hits.get(k) or [])
            if times:
                _hits[k] = times
            else:
                _hits.pop(k, None)
            if len(times) >= LIMIT:
                # чекаємо, поки найстаріша з останніх LIMIT спроб випаде з вікна
                wait = max(wait, int(WINDOW - (now - times[-LIMIT])) + 1)
    return wait


def miss(keys):
    """Не вгадав пароль."""
    now = time.time()
    with _lock:
        if len(_hits) > MAX_KEYS:
            _sweep(now)
        for k in keys:
            times = _fresh(now, _hits.get(k) or [])
            times.append(now)
            _hits[k] = times[-LIMIT:]


def forget(keys):
    """Зайшов — попередні промахи більше не рахуються."""
    with _lock:
        for k in keys:
            _hits.pop(k, None)
