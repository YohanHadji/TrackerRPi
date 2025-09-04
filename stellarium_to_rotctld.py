#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, time, socket, re, html
from math import fmod
import requests

def az_wrap_delta(target, current):
    # devuelve error más corto en [-180,+180)
    return ( (target - current + 540.0) % 360.0 ) - 180.0

def rot_set_pos(sock, az, el, read_reply=True):
    cmd = f"P {az:.2f} {el:.2f}\n".encode("ascii")
    sock.sendall(cmd)
    if read_reply:
        try:
            sock.settimeout(1.0)
            _ = sock.recv(128)
        except Exception:
            pass

def connect_rotctld(host, port, timeout=1.0):
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    return s

def parse_altaz_from_html(info_html):
    """
    Stellarium /api/objects/info devuelve un HTML corto (info del objeto).
    Buscamos una línea tipo "Az/Alt: 123.4  56.7" o con símbolos de grado.
    Para robustez, quitamos etiquetas y normalizamos espacios.
    """
    # quitar tags HTML
    txt = re.sub(r"<[^>]*>", " ", info_html)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()

    # Intento 1: "Az/Alt: <az> <el>" en decimales
    m = re.search(r"Az\s*/?\s*Alt[^:\d\-+]*[:=]\s*([\-+]?\d+(?:\.\d+)?)\D+([\-+]?\d+(?:\.\d+)?)", txt, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Intento 2: capturar dos números decimales cercanos a “Az/Alt”
    m = re.search(r"Az[^A-Za-z0-9]{0,8}Alt[^0-9\-+]*([\-+]?\d+(?:\.\d+)?)[^\d\-+]+([\-+]?\d+(?:\.\d+)?)", txt, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Si todo falla, lanzamos error
    raise ValueError("No pude extraer Az/Alt del HTML")

def get_altaz_stellarium(host="127.0.0.1", port=8090, name=None, timeout=1.0):
    """
    Si 'name' es None, usa el objeto actualmente seleccionado en Stellarium.
    Si 'name' está dado, consulta ese objeto por nombre (debe existir en Stellarium).
    """
    base = f"http://{host}:{port}/api/objects/info"
    params = {}
    if name:
        params["name"] = name
    r = requests.get(base, params=params, timeout=timeout)
    r.raise_for_status()
    return parse_altaz_from_html(r.text)

def main():
    ap = argparse.ArgumentParser(description="Puente Stellarium → rotctld (P az el)")
    ap.add_argument("--stel-host", default="127.0.0.1", help="Host del RemoteControl de Stellarium (default 127.0.0.1)")
    ap.add_argument("--stel-port", type=int, default=8090, help="Puerto del RemoteControl (default 8090)")
    ap.add_argument("--name", default=None, help="Nombre del objeto en Stellarium (si se omite, usa el objeto seleccionado)")
    ap.add_argument("--dt", type=float, default=0.2, help="Periodo de actualización en segundos (default 0.2)")
    ap.add_argument("--deadband", type=float, default=0.3, help="No enviar si el cambio |Δ| < deadband (deg) (default 0.3)")
    ap.add_argument("--min-el", type=float, default=5.0, help="Elevación mínima para mandar comandos (deg) (default 5)")
    ap.add_argument("--rot-host", default="127.0.0.1", help="Host de rotctld (default 127.0.0.1)")
    ap.add_argument("--rot-port", type=int, default=4533, help="Puerto de rotctld (default 4533)")
    ap.add_argument("--verbose", action="store_true", help="Logs verbosos")
    args = ap.parse_args()

    # Conexión a rotctld
    sock = None
    last_azel = (None, None)

    try:
        sock = connect_rotctld(args.rot_host, args.rot_port, timeout=1.0)
        if args.verbose:
            print(f"[INFO] Conectado a rotctld {args.rot_host}:{args.rot_port}")

        while True:
            try:
                az, el = get_altaz_stellarium(args.stel_host, args.stel_port, name=args.name, timeout=1.0)
                if args.verbose:
                    print(f"[OBS] az={az:.2f} el={el:.2f}")

                # Filtrar por elevación mínima
                if el < args.min_el:
                    if args.verbose:
                        print("[OBS] Debajo de min-el, no envío a rotador.")
                    time.sleep(args.dt)
                    continue

                laz, lel = last_azel
                send = False
                if laz is None:
                    send = True
                else:
                    d_az = abs(az_wrap_delta(az, laz))
                    d_el = abs(el - lel)
                    if (d_az > args.deadband) or (d_el > args.deadband):
                        send = True

                if send:
                    # enviar a rotctld
                    rot_set_pos(sock, az, el, read_reply=True)
                    last_azel = (az, el)
                    if args.verbose:
                        print(f"[CMD] P {az:.2f} {el:.2f}")

            except (requests.RequestException, ValueError) as e:
                if args.verbose:
                    print(f"[WARN] No pude leer/parsear Stellarium: {e}")
            except (socket.error, OSError) as e:
                if args.verbose:
                    print(f"[WARN] rotctld socket: {e}. Reintentando…")
                # reintento de conexión
                time.sleep(0.5)
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass
                sock = connect_rotctld(args.rot_host, args.rot_port, timeout=1.0)

            time.sleep(args.dt)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
