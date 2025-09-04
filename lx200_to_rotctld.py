#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puente LX200 (TCP) <- Stellarium Telescope Control -> rotctld (Easycomm-II)
- Stellarium se conecta por red (modo "Logiciel tiers ou poste distant") y envía comandos LX200.
- Este servidor recibe RA/Dec (J2000 por defecto en Stellarium), convierte a Alt/Az
  según tu ubicación y hora actual, y llama a rotctld:  P <az> <el>

Dependencias: skyfield (y sgp4/jplephem ya los tenés), Python 3.11+.
"""

import argparse, math, socket, socketserver, threading, time
from datetime import datetime
from typing import Optional, Tuple

# --- Skyfield para conversiones RA/Dec ↔ Alt/Az
from skyfield.api import load, wgs84, Star, Angle

# ========= Utilidades de formato LX200 =========

def hms_to_hours(hms: str) -> float:
    # "HH:MM:SS" → horas decimales
    parts = hms.strip().split(':')
    if len(parts) != 3:
        raise ValueError("RA HMS invalido")
    h, m, s = map(float, parts)
    return h + m/60.0 + s/3600.0

def dms_to_degrees(dms: str) -> float:
    # "+DD*MM:SS" o "-DD*MM:SS" → grados decimales
    sgn = 1.0
    txt = dms.strip()
    if txt.startswith('-'):
        sgn = -1.0
        txt = txt[1:]
    elif txt.startswith('+'):
        txt = txt[1:]
    if '*' in txt:
        d, rest = txt.split('*', 1)
    else:
        # A veces llega "DD:MM:SS"
        d, rest = txt.split(':', 1)
    if ':' in rest:
        m, s = rest.split(':', 1)
    else:
        m, s = rest, "0"
    deg = float(d) + float(m)/60.0 + float(s)/3600.0
    return sgn * deg

def hours_to_hms(hours: float) -> str:
    hours = hours % 24.0
    h = int(hours)
    m = int((hours - h)*60.0)
    s = int(round((hours - h - m/60.0)*3600.0))
    if s == 60:
        s = 0; m += 1
    if m == 60:
        m = 0; h = (h + 1) % 24
    return f"{h:02d}:{m:02d}:{s:02d}"

def degrees_to_dms(deg: float) -> str:
    sgn = '+' if deg >= 0 else '-'
    a = abs(deg)
    d = int(a)
    m = int((a - d)*60.0)
    s = int(round((a - d - m/60.0)*3600.0))
    if s == 60:
        s = 0; m += 1
    if m == 60:
        m = 0; d += 1
    return f"{sgn}{d:02d}*{m:02d}:{s:02d}"

# ========= Cliente simple a rotctld =========

class RotCtl:
    def __init__(self, host: str, port: int, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.lock = threading.Lock()

    def _talk(self, cmd: str) -> str:
        with self.lock:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            s.sendall((cmd + "\n").encode("ascii"))
            data = s.recv(4096).decode("ascii", "ignore").strip()
            s.close()
            return data

    def set_pos(self, az: float, el: float) -> bool:
        resp = self._talk(f"P {az:.2f} {el:.2f}")
        # rotctld suele contestar "RPRT 0" si ok
        return "RPRT 0" in resp or resp == ""

    def get_pos(self) -> Optional[Tuple[float, float]]:
        resp = self._talk("p")
        try:
            lines = resp.splitlines()
            az = float(lines[0].strip())
            el = float(lines[1].strip())
            return (az, el)
        except Exception:
            return None

# ========= Conversión usando Skyfield =========

class Converter:
    def __init__(self, lat_deg: float, lon_deg: float, alt_m: float):
        self.ts = load.timescale()
        self.site = wgs84.latlon(latitude_degrees=lat_deg,
                                 longitude_degrees=lon_deg,
                                 elevation_m=alt_m)

    def radec_to_altaz(self, ra_hours: float, dec_deg: float) -> Tuple[float, float]:
        """
        Convierte RA/Dec (J2000) a Alt/Az (grados) "apparent" en el instante actual.
        """
        t = self.ts.now()
        star = Star(ra=Angle(hours=ra_hours), dec=Angle(degrees=dec_deg))
        app = self.site.at(t).observe(star).apparent()
        alt, az, _ = app.altaz()
        return (az.degrees % 360.0, alt.degrees)

    def altaz_to_radec(self, az_deg: float, el_deg: float) -> Tuple[float, float]:
        """
        Invierte: desde Alt/Az a RA/Dec aparentes (horas, grados).
        """
        t = self.ts.now()
        v = self.site.at(t).from_altaz(alt_degrees=el_deg, az_degrees=az_deg)
        ra, dec, _ = v.radec()
        return (ra.hours % 24.0, dec.degrees)

# ========= Servidor LX200 =========

class LX200State:
    def __init__(self, conv: Converter, rot: RotCtl, deadband=0.3, verbose=False):
        self.conv = conv
        self.rot = rot
        self.deadband = float(deadband)
        self.verbose = verbose
        # Objetivo cargado por :Sr / :Sd (en horas y grados)
        self.target_ra: Optional[float] = None
        self.target_dec: Optional[float] = None
        self.lock = threading.Lock()

    def log(self, msg: str):
        if self.verbose:
            print(msg, flush=True)

STATE: LX200State = None  # se inicializa en main()

class LX200Handler(socketserver.StreamRequestHandler):
    """
    Implementación mínima del protocolo LX200 usado por Stellarium:
      :GR# -> RA actual   (hh:mm:ss#)
      :GD# -> Dec actual  (+dd*mm:ss#)
      :Srhh:mm:ss# -> set target RA, responde '1'
      :Sd±dd*mm:ss# -> set target Dec, responde '1'
      :MS# -> Slew a target cargado, responde '0' si OK
      :Q#  -> Stop, responde '1'
    """
    def handle(self):
        STATE.log(f"[TCP] Conexión de {self.client_address}")
        buf = b""
        while True:
            data = self.rfile.read(1)
            if not data:
                break
            if data == b'#':
                cmd = buf.decode('ascii', 'ignore')
                buf = b""
                self._process(cmd)
            elif data in (b'\r', b'\n'):
                continue
            else:
                buf += data

    def send(self, s: str):
        self.wfile.write((s + "#").encode('ascii'))

    def _process(self, cmd: str):
        cmdU = cmd.strip().upper()
        STATE.log(f"[LX200 RX] :{cmd}#")

        # GET RA
        if cmdU == "GR":
            pos = STATE.rot.get_pos()
            if pos is None:
                # si no podemos leer, devolvemos la última target
                ra = STATE.target_ra or 0.0
                dec = STATE.target_dec or 0.0
            else:
                az, el = pos
                ra, dec = STATE.conv.altaz_to_radec(az, el)
            self.send(hours_to_hms(ra))
            return

        # GET DEC
        if cmdU == "GD":
            pos = STATE.rot.get_pos()
            if pos is None:
                dec = STATE.target_dec or 0.0
                ra = STATE.target_ra or 0.0
            else:
                az, el = pos
                ra, dec = STATE.conv.altaz_to_radec(az, el)
            self.send(degrees_to_dms(dec))
            return

        # SET RA
        if cmdU.startswith("SR"):
            ra_txt = cmd[2:]  # lo que sigue a "Sr"
            try:
                ra_hours = hms_to_hours(ra_txt)
                with STATE.lock:
                    STATE.target_ra = ra_hours
                self.send("1")
            except Exception:
                self.send("0")
            return

        # SET DEC
        if cmdU.startswith("SD"):
            dec_txt = cmd[2:]
            try:
                dec_deg = dms_to_degrees(dec_txt)
                with STATE.lock:
                    STATE.target_dec = dec_deg
                self.send("1")
            except Exception:
                self.send("0")
            return

        # MOVE (slew) a target RA/DEC cargado
        if cmdU == "MS":
            with STATE.lock:
                ra = STATE.target_ra
                dec = STATE.target_dec
            if ra is None or dec is None:
                self.send("0")  # fallo: no hay target cargado
                return
            az, el = STATE.conv.radec_to_altaz(ra, dec)
            ok = STATE.rot.set_pos(az, el)
            STATE.log(f"[SLEW] RA={ra:.6f}h DEC={dec:.6f}° -> AZ={az:.2f} EL={el:.2f} | ok={ok}")
            self.send("0" if ok else "1")  # LX200: '0'=ok en muchos firmwares
            return

        # STOP
        if cmdU == "Q" or cmdU.startswith("Q"):
            # rotctld no tiene stop estándar para easycomm; podés agregarlo si hace falta
            self.send("1")
            return

        # Respuesta por defecto
        self.send("")

# ========= main =========

def main():
    ap = argparse.ArgumentParser(description="Servidor LX200 → rotctld (Alt/Az)")
    ap.add_argument("--listen", default="0.0.0.0", help="IP de escucha (por defecto: 0.0.0.0)")
    ap.add_argument("--port", type=int, default=10001, help="Puerto LX200 TCP (p.ej. 10001)")
    ap.add_argument("--lat", type=float, required=True, help="Latitud (grados, +N)")
    ap.add_argument("--lon", type=float, required=True, help="Longitud (grados, +E)")
    ap.add_argument("--alt", type=float, default=0.0, help="Altura (m)")
    ap.add_argument("--rot-host", default="127.0.0.1", help="Host rotctld")
    ap.add_argument("--rot-port", type=int, default=4533, help="Puerto rotctld")
    ap.add_argument("--deadband", type=float, default=0.3, help="(reservado) banda muerta, deg")
    ap.add_argument("--verbose", action="store_true", help="Logs verbosos")
    args = ap.parse_args()

    conv = Converter(args.lat, args.lon, args.alt)
    rot = RotCtl(args.rot_host, args.rot_port)
    global STATE
    STATE = LX200State(conv, rot, deadband=args.deadband, verbose=args.verbose)

    class ThreadedTCP(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    srv = ThreadedTCP((args.listen, args.port), LX200Handler)
    print(f"[LX200] Escuchando en {args.listen}:{args.port} (lat={args.lat}, lon={args.lon}, alt={args.alt})")
    print(f"[LX200] Enviando a rotctld {args.rot_host}:{args.rot_port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()

if __name__ == "__main__":
    main()
