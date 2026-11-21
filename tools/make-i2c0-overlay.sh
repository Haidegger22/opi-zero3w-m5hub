#!/bin/bash
# Собирает и устанавливает оверлей i2c0 для Orange Pi 4 Pro (A733, sun60i-a733).
#
# Зачем: в образе лежат только оверлеи i2c3 (sun60i-a733-i2c3.dtbo и
# sun60i-t736-i2c3.dtbo), а i2c0 — та шина, что выведена на пины 3 (SDA) и
# 5 (SCL) гребёнки, куда подключается CardKB. U-Boot собирает имя файла как
# ${overlay_prefix}-${overlay_file}.dtbo, поэтому нужен ровно
# /boot/dtb/allwinner/overlay/sun60i-a733-i2c0.dtbo.
#
# Использование: sudo bash tools/make-i2c0-overlay.sh [--dry-run]
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

OVERLAY_DIR=/boot/dtb/allwinner/overlay
BASE_DTB=/boot/dtb/allwinner/sun60i-a733-orangepi-4-pro.dtb
ENV_FILE=/boot/orangepiEnv.txt
NAME=sun60i-a733-i2c0.dtbo
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

for f in dtc fdtoverlay; do
    command -v "$f" >/dev/null || { echo "нет $f — установите device-tree-compiler" >&2; exit 1; }
done

[ -f "$BASE_DTB" ] || { echo "не найден $BASE_DTB" >&2; exit 1; }

cat > "$WORK/i2c0.dts" <<'EOF'
/dts-v1/;

/ {
	fragment@0 {
		target = <0xffffffff>;

		__overlay__ {
			status = "okay";
		};
	};

	__fixups__ {
		twi0 = "/fragment@0:target:0";
	};
};
EOF

dtc -@ -I dts -O dtb -o "$WORK/$NAME" "$WORK/i2c0.dts"
fdtoverlay -i "$BASE_DTB" -o "$WORK/check.dtb" "$WORK/$NAME"
st=$(fdtget -t s "$WORK/check.dtb" /soc@3000000/twi@2510000 status 2>/dev/null || true)
[ "$st" = "okay" ] || { echo "оверлей не включает twi0 (status=$st)" >&2; exit 1; }
echo "оверлей собран и проверен: twi0 status=okay"

if [ "$DRY" = 1 ]; then
    echo "dry-run: в систему ничего не копировал"
    exit 0
fi

install -m 644 "$WORK/$NAME" "$OVERLAY_DIR/$NAME"

if grep -q '^overlays=' "$ENV_FILE"; then
    cp -a "$ENV_FILE" "$ENV_FILE.bak-i2c0-$(date +%Y%m%d-%H%M)"
    sed -i 's/^overlays=.*/overlays=i2c0/' "$ENV_FILE"
else
    cp -a "$ENV_FILE" "$ENV_FILE.bak-i2c0-$(date +%Y%m%d-%H%M)"
    echo 'overlays=i2c0' >> "$ENV_FILE"
fi

echo "установлено: $OVERLAY_DIR/$NAME"
echo "в $ENV_FILE прописано overlays=i2c0"
echo
echo "дальше: sudo reboot, затем"
echo "  ls /dev/i2c-0 && sudo i2cdetect -y 0   # ожидается 5f"
