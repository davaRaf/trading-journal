# -*- coding: utf-8 -*-
"""
Ходити назовні тільки по IPv4.

Виміряно на сервері 06.09.2026: п'ятнадцять запитів до api.telegram.org
по IPv6 — і три з них висять рівно 30 секунд (тайм-аут), решта йдуть за
0.08 с. Ті самі п'ятнадцять по IPv4 — усі за 0.05–0.08 с. Тобто маршрут
Hetzner → Telegram по IPv6 губить пакети, а Python за замовчуванням
пробує саме IPv6 першим: кожне п'яте повідомлення в боті чекало пів
хвилини на порожньому місці.

Лікувати можна було б і на сервері (/etc/gai.conf), але тоді лікування
живе поза репозиторієм: новий сервер — і все повертається. Тут воно їде
разом з кодом.

Якщо колись IPv6 полагодять, цей модуль просто перестане бути потрібним:
на швидкість по IPv4 він не впливає.
"""
import http.client
import socket
import urllib.request


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        # Те саме, що робить http.client, тільки адресу питаємо виключно
        # серед IPv4 (AF_INET).
        addrs = socket.getaddrinfo(self.host, self.port, socket.AF_INET,
                                   socket.SOCK_STREAM)
        err = None
        for af, socktype, proto, _canon, sa in addrs:
            sock = socket.socket(af, socktype, proto)
            try:
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(self.timeout)
                if self.source_address:
                    sock.bind(self.source_address)
                sock.connect(sa)
            except OSError as ex:
                sock.close()
                err = ex
                continue
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            return
        raise err or OSError("не вдалось з'єднатись по IPv4 з %s" % self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


opener = urllib.request.build_opener(_IPv4HTTPSHandler())


def urlopen(req, timeout=None):
    """Заміна urllib.request.urlopen для наших зовнішніх викликів."""
    if timeout is None:
        return opener.open(req)
    return opener.open(req, timeout=timeout)
