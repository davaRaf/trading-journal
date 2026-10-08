# Автовикладка з GitHub

Сервер сам щохвилини перевіряє `main` у GitHub і, коли там новий коміт,
викладає його й перезапускає сайт. Ручний `./deploy.sh` нікуди не
дівається — він лишається для випадків «виклади просто зараз» і для
`--local` (виклад робочої теки без коміту).

## Чому опитування, а не вебхук

Вебхук чи GitHub Actions спрацьовували б миттєво, але і те, і те
вмикають у **налаштуваннях репозиторію**, а репозиторій чужий
(`davaRaf/trading-journal`) — у контрибʼютора туди доступу немає.
Опитування прав не потребує взагалі: репозиторій публічний, сервер
читає його по HTTPS. Ціна — затримка до хвилини.

## Встановлення (один раз, від root на сервері)

```bash
# 1) git, якщо його раптом немає
apt-get update -qq && apt-get install -y git

# 2) скрипт і юніти з репозиторію, який уже лежить на сервері
install -m 755 /opt/trading-journal/tools/autodeploy/tj-autodeploy /usr/local/bin/tj-autodeploy
install -m 644 /opt/trading-journal/tools/autodeploy/tj-autodeploy.service /etc/systemd/system/
install -m 644 /opt/trading-journal/tools/autodeploy/tj-autodeploy.timer   /etc/systemd/system/

# 3) перша викладка руками — вона ж клонує /opt/tj-src
/usr/local/bin/tj-autodeploy

# 4) вмикаємо таймер
systemctl daemon-reload
systemctl enable --now tj-autodeploy.timer
```

## Перевірка

```bash
systemctl list-timers tj-autodeploy.timer   # коли спрацює наступного разу
journalctl -u tj-autodeploy -n 30           # що робила остання викладка
systemctl status trading-journal            # живий сайт
```

## Що варто памʼятати

- Їде **все, що потрапило в `main`**, включно з чужими комітами, без
  перегляду. Хочеш контролю — тримай свою роботу в гілці й зливай у
  `main` тоді, коли готовий.
- `.env`, `data/` (база, скріни) і `.venv` виклад не чіпає.
- Якщо сайт після перезапуску не відповів `200`, скрипт кладе в журнал
  останні 20 рядків логу сайту й виходить з помилкою — таймер спробує
  ще раз за хвилину.
- Зупинити автовикладку: `systemctl disable --now tj-autodeploy.timer`.
