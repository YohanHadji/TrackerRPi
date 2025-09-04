#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Track de satélite (Skyfield) -> rotctld (Hamlib NET rotctl)
- Lee un TLE (nombre + dos líneas).
- Calcula AZ/EL para tu sitio con Skyfield / SGP4.
- Envía "P <az> <el>" por TCP al rotctld (puente Easycomm) con deadband.

Requisitos:
  pip install --user --break-system-packages skyfield sgp4

Ejemplo:
  python3 track_skyfield_rotctld.py --tle-file ~/iss.tle \
    --sat "ISS (ZARYA)" \
    --lat -34.6037 --lon -58.3816 --alt 25 \
    --dt 0.2 --min-el 5 --deadband 0.2 \
    --host 127.0.0.1 --port 4533
"""

import argparse
import socket
import sys
import time
from math import fmod

from skyfield.api import EarthSatellite, load, wgs84

# ------------------------- utilidades TLE -------------------------

def load_first_sat_from_tle(path, sat_name=None):
    """
    Lee un archivo TLE (formato clásico: NOMBRE / L1 / L2 (repetido)).
    Devuelve EarthSatellite de la primera coincidencia por nombre,
    o el primero del archivo si sat_name es None.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = [ln.strip() for ln in f.read().strip().splitlines() if ln.strip()]

    triples = []
    i = 0
    while i < len(raw) - 2:
        # Caso 1: name + (1 ...) + (2 ...)
        if raw[i+1].startswith("1 ") and raw[i+2].startswith("2 "):
            name, l1, l2 = raw[i], raw[i+1], raw[i+2]
            triples.append((name, l1, l2))
            i += 3
        # Caso 2: sin nombre, solo 1/2 (poco común); damos nombre genérico
        elif raw[i].startswith("1 ") and raw[i+1].startswith("2 "):
            idx = len(triples) + 1
            name, l1, l2 = f"SAT_{idx}", raw[i], raw[i+1]
            triples.append((name, l1, l2))
            i += 2
        else:
            i += 1

    if not triples:
        raise RuntimeError(f"No se encontraron TLE válidos en {path}")

    ts = load.timescale()
    sats = []
    for name, l1, l2 in triples:
        try:
            sats.append(EarthSatellite(l1, l2, name=name, ts=ts))
        except Exception as e:
            print(f"[WARN] TLE inválido '{name}': {e}", file=sys.stderr)

    if not sats:
        raise RuntimeError("Ningún TLE pudo cargarse (todos inválidos).")

    if sat_name:
        for s in sats:
            if s.name.strip().lower() == sat_name.strip().lower():
                return s, ts
        print(f"[WARN] No se encontró '{sat_name}'. Usando el primero del archivo.", file=sys.stderr)

    return sats[0], ts

# ------------------------- cliente rotctld -------------------------

class RotctlClient:
    """Cliente muy simple para rotctld (Hamlib NET rotctl)."""
    def __init__(self, host="127.0.0.1", port=4533, timeout=1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        if self.sock:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self.sock = s

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def send_cmd(self, line: str, expect_reply=False):
        """Envía una línea (con \\n). Si expect_reply, intenta leer una línea."""
        if not self.sock:
            self.connect()
        data = (line.rstrip("\r\n") + "\n").encode("ascii", "ignore")
        self.sock.sendall(data)
        if not expect_reply:
            return None
        try:
            buff = b""
            t0 = time.time()
            while time.time() - t0 < self.timeout:
                chunk = self.sock.recv(256)
                if not chunk:
                    break
                buff += chunk
                if b"\n" in buff:
                    break
            return buff.decode(errors="ignore").strip()
        except Exception:
            return None

    def set_pos(self, az_deg: float, el_deg: float):
        """Comando 'P az el' absoluto (Hamlib)."""
        # Normalizá a 0..360 para az y 0..90 para el (clamp)
        az = fmod(az_deg, 360.0)
        if az < 0:
            az += 360.0
        el = max(0.0, min(90.0, el_deg))
        # Enviamos y no bloqueamos esperando respuesta para evitar RPRT -9/tiempos
        self.send_cmd(f"P {az:.2f} {el:.2f}", expect_reply=False)

    def stop(self):
        self.send_cmd("S", expect_reply=False)

# ------------------------- loop de tracking -------------------------

def main():
    ap = argparse.ArgumentParser(description="Track Skyfield -> rotctld")
    ap.add_argument("--tle-file", required=True, help="Archivo TLE (name+L1+L2)")
    ap.add_argument("--sat", default=None, help="Nombre exacto del satélite en el TLE")
    ap.add_argument("--lat", type=float, required=True, help="Latitud (grados, +N, -S)")
    ap.add_argument("--lon", type=float, required=True, help="Longitud (grados, +E, -W)")
    ap.add_argument("--alt", type=float, default=0.0, help="Altitud (m)")
    ap.add_argument("--dt", type=float, default=0.2, help="Periodo de actualización (s)")
    ap.add_argument("--min-el", type=float, default=5.0, help="Elevación mínima para trackear (grados)")
    ap.add_argument("--deadband", type=float, default=0.20, help="Hysteresis para no enviar micro-correcciones (grados)")
    ap.add_argument("--host", default="127.0.0.1", help="Host rotctld")
    ap.add_argument("--port", type=int, default=4533, help="Puerto rotctld")
    ap.add_argument("--park-el", type=float, default=None, help="Si el < min-el, estacionar a esta EL (opcional)")
    ap.add_argument("--verbose", action="store_true", help="Logs detallados")
    args = ap.parse_args()

    sat, ts = load_first_sat_from_tle(args.tle_file, args.sat)
    print(f"# Trackeando: {sat.name}")

    site = wgs84.latlon(args.lat, args.lon, elevation_m=args.alt)
    rot = RotctlClient(args.host, args.port, timeout=1.0)

    last_sent_az = None
    last_sent_el = None
    was_visible = False

    try:
        rot.connect()
    except Exception as e:
        print(f"[ERR] No conecta a rotctld {args.host}:{args.port} -> {e}", file=sys.stderr)
        sys.exit(2)

    try:
        while True:
            t = ts.now()

            # *** Skyfield correcto: topocéntrico como (sat - site).at(t)
            topo = (sat - site).at(t)
            alt, az, dist = topo.altaz()

            alt_deg = alt.degrees
            az_deg = az.degrees

            # visibilidad
            visible = alt_deg >= args.min_el

            if args.verbose:
                print(f"[OBS] az={az_deg:6.2f} el={alt_deg:5.2f} vis={visible}", flush=True)

            if visible:
                # deadband: sólo mandamos si el cambio supera el umbral
                if (last_sent_az is None or last_sent_el is None or
                        abs(((az_deg - (last_sent_az or 0.0) + 540.0) % 360.0) - 180.0) > args.deadband or
                        abs(alt_deg - (last_sent_el or 0.0)) > args.deadband):
                    try:
                        rot.set_pos(az_deg, alt_deg)
                        last_sent_az, last_sent_el = az_deg, alt_deg
                        if args.verbose:
                            print(f"[CMD] P {az_deg:.2f} {alt_deg:.2f}")
                    except Exception as e:
                        # Reintento de conexión simple
                        if args.verbose:
                            print(f"[WARN] fallo envío, reintento: {e}")
                        try:
                            rot.close()
                            rot.connect()
                        except Exception:
                            pass
                was_visible = True

            else:
                # debajo del horizonte
                if was_visible:
                    # terminó la pasada: opcionalmente STOP
                    try:
                        rot.stop()
                        if args.verbose:
                            print("[CMD] S (stop)")
                    except Exception:
                        pass
                    was_visible = False

                # estacionar si se pidió
                if args.park_el is not None:
                    if last_sent_el != args.park_el:
                        try:
                            # mantenemos el az actual (no importa), elevamos/descendemos a park
                            rot.set_pos(az_deg, args.park_el)
                            last_sent_az, last_sent_el = az_deg, args.park_el
                            if args.verbose:
                                print(f"[CMD] park -> P {az_deg:.2f} {args.park_el:.2f}")
                        except Exception:
                            pass

            time.sleep(max(0.02, args.dt))

    except KeyboardInterrupt:
        print("\n[OK] fin.")
    finally:
        rot.close()

if __name__ == "__main__":
    main()
