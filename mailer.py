# -*- coding: utf-8 -*-
"""
Відправка листів — рівно стільки, скільки треба для «забув пароль».

Своєї пошти сайт не має: лист іде через звичайний поштовий ящик за
SMTP (Gmail, Ukr.net — байдуже), логін і пароль якого лежать у змінних
оточення. Немає змінних — лист просто не піде, і authmail.py залишить
людині відновлення через Телеграм. Тому все тут мовчазне: помилку
пишемо в журнал сервера й повертаємо False, а не валимо запит.
"""
import email.message
import smtplib
import ssl

import config


def enabled():
    """Чи налаштована пошта. Без цього листи не шлемо й не обіцяємо."""
    return bool(config.SMTP_HOST and config.SMTP_USER
                and config.SMTP_PASS and config.SMTP_FROM)


def _sender():
    """From у вигляді «Ім'я <адреса>» — інакше лист приходить від голої адреси."""
    name = (config.SMTP_NAME or "").strip()
    return "%s <%s>" % (name, config.SMTP_FROM) if name else config.SMTP_FROM


def send(to, subject, text):
    """Один лист простим текстом. True — пішов, False — ні."""
    if not enabled() or not to:
        return False
    msg = email.message.EmailMessage()
    msg["From"] = _sender()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        # 465 — захищене з'єднання одразу, 587 — спершу відкрите, потім
        # STARTTLS. Обидва порти живі у всіх поштових служб, тож вибір
        # робимо за номером, а не окремою змінною.
        if int(config.SMTP_PORT) == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                  timeout=20, context=ssl.create_default_context()) as s:
                s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
        return True
    except Exception as ex:
        print("пошта: лист на %s не пішов — %s" % (to, ex), flush=True)
        return False
