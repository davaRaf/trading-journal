#!/bin/bash
# Снимок базы журнала — файлом, рядом с сервером.
#
# Зачем отдельно от backup.py. Тот кладёт ежедневные слепки журналов внутрь
# самой базы: он спасает, когда человек снёс свои сделки или импорт затёр
# поля. Но если не поднимется сама база или умрёт диск, вместе с базой
# уйдут и слепки. Поэтому нужен обычный дамп файлом — и копия за пределами
# этой машины.
#
# Ставится на сервере:
#
#     cp /opt/trading-journal/tools/pgdump.sh /usr/local/bin/tj-dump
#     chmod +x /usr/local/bin/tj-dump
#     /usr/local/bin/tj-dump            # проверить руками
#
# Дальше — по расписанию, systemd-таймером (см. SECURITY.md).
#
# Забирать копию к себе — со своей машины, а не отсюда: сервер не должен
# уметь писать в хранилище, иначе тот, кто добрался до сервера, сотрёт и
# копии.
#
#     scp -i ~/.ssh/id_ed25519_hetzner root@94.130.58.113:/var/backups/statsai/*.sql.gz .
set -euo pipefail

DIR=/var/backups/statsai
KEEP=14                      # сколько снимков держать
ENV_FILE=/opt/trading-journal/.env

mkdir -p "$DIR"
chmod 700 "$DIR"             # внутри вся база целиком, читать её никому

# Адрес базы берём оттуда же, откуда его берёт сам журнал: два разных
# места для одного и того же — верный способ однажды снимать не ту базу.
URL=$(grep -m1 '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)
URL=${URL%\"}; URL=${URL#\"}
if [ -z "$URL" ]; then
  echo "не нашёл DATABASE_URL в $ENV_FILE" >&2
  exit 1
fi

NAME="$DIR/statsai-$(date +%Y-%m-%d-%H%M).sql.gz"
TMP="$NAME.part"

# -Fp | gzip, а не -Fc: так снимок читается любым pg_restore и просто
# распаковывается глазами, если однажды понадобится достать одну таблицу.
pg_dump --no-owner --no-privileges "$URL" | gzip -9 > "$TMP"
mv "$TMP" "$NAME"
chmod 600 "$NAME"

# Пустой или подозрительно маленький файл — это не снимок, а беда молча.
SIZE=$(stat -c %s "$NAME")
if [ "$SIZE" -lt 100000 ]; then
  echo "снимок вышел всего $SIZE байт — похоже, база не отдалась" >&2
  exit 1
fi

# Старое убираем, но только если новое легло.
ls -1t "$DIR"/statsai-*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "готово: $NAME ($((SIZE / 1024 / 1024)) МБ), всего снимков: $(ls -1 "$DIR"/statsai-*.sql.gz | wc -l)"
