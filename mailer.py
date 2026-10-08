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
import json
import smtplib
import ssl
import urllib.request

import config


def enabled():
    """Чи налаштована пошта. Без цього листи не шлемо й не обіцяємо."""
    return bool(config.RESEND_API_KEY) or bool(config.SMTP_HOST and config.SMTP_USER
                                                and config.SMTP_PASS and config.SMTP_FROM)


def _resend(to, subject, text, html=None, headers=None):
    """Лист через Resend (resend.com) — сервіс розсилок: листи з нашого
    домену й не в спам. Ключ — RESEND_API_KEY, адреса — MAIL_FROM."""
    body = {"from": config.MAIL_FROM, "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    if headers:
        body["headers"] = headers
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + config.RESEND_API_KEY, "Content-Type": "application/json",
                 "User-Agent": "StatsAI"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as ex:
        detail = ""
        try:
            detail = ex.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        print("пошта (Resend): лист на %s не пішов — %s %s" % (to, ex, detail), flush=True)
        return False


def _sender():
    """From у вигляді «Ім'я <адреса>» — інакше лист приходить від голої адреси."""
    name = (config.SMTP_NAME or "").strip()
    return "%s <%s>" % (name, config.SMTP_FROM) if name else config.SMTP_FROM


def send(to, subject, text, html=None, headers=None):
    """Один лист. True — пішов, False — ні. Є ключ Resend — шлемо через
    нього (там і HTML), інакше старим SMTP простим текстом."""
    if not enabled() or not to:
        return False
    if config.RESEND_API_KEY:
        return _resend(to, subject, text, html, headers)
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
