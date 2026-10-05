#!/usr/bin/env python3
"""game-cursor.py — курсор для игр на Zero 3W.

Рабочий стол рисует курсор «кометой» (cursor-comet.py): у неё шлейф, и диск кометы
уходит в сторону от настоящей точки указателя. В игре это мешает — например в меню
выбора оружия непонятно, куда именно попадёт клик.

Поведение:
  • на экране окно игры -> комета останавливается, включается game-pointer.py
    (точный прицел ровно в точке указателя, клики проходят сквозь него);
  • игр на экране нет   -> прицел выключается, комета возвращается как была.

Скрипт кометы не изменяется: сторож только запускает и останавливает процессы.

Запуск: game-cursor.py
Лог:    /tmp/game-cursor.log
"""
import os
import subprocess
import sys
import time

from Xlib import X, XK, display, protocol
from Xlib.ext import xtest

CURSOR_KEYS = ("KP_4", "KP_6", "KP_8", "KP_2")   # клавиши игрового курсора (мост)

COMET = "/home/orangepi/.local/bin/cursor-comet.py"
COMET_ARGS = ["--hide-cursor"]
POINTER = "/home/orangepi/.local/bin/game-pointer.py"
BRIDGE = "/home/orangepi/.local/bin/joy-to-keys.py"
GAMES = {"hedgewars", "hwengine", "warmux", "wormux", "retroarch", "supertux2", "0ad", "wa.exe"}
# Игры, которые ведут свой курсор сами (Worms Armageddon, класс wa.exe):
# указатель они перехватывают и центруют, поэтому комета висит на месте и мешает —
# в этом режиме комету убираем, а свой оверлей-прицел и мост клавиш не включаем.
OWN_CURSOR = {"wa.exe"}
POLL = 1.0          # период опроса, секунды
GRACE = 1           # секунд устойчивости перед переключением
LOG = "/tmp/game-cursor.log"


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


RECENTER_FLAG = "/tmp/m5hub-recenter"   # разрешение m5hub переносить указатель в центр
DIRECT_FLAG = "/tmp/m5hub-direct"       # прямой ход указателя без сглаживания (игры со своим курсором)
_recenter_flag = None                   # что выставлено сейчас (чтобы не дёргать диск зря)
_direct_flag = None


def sync_recenter_flag(need):
    """Разрешить m5hub переносить указатель в центр экрана у края.

    Перенос нужен только в матче: там курсор ведёт сама игра, а игровой мост
    читает прыжки указателя — без переноса движение «упирается в стенку». На
    рабочем столе и в меню перенос виден как прыжок курсора в центр, поэтому там
    он запрещён. m5hub проверяет наличие этого файла в цикле движения.
    """
    global _recenter_flag
    if _recenter_flag == need:
        return
    try:
        if need:
            with open(RECENTER_FLAG, "w") as f:
                f.write("%d\n" % os.getpid())
        else:
            if os.path.exists(RECENTER_FLAG):
                os.remove(RECENTER_FLAG)
        _recenter_flag = need
        log("перенос указателя у края: %s" % ("разрешён (матч)" if need else "запрещён"))
    except Exception as e:
        log("пометку переноса не удалось переключить: %r" % (e,))


def sync_direct_flag(need):
    """Прямой ход указателя без сглаживания — пока идёт игра со своим курсором.

    m5hub сглаживает движение (30% к цели за такт), на рабочем столе это плавность,
    а в игре читается как «курсор доигрывает прошлые движения» (Артём, 06.10.2026).
    Флаг включает в m5hub прямой ход; снимается, когда игра закрыта.
    """
    global _direct_flag
    if _direct_flag == need:
        return
    try:
        if need:
            with open(DIRECT_FLAG, "w") as f:
                f.write("%d\n" % os.getpid())
        else:
            if os.path.exists(DIRECT_FLAG):
                os.remove(DIRECT_FLAG)
        _direct_flag = need
        log("прямой ход указателя (без сглаживания): %s" % ("включён" if need else "выключен"))
    except Exception as e:
        log("пометку прямого хода не удалось переключить: %r" % (e,))


def walk(w, depth=0):
    """Обходим дерево окон: оконный менеджер заворачивает окно игры в рамку,
    поэтому класс игры виден только в глубине дерева."""
    yield w
    if depth >= 3:
        return
    try:
        for c in w.query_tree().children:
            yield from walk(c, depth + 1)
    except Exception:
        return


def game_windows(d):
    """Список окон игр, которые сейчас реально видны на экране."""
    out = []
    try:
        top = d.screen().root.query_tree().children
    except Exception:
        return out
    for t in top:
        for w in walk(t):
            try:
                at = w.get_attributes()
                if at.map_state != X.IsViewable:
                    continue
                cls = w.get_wm_class() or ()
                names = {str(c).lower() for c in cls}
                if names & GAMES:
                    geo = w.get_geometry()
                    # игровым считаем только окно, занимающее заметную часть экрана
                    if geo.width > 400 and geo.height > 300:
                        out.append((w.id, tuple(cls), geo.width, geo.height))
            except Exception:
                continue
    return out


def ensure_fullscreen(d, win_id, env):
    """Окно игры должно занимать весь экран.

    Двумя шагами: (1) просим у оконного менеджера настоящий полный экран;
    (2) проверяем факт — если окно всё равно стоит со сдвигом на рамку
    (заголовок съедает ~35 px снизу), сдвигаем его в угол экрана. Иначе нижняя
    полоса с кнопками уходит за край.
    """
    try:
        root = d.screen().root
        wm_state = d.intern_atom("_NET_WM_STATE")
        fs = d.intern_atom("_NET_WM_STATE_FULLSCREEN")
        win = d.create_resource_object("window", win_id)
        ev = protocol.event.ClientMessage(window=win, client_type=wm_state,
                                          data=(32, [1, fs, 0, 1, 0]))
        root.send_event(ev,
                        event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.flush()
    except Exception as e:
        log("полный экран не удался: %r" % (e,))

    try:
        res = subprocess.run(["xdotool", "getwindowgeometry", str(win_id)],
                             capture_output=True, text=True, env=env)
        pos = ""
        for line in res.stdout.splitlines():
            if "Position:" in line:
                pos = line.split("Position:")[1].strip().split()[0]
        if pos and pos != "0,0":
            subprocess.run(["xdotool", "windowmove", str(win_id), "0", "0"],
                           capture_output=True, env=env)
            log("окно %s сдвинуто в угол экрана (было %s)" % (win_id, pos))
    except Exception as e:
        log("сдвиг окна не удался: %r" % (e,))


def pids_of(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def kill_by_pattern(pattern):
    for p in pids_of(pattern):
        subprocess.run(["kill", str(p)], capture_output=True)


def start_pointer(env):
    if pids_of(POINTER):
        return
    subprocess.Popen([sys.executable, POINTER], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    log("включён точный курсор игры")


def stop_pointer():
    kill_by_pattern(POINTER)
    log("точный курсор игры выключен")


def start_comet(env):
    if pids_of(COMET):
        return
    subprocess.Popen([sys.executable, COMET] + COMET_ARGS,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env=env)
    log("комета возвращена (рабочий стол)")


def start_bridge(env):
    """В матче: игра ведёт свой курсор, движения указателя она не видит, но клавиши
    перемещения курсора принимает — поэтому переводим движение джойстика в клавиши."""
    if pids_of(BRIDGE):
        return
    subprocess.Popen([sys.executable, BRIDGE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env=env)
    log("включён мост «джойстик → клавиши курсора»")


def release_cursor_keys():
    """Отпустить клавиши игрового курсора после остановки моста.

    Если мост убит ровно между нажатием и отпусканием, клавиша остаётся
    «зажатой» в X: сервер повторяет её сам ~30 раз в секунду, и в приложении это
    выглядит как бесконечная прокрутка (поймано 24.09.2026 — зажатый KP_Down).
    Снимается только явным KeyRelease, перезапуск драйвера не помогает.
    """
    try:
        d = display.Display()
        for name in CURSOR_KEYS:
            code = d.keysym_to_keycode(XK.string_to_keysym(name))
            if code:
                xtest.fake_input(d, X.KeyRelease, code)
        d.sync()
    except Exception as e:
        log("клавиши курсора не отпустились: %r" % (e,))


def stop_bridge():
    kill_by_pattern(BRIDGE)
    time.sleep(0.2)     # дать процессу уйти, чтобы отпускание не спорило с его нажатием
    release_cursor_keys()


def is_engine_window(wins):
    """Матч (движок hwengine) или фронтенд (меню, hedgewars)."""
    for _wid, cls, _w, _h in wins:
        if {str(c).lower() for c in cls} & {"hwengine"}:
            return True
    return False


def is_own_cursor_window(wins):
    """Игра с собственным курсором (Worms): она сама рисует и ведёт указатель."""
    for _wid, cls, _w, _h in wins:
        if {str(c).lower() for c in cls} & OWN_CURSOR:
            return True
    return False


def main():
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    d = display.Display()
    mode = "none"          # none | frontend (меню игры) | engine (матч)
    pending_mode = None
    pending_since = None
    tick_n = 0
    log("старт: слежу за играми " + ", ".join(sorted(GAMES)))

    while True:
        try:
            wins = game_windows(d)
            engine = is_engine_window(wins)
            own = is_own_cursor_window(wins)
            want_mode = ("engine" if engine else
                         "owncursor" if own else
                         "frontend" if wins else "none")

            if want_mode != mode:
                # режим хочет измениться — ждём GRACE секунд устойчивости
                if pending_mode != want_mode:
                    pending_mode = want_mode
                    pending_since = time.time()
                elif time.time() - pending_since >= GRACE:
                    if want_mode == "engine":
                        # ИДЁТ МАТЧ: игра ведёт свой курсор и не видит движение указателя,
                        # сделанное виртуально. Комету и оверлей убираем, движение
                        # джойстика переводим в клавиши игрового курсора.
                        kill_by_pattern(COMET)
                        stop_pointer()
                        start_bridge(env)
                        log("МАТЧ %s — курсор игры + мост клавиш" % (wins[0][1],))
                    elif want_mode == "owncursor":
                        # ИГРА СО СВОИМ КУРСОРОМ (Worms Armageddon): указатель она
                        # перехватывает и центрует, курсор ведёт и рисует сама —
                        # оставляем только её курсор: комету, оверлей и мост выключаем.
                        kill_by_pattern(COMET)
                        stop_pointer()
                        stop_bridge()
                        log("ИГРА %s — курсор ведёт игра, комета убрана" % (wins[0][1],))
                    elif want_mode == "frontend":
                        # МЕНЮ игры: мышь и джойстик тут работают сами, а оверлей-прицел
                        # только мешал — оставляем комету, как было раньше.
                        stop_bridge()
                        stop_pointer()
                        start_comet(env)
                        for wid, cls, gw, gh in wins:
                            ensure_fullscreen(d, wid, env)
                        log("МЕНЮ игры %s — комета, мост выключен" % (wins[0][1],))
                    else:
                        stop_bridge()
                        stop_pointer()
                        start_comet(env)
                        log("рабочий стол — комета вернулась")
                    mode = want_mode
                    pending_mode = None
            else:
                pending_mode = None
                # присмотр: если нужный компонент умер — поднимаем его заново
                if mode == "engine":
                    if not pids_of(BRIDGE):
                        log("мост пропал — поднимаю заново")
                        start_bridge(env)
                    if pids_of(COMET):
                        kill_by_pattern(COMET)
                    if pids_of(POINTER):
                        stop_pointer()
                    if tick_n % 5 == 0:      # раз в ~5 с подтверждаем полный экран
                        for wid, cls, gw, gh in wins:
                            ensure_fullscreen(d, wid, env)
                elif mode == "owncursor":
                    # присмотр для игры со своим курсором: комета должна быть снята,
                    # оверлей и мост — выключены
                    if pids_of(COMET):
                        kill_by_pattern(COMET)
                    if pids_of(POINTER):
                        stop_pointer()
                    if pids_of(BRIDGE):
                        stop_bridge()
                elif mode == "frontend":
                    if not pids_of(COMET):
                        log("комета пропала — поднимаю заново")
                        start_comet(env)
                    if pids_of(BRIDGE):
                        stop_bridge()
                    if pids_of(POINTER):
                        stop_pointer()
                else:
                    if not pids_of(COMET):
                        log("комета пропала — поднимаю заново")
                        start_comet(env)
                    if pids_of(BRIDGE):
                        stop_bridge()
                    if pids_of(POINTER):
                        stop_pointer()
                tick_n += 1
            # перенос указателя у края разрешаем только в матче
            sync_recenter_flag(mode == "engine")
            # прямой ход указателя (без сглаживания) — только в игре со своим курсором
            sync_direct_flag(mode == "owncursor")
        except Exception as e:
            log("ошибка: %r" % (e,))
        time.sleep(POLL)


def _cleanup_flag(*_):
    """Снять пометки: с ними m5hub переносит указатель в центр и ходит без сглаживания."""
    for flag in (RECENTER_FLAG, DIRECT_FLAG):
        try:
            if os.path.exists(flag):
                os.remove(flag)
        except Exception:
            pass


if __name__ == "__main__":
    import signal
    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(_sig, lambda *_: (_cleanup_flag(), os._exit(0)))
        except Exception:
            pass
    try:
        main()
    finally:
        _cleanup_flag()
