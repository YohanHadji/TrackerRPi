#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puente Easycomm-II por PTY -> tracker_goto_safe.py
- Crea un puerto serie virtual (PTY) con protocolo Easycomm-II.
- rotctld (Hamlib) se conectará a este PTY con -m 202 (easycommII).
- Comandos soportados:
    * C / C2 / C?     -> devuelve "AZ <v> EL <v>"
    * "AZ EL"         -> devuelve "AZ <v> EL <v>"
    * "AZ<val> EL<val>" -> fija objetivo (OK)
    * "S"             -> stop (OK)
"""

import os
import pty
import tty
import termios
import fcntl
import select
import re
import threading
import time
import sys
import math, time

# === Importa el controlador del tracker ===
import tracker_goto_safe as T
from tracker_goto_safe import get_tracker_pose, goto_abs_safe, send_stop, send_enable

# ===================== Ajustes / Tuning =====================
DEBUG_IO        = True     # ponlo en False cuando termines de ajustar
SLEEP_BETWEEN   = 0.10     # pausa entre iteraciones del guiado (s)

#KP        = 14.0
#BASE_GAIN = 25.0
#V_MAX     = 6.0
#MAX_CMD   = 200
#DCMD_MAX  = 40
#TOL             = 0.35     # tolerancia fina final (deg)
# Perfil “óptico” (suave)
KP = 9.0            # antes 14.0
BASE_GAIN = 18.0    # antes 25.0
V_MAX = 3.0         # antes 6.0 (deg/s)
MAX_CMD = 120       # antes 200
DCMD_MAX = 15       # antes 40
TOL = 0.20          # fina pero sin nervios


# Tiempos dinámicos según distancia (para evitar “micro-paradas”)
SLEW_DEG_PER_SEC = 6.5     # velocidad angular aprox (ajusta a tu mecánica real)
TIME_SAFETY      = 1.35    # margen de seguridad
MIN_STEP_TIME    = 1.5     # s
MAX_STEP_TIME    = 60.0    # s (trayectos largos)

# Suavizado del setpoint enviado por Gpredict
SMOOTH_TAU = 0.35     # s (constante de tiempo del filtro 1er orden)
MAX_RATE_AZ = 8.0     # deg/s (límite de velocidad deseada en AZ)
MAX_RATE_EL = 5.0     # deg/s (límite en EL)

_last_sp = {'az': None, 'el': None, 't': 0.0}

# Heurística de casi-wrap en AZ (0/360)
CROSS_EPS        = 5.0     # si el camino corto <5° pero el delta bruto >180°, asumimos camino largo

# Symlink estable para que rotctld tenga una ruta fija
STABLE_LINK      = "/run/rotor_pty"
# ============================================================

# Estado compartido
last_pose   = [0.0, 0.0]           # cache rápido (az, el)
target_lock = threading.Lock()
target      = None                 # (az, el)
running     = True

def _shortest_angle(d):
    # devuelve diferencia envuelta a [-180, +180)
    return ((d + 180.0) % 360.0) - 180.0

def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def smooth_target(taz, tel):
    """Filtro 1º orden + limitador de velocidad para el setpoint."""
    now = time.monotonic()
    paz = _last_sp['az']
    pel = _last_sp['el']
    if paz is None:
        _last_sp.update({'az': taz % 360.0, 'el': tel, 't': now})
        return taz % 360.0, tel

    dt = max(1e-3, now - _last_sp['t'])

    # 1) Low-pass hacia el nuevo objetivo
    alpha = 1.0 - math.exp(-dt / SMOOTH_TAU)
    az_lp = paz + alpha * _shortest_angle(taz - paz)
    el_lp = pel + alpha * (tel - pel)

    # 2) Limitador de velocidad (rampa)
    az_step = _clamp(_shortest_angle(az_lp - paz), -MAX_RATE_AZ * dt, MAX_RATE_AZ * dt)
    el_step = _clamp(el_lp - pel,                     -MAX_RATE_EL * dt, MAX_RATE_EL * dt)

    az = (paz + az_step) % 360.0
    el =  pel + el_step

    _last_sp.update({'az': az, 'el': el, 't': now})
    return az, el
# === Listener único de telemetría (evita EADDRINUSE) ===
_listener_once = False

def ensure_listener_once():
    """Arranca un ÚNICO listener de telemetría y neutraliza el interno."""
    global _listener_once
    if _listener_once:
        return

    def _run():
        try:
            # === IMPORTANTE ===
            # Escuchar telemetría desde el HUB (fanout #3):
            #   bind_ip: 127.0.0.1
            #   port:    9003
            T._listen_capsules(bind_ip="127.0.0.1", port=9003)
        except OSError as e:
            # 98 = Address already in use (puerto ocupado)
            if getattr(e, "errno", None) != 98:
                print(f"[TELEM] listener error: {e}", flush=True)

    threading.Thread(target=_run, daemon=True).start()
    # Desactiva el lanzador interno de goto_abs_safe (para que NO intente bindear de nuevo)
    T._listen_capsules = lambda *a, **k: None
    _listener_once = True

# === Timeout dinámico por distancia efectiva ===
def compute_step_time(dist_deg: float) -> float:
    """Devuelve un timeout adecuado para goto_abs_safe según distancia angular."""
    t = (dist_deg / max(SLEW_DEG_PER_SEC, 0.1)) * TIME_SAFETY
    if t < MIN_STEP_TIME:
        t = MIN_STEP_TIME
    elif t > MAX_STEP_TIME:
        t = MAX_STEP_TIME
    return t

def set_target(az: float, el: float):
    """Actualiza el objetivo del guiado."""
    global target
    with target_lock:
        target = (float(az), float(el))
    if DEBUG_IO:
        print(f"[GUIDE] nuevo target: az={az:.2f} el={el:.2f}", flush=True)

def guidance_loop():
    """Persigue 'target' con pasos de duración dinámica + suavizado de setpoint."""
    ensure_listener_once()   # evita que goto_abs_safe intente abrir otro listener
    send_enable(True)
    print("[GUIDE] hilo de guiado ACTIVO", flush=True)
    try:
        while running:
            # Lee objetivo actual
            with target_lock:
                tgt = target

            # Lee pose (si no hay telemetría nueva, usa el cache last_pose)
            try:
                az, el = get_tracker_pose(wait=False, timeout=0.05)
                if az is None or el is None:
                    raise RuntimeError("no telemetry")
                last_pose[0], last_pose[1] = az, el
            except Exception:
                az, el = last_pose

            if not tgt:
                time.sleep(0.05)
                continue

            # Objetivo crudo que viene de Gpredict
            taz_raw, tel_raw = tgt

            # Suavizado + limitador de velocidad (convierte escalones en rampa)
            taz, tel = smooth_target(taz_raw, tel_raw)

            # Error envuelto en AZ
            e_az = (taz - az + 540.0) % 360.0 - 180.0
            e_el = (tel - el)
            dist = (e_az * e_az + e_el * e_el) ** 0.5

            # Log
            print(
                f"[GUIDE] cur=({az:.2f},{el:.2f}) "
                f"tgtSm=({taz:.2f},{tel:.2f}) "
                f"err=({e_az:.2f},{e_el:.2f}) d={dist:.2f}",
                flush=True
            )

            # Si ya estamos dentro de tolerancia fina, no hagas nada
            if dist <= TOL:
                time.sleep(0.05)
                continue

            # Tolerancia: laxa si estamos lejos, fina al final
            tol_here = 0.8 if dist > 8.0 else TOL

            # Timeout dinámico según distancia
            step_timeout = compute_step_time(dist)

            try:
                goto_abs_safe(
                    taz, tel,
                    base_gain=BASE_GAIN, kp=KP, vmax=V_MAX,
                    max_cmd=MAX_CMD, dcmd_max=DCMD_MAX,
                    timeout=step_timeout,
                    tol_deg=tol_here,
                    verbose=False
                )
            except Exception as e:
                print(f"[GUIDE] goto_abs_safe error: {e}", flush=True)

            time.sleep(SLEEP_BETWEEN)
    finally:
        try:
            send_stop()
        except Exception:
            pass
        send_enable(False)
        print("[GUIDE] hilo de guiado DETENIDO", flush=True)

def start_guidance():
    t = threading.Thread(target=guidance_loop, daemon=True)
    t.start()
    return t

# ===================== Easycomm-II helpers =====================
_re_set = re.compile(r"\s*AZ\s*([+-]?\d+(?:\.\d+)?)\s*(?:EL\s*([+-]?\d+(?:\.\d+)?))?", re.I)
_re_get = re.compile(r"^\s*AZ\s*EL\s*$", re.I)  # “AZ EL” (sin números) = get pos

def handle_line(cmd: str, write_fn):
    """
    Easycomm-II mínimo para Hamlib:
      - "C", "C2", etc.        -> responder "AZ <v> EL <v>\r\n"
      - "AZ EL" (sin números)  -> responder "AZ <v> EL <v>\r\n"
      - "AZ<v> EL<v>"          -> set pos (responder "OK\r\n")
      - "S"                    -> stop (responder "OK\r\n")
      - otros                  -> "OK\r\n" (benigno)
    """
    raw = cmd
    cmd = cmd.strip()
    if DEBUG_IO:
        print(f"[EC RX] {raw!r}", flush=True)
    if not cmd:
        return

    up = cmd.upper()

    # --- GET POS (C, C2, etc.) ---
    if up.startswith("C"):
        try:
            az, el = get_tracker_pose(wait=False, timeout=0.05)
            if az is None or el is None:
                raise RuntimeError("no telemetry")
            last_pose[0], last_pose[1] = az, el
        except Exception:
            az, el = last_pose
        resp = f"AZ {az:.1f} EL {el:.1f}\r\n"
        if DEBUG_IO:
            print(f"[EC TX] {resp.strip()}", flush=True)
        write_fn(resp)
        return

    # --- GET POS (AZ EL sin números) ---
    if _re_get.match(cmd):
        try:
            az, el = get_tracker_pose(wait=False, timeout=0.05)
            if az is None or el is None:
                raise RuntimeError("no telemetry")
            last_pose[0], last_pose[1] = az, el
        except Exception:
            az, el = last_pose
        resp = f"AZ {az:.1f} EL {el:.1f}\r\n"
        if DEBUG_IO:
            print(f"[EC TX] {resp.strip()}", flush=True)
        write_fn(resp)
        return

    # --- STOP ---
    if up == "S":
        try:
            send_stop()
        except Exception:
            pass
        if DEBUG_IO:
            print("[EC TX] OK", flush=True)
        write_fn("OK\r\n")
        return

    # --- SET POS (AZ... EL...) ---
    m = _re_set.match(cmd)
    if m:
        try:
            az = float(m.group(1))
            el = float(m.group(2)) if m.group(2) is not None else None
            if el is not None:
                set_target(az, el)
            if DEBUG_IO:
                print("[EC TX] OK", flush=True)
            write_fn("OK\r\n")
            return
        except Exception:
            if DEBUG_IO:
                print("[EC TX] ERR", flush=True)
            write_fn("ERR\r\n")
            return

    # --- fallback ---
    if DEBUG_IO:
        print("[EC TX] OK", flush=True)
    write_fn("OK\r\n")

# ===================== utilidades PTY =====================
def make_nonblocking(fd: int):
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

# ===================== main =====================
def main():
    # Listener único
    ensure_listener_once()

    # Crea PTY (lado “serie” donde se conectará rotctld)
    master_fd, slave_fd = pty.openpty()

    # Raw, 8N1
    attrs = termios.tcgetattr(slave_fd)
    tty.setraw(slave_fd)
    attrs[2] = attrs[2] | termios.CLOCAL | termios.CREAD
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    slave_name = os.ttyname(slave_fd)

    # Symlink estable
    try:
        if os.path.islink(STABLE_LINK) or os.path.exists(STABLE_LINK):
            os.unlink(STABLE_LINK)
        os.symlink(slave_name, STABLE_LINK)
    except Exception:
        pass

    print(f"[easycomm-pty] PTY listo en: {slave_name}")
    print(f"[easycomm-pty] Enlace estable: {STABLE_LINK}")
    sys.stdout.flush()

    make_nonblocking(master_fd)

    # Lanza el guiado
    _ = start_guidance()

    # Bucle E/S Easycomm-II
    rx_buf = bytearray()
    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.1)
            if master_fd in r:
                try:
                    data = os.read(master_fd, 4096)
                except BlockingIOError:
                    data = b""
                if not data:
                    time.sleep(0.01)
                    continue

                rx_buf += data
                # Separar por CR/LF
                while b"\n" in rx_buf or b"\r" in rx_buf:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        if sep in rx_buf:
                            line, rx_buf[:] = rx_buf.split(sep, 1)
                            break
                    line = line.decode("ascii", "ignore")
                    def w(s: str):
                        os.write(master_fd, s.encode("ascii", "ignore"))
                    handle_line(line, w)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
