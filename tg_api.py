# -*- coding: utf-8 -*-
"""
Telegram Bot API поверх urllib — библиотеки вроде aiogram тут не нужны,
нам хватает горстки методов.
"""
import json
import urllib.error
import urllib.request

from config import BOT_TOKEN

API = "https://api.telegram.org/bot%s/%s"
# Файли лежать на іншому шляху, ніж методи: getFile віддає file_path,
# а саму картинку качають уже звідси.
FILES = "https://api.telegram.org/file/bot%s/%s"


class TelegramError(Exception):
    pass


def call(method, payload=None, timeout=30):
    if not BOT_TOKEN:
        raise TelegramError("BOT_TOKEN не задан")
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API % (BOT_TOKEN, method), data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        try:
            body = json.loads(ex.read().decode("utf-8"))
        except Exception:
            raise TelegramError("%s: HTTP %s" % (method, ex.code))
        raise TelegramError("%s: %s" % (method, body.get("description")))
    if not body.get("ok"):
        raise TelegramError("%s: %s" % (method, body.get("description")))
    return body.get("result")


def send_typing(chat_id):
    """«друкує…» у чаті. Відповідь від моделі йде секунду-дві, і без цього
    здається, що бот заснув. Помилку ковтаємо: це прикраса, а не робота."""
    try:
        call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass


def get_me():
    return call("getMe")


def get_updates(offset=None, timeout=25):
    payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    # ждём ответа дольше, чем длится long polling, иначе рвём соединение сами
    return call("getUpdates", payload, timeout=timeout + 10)


def get_file(file_id):
    """Шлях до файлу на серверах Телеграма. Живе годину — качати треба одразу."""
    return call("getFile", {"file_id": file_id})


def download(file_path, timeout=30):
    """Сама картинка байтами. Ліміт Телеграма на скачування — 20 МБ,
    скріни графіків у нього вкладаються з великим запасом."""
    if not BOT_TOKEN:
        raise TelegramError("BOT_TOKEN не задан")
    req = urllib.request.Request(FILES % (BOT_TOKEN, file_path))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as ex:
        raise TelegramError("download: HTTP %s" % ex.code)


def send_message(chat_id, text, keyboard=None, parse_mode=None, reply_kb=None):
    """parse_mode — тільки там, де текст ми зібрали самі (новини, HTML).

    Решта повідомлень іде звичайним текстом: у них трапляються назви з
    журналу й слова людини, і будь-яка кутова дужка ламала б розмітку.
    """
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    elif reply_kb is not None:
        # Постійна клавіатура біля поля вводу: нею тримаємо кнопку «Записати
        # угоду» завжди на очах. Порожній список прибирає її.
        payload["reply_markup"] = ({"keyboard": reply_kb, "resize_keyboard": True,
                                    "is_persistent": True}
                                   if reply_kb else {"remove_keyboard": True})
    return call("sendMessage", payload)


def edit_message_text(chat_id, message_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    payload["reply_markup"] = {"inline_keyboard": keyboard or []}
    return call("editMessageText", payload)


def answer_callback(callback_id, text=None):
    """Гасить «годинник» на кнопці. Помилку ковтаємо: Телеграм не приймає
    відповідь на запит, старший за хвилину («query is too old»), а це
    трапляється щоразу, коли людина тисне кнопку в старому повідомленні
    або поки бот перезапускався. Робота від цього не залежить — але
    непроковтнутий виняток раніше валив увесь обробник, і людина
    замість відповіді не отримувала нічого."""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        return call("answerCallbackQuery", payload)
    except TelegramError:
        return None
