# -*- coding: utf-8 -*-
"""
Разовый перенос скриншотов на новый сервер.

Нужен один раз при переезде: сделки уезжают вместе с базой, а картинки
лежат файлами и сами не поедут.

Как пользоваться:

    1. На хостинге задать переменную ADMIN_TOKEN (любая длинная строка).
    2. Запустить отсюда:

        python tools/upload_shots.py https://адрес-сервера ТОКЕН

    3. Убрать ADMIN_TOKEN с хостинга — точка загрузки исчезнет вместе с ним.

Скрипт заливает только те файлы, которых на сервере ещё нет, поэтому его
можно спокойно запускать повторно, если связь оборвалась.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

SHOTS = os.path.join(config.DATA_DIR, "screenshots")
TIMEOUT = 60


def send(base, token, name, raw):
    body = json.dumps({"name": name, "data": base64.b64encode(raw).decode()}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/api/admin/upload-shot", data=body,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    base, token = sys.argv[1], sys.argv[2]

    names = sorted(n for n in os.listdir(SHOTS)
                   if os.path.isfile(os.path.join(SHOTS, n)))
    total = len(names)
    size = sum(os.path.getsize(os.path.join(SHOTS, n)) for n in names)
    print("файлов: %d, вместе %.1f МБ" % (total, size / 1024 / 1024))

    sent = skipped = failed = 0
    for i, name in enumerate(names, 1):
        path = os.path.join(SHOTS, name)
        with open(path, "rb") as f:
            raw = f.read()
        for attempt in range(3):
            try:
                res = send(base, token, name, raw)
                if res.get("skipped"):
                    skipped += 1
                else:
                    sent += 1
                break
            except urllib.error.HTTPError as e:
                print("  %s — ошибка %s" % (name, e.code))
                failed += 1
                break
            except Exception as e:
                if attempt == 2:
                    print("  %s — не вышло: %s" % (name, e))
                    failed += 1
                else:
                    time.sleep(2)
        if i % 50 == 0 or i == total:
            print("  %d из %d" % (i, total))

    print("залито %d, уже были %d, не вышло %d" % (sent, skipped, failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
