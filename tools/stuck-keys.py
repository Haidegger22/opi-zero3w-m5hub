#!/usr/bin/env python3
"""stuck-keys.py [--release] — показать клавиши, которые «зажаты» в X, и снять их.

Зачем: m5hub отправляет нажатия CardKB/джойстика через XTEST. Если клавиша
оказалась нажатой и отпускание не пришло (обрыв чтения I²C, перезапуск драйвера
посреди удержания), X-сервер считает её удержанной и сам повторяет её с частотой
автоповтора — в приложении это выглядит как бесконечная прокрутка или поток
символов. Перезапуск m5hub состояние X НЕ чистит: нужен явный KeyRelease.

Без флага — только показывает. С --release — снимает найденные клавиши.
"""
import sys

from Xlib import X, XK, display
from Xlib.ext import xtest

REL = "--release" in sys.argv

d = display.Display()

# какие клавиши сейчас нажаты (бит на каждый код клавиши)
try:
    km = d.query_keymap()
except Exception as e:                                   # pragma: no cover
    print("не удалось прочитать состояние клавиш: %s" % e)
    sys.exit(1)

raw = bytes(km) if not isinstance(km, (bytes, bytearray)) else bytes(km)
pressed = []
for code in range(8 * len(raw)):
    if raw[code // 8] & (1 << (code % 8)):
        sym = d.keycode_to_keysym(code, 0)
        try:
            name = XK.keysym_to_string(sym) or "?"
        except Exception:
            name = "?"
        pressed.append((code, sym, name))

print("зажатых клавиш: %d" % len(pressed))
for code, sym, name in pressed:
    print("   код %-4d символ %-6d «%s»" % (code, sym, name))

if not pressed:
    print("   (ничего не зажато — состояние X чистое)")
    sys.exit(0)

if not REL:
    print("запусти с --release, чтобы снять их")
    sys.exit(0)

for code, sym, name in pressed:
    xtest.fake_input(d, X.KeyRelease, code)
    d.flush()
d.sync()
print("отпущено: %s" % ", ".join("«%s»(код %d)" % (n, c) for c, _, n in pressed))

km2 = bytes(d.query_keymap())
left = [c for c in range(8 * len(km2)) if km2[c // 8] & (1 << (c % 8))]
print("после снятия зажато: %d %s" % (len(left), left if left else "— чисто"))
