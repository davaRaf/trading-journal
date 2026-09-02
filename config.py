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
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME  = os.environ.get("BOT_USERNAME", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PORT          = int(os.environ.get("PORT", 8172))
# На своєму комп'ютері слухаємо тільки себе, на хостингу — усі інтерфейси,
# інакше платформа не достукається до сервера й вважатиме його мертвим.
HOST          = os.environ.get("HOST", "127.0.0.1")
# Телеграм-бот довгим опитуванням: на хостингу зручно тримати його в тому
# самому процесі, що й сайт — тоді вистачає одного безкоштовного сервісу.
RUN_BOT       = os.environ.get("RUN_BOT", "") not in ("", "0", "false", "no")
