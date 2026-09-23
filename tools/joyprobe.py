#!/usr/bin/env python3
"""Пробник джойстика M5Stack V2 через PaHub (запускать при ОСТАНОВЛЕННОМ m5hub!).

Читает канал 0 (джойстик 0x63), регистр 0x00, 4 байта: X младший-старший, Y младший-старший.
Считает медиану, минимум и максимум по 30 замерам — так видно, стоит ли джойстик
в центре (~32768) или его «уводит» в сторону (тогда курсор будет пришпилен к краю).

Важно (обе грабли проверены на себе):
  * шину открывать через os.open(O_RDWR), обычный open() даёт OSError 22;
  * структура для ioctl I2C_RDWR — это {указатель на массив сообщений, их количество},
    а НЕ сообщение; перепутаешь — получишь OSError 22 на ровном месте;
  * буферы держать живыми до вызова ioctl, иначе сборщик мусора их освободит.
"""
import ctypes, fcntl, os, statistics, time

I2C_BUS = 0
I2C_SLAVE = 0x0703
I2C_RDWR = 0x0707
I2C_M_RD = 1
PAHUB = 0x70
JOY = 0x63
JOY_CHANNEL = 0          # джойстик сидит на канале 0


class Msg(ctypes.Structure):
    """struct i2c_msg"""
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                ("len", ctypes.c_uint16), ("buf", ctypes.POINTER(ctypes.c_uint8))]


class Data(ctypes.Structure):
    """struct i2c_rdwr_ioctl_data"""
    _fields_ = [("msgs", ctypes.POINTER(Msg)), ("nmsgs", ctypes.c_uint32)]


_keep = []  # держим объекты живыми до ioctl


def open_bus():
    fd = os.open(f"/dev/i2c-{I2C_BUS}", os.O_RDWR)
    fcntl.ioctl(fd, I2C_SLAVE, PAHUB)
    return fd


def wr(fd, addr, data):
    da = (ctypes.c_uint8 * len(data))(*data)
    m = Msg(addr, 0, len(data), da)
    d = Data(ctypes.pointer(m), 1)
    _keep.extend([da, m, d])
    fcntl.ioctl(fd, I2C_RDWR, d)


def rd(fd, addr, reg, n):
    ra = (ctypes.c_uint8 * 1)(reg)
    m1 = Msg(addr, 0, 1, ra)
    ba = (ctypes.c_uint8 * n)()
    m2 = Msg(addr, I2C_M_RD, n, ba)
    arr = (Msg * 2)(m1, m2)
    d = Data(arr, 2)
    _keep.extend([ra, m1, ba, m2, arr, d])
    fcntl.ioctl(fd, I2C_RDWR, d)
    return bytes(ba)


def main():
    fd = open_bus()
    wr(fd, PAHUB, [0x00])                     # сброс каналов
    time.sleep(0.05)
    wr(fd, PAHUB, [1 << JOY_CHANNEL])         # выбрать канал джойстика
    time.sleep(0.1)

    xs, ys = [], []
    for _ in range(30):
        d = rd(fd, JOY, 0x00, 4)
        xs.append(d[0] | (d[1] << 8))
        ys.append(d[2] | (d[3] << 8))
        time.sleep(0.02)

    def report(name, v):
        med = statistics.median(v)
        print(f"   {name}: медиана {med:.0f}, минимум {min(v)}, максимум {max(v)}, разброс {max(v)-min(v)}")

    print("=== Сырые значения джойстика (центр должен быть ~32768):")
    report("X", xs)
    report("Y", ys)

    mx, my = statistics.median(xs), statistics.median(ys)
    dz = 8000
    dx, dy = mx - 32768, my - 32768
    print(f"=== Отклонение от центра: X {dx:+.0f}, Y {dy:+.0f} (порог движения {dz})")
    if abs(dx) < dz and abs(dy) < dz:
        print("   ВЫВОД: джойстик стоит в центре — сам курсор он не тянет.")
    else:
        print("   ВЫВОД: джойстик отклонён (или врёт) — драйвер будет тянуть курсор в эту сторону!")
    os.close(fd)


if __name__ == "__main__":
    main()
