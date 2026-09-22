#!/bin/bash
# Прошивка CardKB (ATmega8) через Raspberry Pi 5. Проверено 22.09.2026.
#
# Подключение (проверенная раскладка, НЕ совпадает с логикой схемы по MISO/MOSI):
#   площадка 1 (квадратная) -> пин 1  (3,3 В)      питание
#   площадка 2              -> пин 11 (GPIO17)     RST
#   площадка 3              -> пин 13 (GPIO27)     SCK
#   площадка 5              -> пин 16 (GPIO23)     MOSI
#   площадка 4              -> пин 15 (GPIO22)     MISO
#   площадка 6              -> пин 39 (GND)        земля
#
# Требуется avrdude с поднятым PIN_MAX (см. tools/avrdude-pinmax.patch) —
# иначе он отвергает номера линий больше 400, а на Pi 5 база GPIO = 569.
#
# Использование:  sudo bash flash_cardkb_pi5.sh <файл.hex>
# Без аргумента перебирает комбинации и только читает сигнатуру (ничего не пишет).

set -u
AVRDUDE="${AVRDUDE:-$HOME/avrdude-lgpio/bin/avrdude}"
BASE_CONF="${BASE_CONF:-$HOME/avrdude-lgpio/etc/avrdude.conf}"
CONF=/tmp/cardkb_flash.conf
BACKUP="$HOME/cardkb-original.bin"
HEX="${1:-}"

# sysfs-номера (база RP1 = 569): GPIO17->586, GPIO27->596, GPIO22->591, GPIO23->592
RST=586
SCK=596
MISO=591      # пин 15
MOSI=592      # пин 16
DUMMY_RESET=594   # свободная линия: драйвер сброс не подаёт, держим его сами

mkdir -p "$(dirname "$CONF")"

make_conf() {   # $1 = sck, $2 = mosi(sdo), $3 = miso(sdi)
  cp "$BASE_CONF" "$CONF"
  cat >> "$CONF" <<EOF

programmer
    id    = "cardkb";
    desc  = "CardKB via Pi5 GPIO (reset удерживается вручную)";
    type  = "linuxgpio";
    reset = $DUMMY_RESET;
    sck   = $1;
    sdo   = $2;
    sdi   = $3;
;
EOF
}

cleanup() {
  for f in /sys/class/gpio/gpio5*; do
    n=$(basename "$f" | sed 's/gpio//')
    if [ -d "$f" ] && [ "$n" != "gpiochip569" ] && [ "$n" != "$RST" ]; then
      echo "$n" > /sys/class/gpio/unexport 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT

echo "=== Держу линию сброса (пин 11 = sysfs $RST) в нуле"
echo "$RST" > /sys/class/gpio/export 2>/dev/null || true
echo out > "/sys/class/gpio/gpio$RST/direction"
echo 0   > "/sys/class/gpio/gpio$RST/value"
sleep 0.5

# ── Перебор комбинаций: ищем ту, на которой микросхема отвечает ──
FOUND=""
echo
echo "=== Ищу рабочую комбинацию сигналов"
for sck in 596 591 592; do for sdo in 596 591 592; do for sdi in 596 591 592; do
  [ "$sck" = "$sdo" ] || [ "$sck" = "$sdi" ] || [ "$sdo" = "$sdi" ] && continue
  make_conf "$sck" "$sdo" "$sdi"
  OUT=$(timeout 25 "$AVRDUDE" -C "$CONF" -c cardkb -p m8 -F -B 60 -U signature:r:-:h 2>&1)
  if echo "$OUT" | grep -q "0x1e93"; then
    echo "    SCK=$sck MOSI=$sdo MISO=$sdi  ->  ОТВЕЧАЕТ (0x1e9307, ATmega8)"
    FOUND="$sck $sdo $sdi"
    cp "$CONF" "${HOME}/avrdude-lgpio/etc/avrdude-cardkb.conf"
    break 3
  else
    echo "    SCK=$sck MOSI=$sdo MISO=$sdi  ->  нет ответа"
  fi
  for f in /sys/class/gpio/gpio5*; do
    n=$(basename "$f" | sed 's/gpio//')
    [ -d "$f" ] && [ "$n" != "gpiochip569" ] && [ "$n" != "$RST" ] && echo "$n" > /sys/class/gpio/unexport 2>/dev/null
  done
done; done; done

if [ -z "$FOUND" ]; then
  echo
  echo "=== НИ ОДНА КОМБИНАЦИЯ НЕ ОТВЕЧАЕТ. Ничего не записано."
  echo "    Проверить: питание 3,3 В на площадке 1, землю на площадке 6,"
  echo "    и что линия сброса действительно в нуле (pinctrl get 17)."
  exit 1
fi

CONF_USE="${HOME}/avrdude-lgpio/etc/avrdude-cardkb.conf"

if [ -z "$HEX" ]; then
  echo
  echo "=== Сигнатура прочитана, файл прошивки не задан — только проверка. Запись не выполнялась."
  exit 0
fi

if [ ! -f "$HEX" ]; then
  echo "=== Нет файла прошивки: $HEX"; exit 1
fi

echo
echo "=== Сохраняю родную прошивку в $BACKUP"
timeout 60 "$AVRDUDE" -C "$CONF_USE" -c cardkb -p m8 -B 60 -U flash:r:"$BACKUP":r 2>&1 | grep -E "Reading|error" | sed 's/^/    /'
if [ "$(stat -c%s "$BACKUP" 2>/dev/null || echo 0)" -lt 1000 ]; then
  echo "    ОШИБКА: копия не сохранилась, новую прошивку НЕ пишу."; exit 1
fi
ls -la "$BACKUP" | awk '{print "    сохранено: "$5" байт"}'

echo
echo "=== Записываю $HEX"
timeout 90 "$AVRDUDE" -C "$CONF_USE" -c cardkb -p m8 -B 60 -U flash:w:"$HEX":i 2>&1 | grep -E "Writing|error|verified|bytes" | sed 's/^/    /'

echo
echo "=== Сверяю записанное с файлом"
timeout 60 "$AVRDUDE" -C "$CONF_USE" -c cardkb -p m8 -B 60 -U flash:v:"$HEX":i 2>&1 | tail -3 | sed 's/^/    /'

echo
echo "=== Отпускаю сброс"
echo "$RST" > /sys/class/gpio/unexport 2>/dev/null || true
echo "    ГОТОВО. Родная прошивка сохранена в $BACKUP"
