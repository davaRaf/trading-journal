# -*- coding: utf-8 -*-
"""
Слід безпеки: хто заходив, що не вийшло, що зробили з акаунтом.

Навіщо. Коли щось таки трапиться, головне питання буде не «як це
влаштовано», а «коли почалось і кого зачепило». Відповісти на нього можна
тільки тим, що записано заздалегідь: по гарячих слідах збирати нема з
чого. Тому кілька подій ми записуємо завжди — вхід, невдалий вхід, зміна
пароля, 2FA і все, що робить власник у службовій панелі.

Куди. У звичайний вивід процесу. На сервері його підбирає systemd, і все
лежить в одному місці, разом з помилками й трасуваннями:

    journalctl -u trading-journal | grep statsai-sec       # усе
    journalctl -u trading-journal | grep "statsai-sec вхід" # тільки входи

Окремої бази під це не заводимо: журнал у нас один процес на одній
машині, і другий склад подій довелось би ще й берегти від того, від чого
бережемо решту.

Чого тут немає ніколи: паролів, кодів із застосунку, кук, вмісту листів.
Пошта — лише обрізана (d***@gmail.com): свій акаунт у ній упізнаєш, а от
списку адрес із украденого журналу не збереш.
"""
import datetime

TAG = "statsai-sec"


def mask(value):
    """Пошта чи логін у вигляді, за яким людину впізнає тільки вона сама."""
    s = str(value or "").strip()
    if not s:
        return "—"
    if "@" not in s:
        return s[:2] + "***" if len(s) > 2 else "***"
    name, _, host = s.partition("@")
    return (name[:1] or "?") + "***@" + host


def event(what, ok=True, user=None, ip="", login="", **extra):
    """Один рядок у слід.

    what  — що сталось: «вхід», «пароль», «2fa», «адмін».
    ok    — вийшло чи ні; невдачі шукають найчастіше, тому вони помітні.
    user  — запис із бази, якщо знаємо, хто це.
    login — те, що ввели, коли не знаємо (невдалий вхід).
    """
    # Усе разом під охороною: слід не має права завалити сам запит. Людина
    # прийшла зайти в журнал, а не подивитись, як ми ведемо записи.
    try:
        when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [TAG, when, str(what), "ok" if ok else "ЗБІЙ"]
        if user:
            parts.append("uid=%s" % user.get("id"))
            if user.get("nickname"):
                parts.append("нік=%s" % user["nickname"])
        elif login:
            parts.append("логін=%s" % mask(login))
        if ip:
            parts.append("ip=%s" % ip)
        for k, v in extra.items():
            parts.append("%s=%s" % (k, v))
        print(" ".join(parts), flush=True)
    except Exception as ex:
        try:
            print("%s слід не записався: %r" % (TAG, ex), flush=True)
        except Exception:
            pass
