#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_rate_meter.py — Mide velocidades angulares (deg/s) leyendo de rotctld.
Robusto contra respuestas 'RPRT ...' y timeouts ocasionales.
"""

import socket, time, argparse

HOST, PORT = "127.0.0.1", 4533

def shortest_deg(a, b):
    return (b - a + 540.0) % 360.0 - 180.0

def send_line(s, line):
    s.sendall((line.rstrip("\r\n") + "\n").encode("ascii"))

def read_line(s, timeout=1.0):
    s.settimeout(timeout)
    buf = bytearray()
    while True:
        ch = s.recv(1)
        if not ch:
            raise TimeoutError("socket closed")
        buf += ch
        if ch == b"\n":
            break
    return buf.decode("ascii", "ignore").strip()

def handshake(s):
    """Drena estado y deja el canal 'limpio'."""
    send_line(s, "dump_state")
    t0 = time.time()
    while time.time() - t0 < 1.0:
        try:
            ln = read_line(s, 0.2)
            if ln.startswith("RPRT"):
                break
        except TimeoutError:
            break

def read_number_line(s, timeout=1.0, retries=6):
    """Lee líneas hasta encontrar un float; ignora 'RPRT ...' o vacías."""
    for _ in range(retries):
        ln = read_line(s, timeout)
        if not ln:
            continue
        if ln.startswith("RPRT"):
            # ignoramos códigos de estado; si no es 0, damos un respiro
            if ln != "RPRT 0":
                time.sleep(0.02)
            continue
        try:
            return float(ln)
        except ValueError:
            # Línea inesperada: seguir leyendo
            continue
    raise TimeoutError("no numeric line found")

def get_pos(s, timeout=1.0):
    """Envía 'p' y devuelve (az, el). Ignora líneas 'RPRT ...'."""
    send_line(s, "p")
    az = read_number_line(s, timeout)
    el = read_number_line(s, timeout)
    # puede venir un 'RPRT 0' adicional; drenarlo sin bloquear
    try:
        ln = read_line(s, 0.02)
        # si no era un RPRT, lo dejamos pasar para la próxima lectura
    except Exception:
        pass
    return az, el

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--dt", type=float, default=0.1, help="periodo de muestreo (s)")
    ap.add_argument("--dur", type=float, default=0.0, help="duración total (0=sin fin)")
    args = ap.parse_args()

    s = socket.create_connection((args.host, args.port), timeout=2.0)
    try:
        handshake(s)
        # primer punto
        az0, el0 = get_pos(s, 1.0)
        t0 = time.time()
        last_t, last_az, last_el = t0, az0, el0

        print("# t(s)   AZ     EL     vAZ(deg/s)  vEL(deg/s)")
        print(f"{0:6.2f}  {az0:6.2f}  {el0:6.2f}   {0:10.3f}  {0:10.3f}")

        while True:
            if args.dur and (time.time() - t0) > args.dur:
                break

            try:
                az, el = get_pos(s, 1.0)
            except Exception:
                # re-sincroniza y salta una muestra sin romper el programa
                try:
                    handshake(s)
                except Exception:
                    pass
                time.sleep(max(0.0, args.dt))
                continue

            t = time.time()
            dt = max(1e-3, t - last_t)
            vaz = shortest_deg(last_az, az) / dt
            vel = (el - last_el) / dt
            print(f"{t - t0:6.2f}  {az:6.2f}  {el:6.2f}   {vaz:10.3f}  {vel:10.3f}")

            last_t, last_az, last_el = t, az, el

            # duerme para clavar el periodo
            nxt = last_t + args.dt
            time.sleep(max(0.0, nxt - time.time()))
    finally:
        s.close()

if __name__ == "__main__":
    main()
