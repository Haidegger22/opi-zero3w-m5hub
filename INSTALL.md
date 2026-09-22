# Установка и использование

Кратко: клонировать, поставить зависимости, запустить как службу. Всё остальное —
про CardKB, её прошивку и настройку удержания стрелок — в [README.md](README.md),
раздел «Прошивка CardKB через Raspberry Pi 5».

## 1. Драйвер m5hub

```bash
# зависимости (Debian 13, Orange Pi Zero 3W)
sudo apt-get install -y python3 python3-xlib xdotool i2c-tools

# клонирование
git clone https://github.com/Haidegger22/opi-zero3w-m5hub.git
cd opi-zero3w-m5hub

# запуск вручную (проверка)
sudo python3 m5hub.py
```

Служба systemd (`/etc/systemd/system/m5hub.service`):

```ini
[Unit]
Description=M5Hub driver
After=multi-user.target

[Service]
Type=simple
WorkingDirectory=/home/pi
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pi/.Xauthority
ExecStart=/usr/bin/python3 /home/pi/m5hub/m5hub.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now m5hub
systemctl status m5hub
```

Шина I2C включается в `orangepi-config` → System → Hardware → I2C0,
после чего `i2cdetect -y 0` должен показать `0x70` (PaHub).

## 2. Прошивка CardKB через Raspberry Pi 5

Нужна, чтобы стрелки **держались**, пока клавиша зажата (в штатной прошивке
клавиатура сообщает только отжатие). Полное объяснение — в README.

### 2.1. Что понадобится

- Raspberry Pi 5 (у нас — Raspberry Pi 5), 6 проводов, паяльник
- `avrdude` **с поднятым пределом номеров линий** — без этого он не работает
  с номерами больше 400, а на Pi 5 база GPIO = 569 (см. `tools/avrdude-pinmax.patch`)
- файл прошивки `firmware/cardkb_m8.hex` (собран из официального исходника M5Stack,
  лицензия MIT — `m5stack/M5Unit-KEYBOARD`, `examples/firmware/CardKB_Firmware`)

### 2.2. Подключение

| Площадка CardKB | Пин Raspberry Pi 5 | Роль |
|---|---|---|
| 1 (квадратная) | 1 (3,3 В) | питание |
| 2 | 11 | RST |
| 3 | 13 | SCK |
| 5 | 16 | MOSI |
| 4 | 15 | MISO |
| 6 | 39 | земля |

> ⚠️ Питание — только 3,3 В (пин 1 или 17). Пять вольт подавать нельзя: линия MISO
> окажется под 5 В и сожжёт вход Raspberry Pi.
> ⚠️ MISO и MOSI стоят в порядке, отличающемся от логики схемы — этот порядок
> проверен на живой плате. Если не работает, перебрать комбинации скриптом.

### 2.3. Сборка avrdude с поддержкой GPIO

```bash
sudo apt-get install -y build-essential cmake libgpiod-dev libusb-1.0-0-dev \
                        libhidapi-dev libftdi1-dev

git clone https://github.com/avrdudes/avrdude.git
cd avrdude
git checkout v7.1                     # версия, на которой проверялось
patch -p1 < /путь/к/tools/avrdude-pinmax.patch
cmake -S . -B build -DHAVE_LINUXGPIO=1
cmake --build build -j$(nproc)
sudo cmake --install build --prefix=/usr/local
avrdude -c '?' | grep linuxgpio       # драйвер должен быть виден
```

### 2.4. Прошивка

Скрипт делает всё сам: находит рабочую комбинацию сигналов, сохраняет родную
прошивку, записывает новую и сверяет результат.

```bash
sudo bash tools/flash_cardkb_pi5.sh firmware/cardkb_m8.hex
```

Если запустить скрипт без аргумента — он только читает сигнатуру чипа и ничего
не пишет (безопасная проверка: `0x1e9307` = ATmega8).

Родная прошивка сохраняется в `~/cardkb-original.bin` — вернуться к ней можно так:

```bash
sudo bash tools/flash_cardkb_pi5.sh ~/cardkb-original.bin
```

### 2.5. Проверка результата

```bash
# канал PaHub на клавиатуру
i2cset -y 0 0x70 0x00; i2cset -y 0 0x70 0x04

# версия прошивки и текущий режим
i2cget -y 0 0x5F 0xFE        # 0x01 = новая прошивка
i2cget -y 0 0x5F 0x20        # 0x00 обычный, 0x01 сканирование нажатий

# включить режим сканирования и посмотреть маску удержанных клавиш
i2cset -y 0 0x5F 0x20 0x01
i2ctransfer -y 0 w1@0x5F 0x10 r7      # 7 байт; зажать стрелку и повторить
```

## 3. Режим сканирования и удержание стрелок

Клавиатура сообщает удержанные клавиши битовой маской (регистр `0x10`, 7 байт).
Индексы: Esc = 0, влево = 24, вверх = 25, Enter = 35, вниз = 36, вправо = 37, пробел = 47.

```python
data = read_register(0x10, 7)
bits = int.from_bytes(data[:6], "little")
held = lambda i: bool((bits >> i) & 1)
```

- для **игр** это использует игровой мост `game_input.py` (репозиторий
  `opi-zero3w-retroarch`): включает режим сканирования, читает маску, выставляет
  клавиши с удержанием и возвращает обычный режим на выходе;
- в **m5hub** при старте принудительно выставляется режим `0x20 = 0`: если игровой
  мост завершится аварийно, клавиатура в системе не останется немой.

Проверка удержания — логгер X-событий `xrec.py`: при зажатой стрелке в логе должна
быть одна строка PRESS и одна RELEASE с большим промежутком между ними.
