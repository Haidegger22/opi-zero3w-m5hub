#!/usr/bin/env python3
"""CardKB напрямую на шине i2c-0 (без PaHub) — Orange Pi 4 Pro.

Берёт весь разбор клавиатуры из m5hub.py (битовая маска нажатий, слои
Shift/Sym/Fn, T9, Fn-комбинации), но отключает джойстик, скролл, LED и выбор
канала PaHub: на 4 Pro клавиатура подключена прямо к 40-pin гребёнке
(i2c0, пины 3/5), адрес 0x5F.

Запуск: от root (у /dev/i2c-0 права crw-rw---- root:i2c), с DISPLAY=:0 и
XAUTHORITY домашнего пользователя. Готовый юнит — packaging/cardkb.service.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m5hub  # noqa: E402


class DirectHub(m5hub.Hub):
    # PaHub отсутствует: выбор канала — пустышка, сброс хаба не нужен
    def sel(self, c):
        return True

    def _rst(self):
        return

    # Джойстика нет: калибровка не нужна, центр — фиктивный
    def _cal(self):
        self._cx = self._cy = 32768

    # Подсветки PaHub-юнитов нет
    def _led(self, *a, **k):
        return

    def _led_j(self, *a, **k):
        return

    # Опрос отсутствующих устройств
    def _j(self):
        return

    def _s(self):
        return


if __name__ == '__main__':
    import signal

    os.environ.setdefault('DISPLAY', ':0')
    hub = DirectHub()

    def _term(sig, frm):
        print('[cardkb] SIGTERM — чистое завершение', flush=True)
        try:
            hub.cleanup()
        except Exception as e:
            print('[cardkb] cleanup err:', e, flush=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, _term)
    try:
        hub.run()
    except KeyboardInterrupt:
        hub.cleanup()
