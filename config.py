# -*- coding: utf-8 -*-
"""
Настройки из окружения. Локально удобнее держать их в файле .env рядом
с app.py — он в репозиторий не попадает (см. .gitignore и .env.example).
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path=None):
    """Читает .env, не затирая переменные, уже заданные в окружении."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


load_dotenv()

DATABASE_URL  = os.environ.get("DATABASE_URL", "")
# Де лежать скріншоти, посилання-снімки й налаштування Notion. На хостингу
# сюди підставляють теку тому (volume) — інакше файли зникнуть при першому
# ж оновленні коду: у контейнерів файлова система тимчасова.
DATA_DIR      = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME  = os.environ.get("BOT_USERNAME", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
# Адрес журнала — бот вставляет его в сообщения. Меняется вместе с хостингом,
# поэтому берём из окружения, а не зашиваем в текст.
SITE_URL      = os.environ.get("SITE_URL", "https://trading-journal-production-440c.up.railway.app/")
# Разовый ключ для переноса скриншотов на новый сервер (tools/upload_shots.py).
# Пока пустой — точка загрузки просто не существует. После переезда убрать.
ADMIN_TOKEN   = os.environ.get("ADMIN_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Вхід через сервіси (oauth.py). Кнопка на сторінці входу показується,
# тільки якщо є обидва ключі. Telegram окремих ключів не потребує.
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DISCORD_CLIENT_ID    = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
# Зовнішня адреса сайту для зворотних посилань OAuth (https://…). Якщо
# порожня — береться з заголовків запиту.
PUBLIC_URL    = os.environ.get("PUBLIC_URL", "").rstrip("/")
PORT          = int(os.environ.get("PORT", 8172))
# На своєму комп'ютері слухаємо тільки себе, на хостингу — усі інтерфейси,
# інакше платформа не достукається до сервера й вважатиме його мертвим.
HOST          = os.environ.get("HOST", "127.0.0.1")
# Телеграм-бот довгим опитуванням: на хостингу зручно тримати його в тому
# самому процесі, що й сайт — тоді вистачає одного безкоштовного сервісу.
RUN_BOT       = os.environ.get("RUN_BOT", "") not in ("", "0", "false", "no")
