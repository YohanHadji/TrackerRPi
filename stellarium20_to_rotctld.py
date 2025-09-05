#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stellarium (bin 20/24 bytes) -> rotctld
- Decodifica RA/DEC, convierte a AZ/EL (LST).
- Hilo de tracking continuo si no llegan paquetes.
- Suavizado: 3 decimales en P, deadband y limitación de velocidad (--max-rate).
"""

import argparse, socket, threading, time, math
from contextlib import closing

# ---------- rotctld ----------
class Rotctl:
    def __init__(self, host, port, timeout=2.0):
        self.addr = (host, port)
        self.timeout = timeout
        self.sock = None
        self.lock = threading.Lock()
        self.connect()

    def connect(self):
        with self.lock:
            if self.sock:
                try: self.sock.close()
                except: pass
            s = socket.create_connection(self.addr, timeout=self.timeout)
            s.settimeout(self.timeout)
            self.sock = s

    def _send(self, line: str):
        self.sock.sendall(line.encode('ascii'))

    def _readline(self):
        buf = b""
        while not buf.endswith(b"\n"):
            b = self.sock.recv(1)
            if not b: break
            buf += b
        return buf.decode('ascii', 'ignore').strip()

    def get_pos(self):
        with self.lock:
            try:
                self._send("p\n")
                az = float(self._readline())
                el = float(self._readline())
                return az, el
            except Exception:
                self.connect()
                raise

    def set_pos(self, az_deg: float, el_deg: float):
        with self.lock:
            try:
                # 3 decimales para minimizar cuantización
                self._send(f"P {az_deg:.3f} {el_deg:.3f}\n")
                return self._readline()  # "RPRT 0"
            except Exception:
                self.connect()
                raise

# ---------- utils ----------
def hexdump(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)

def wrap180(d):
    return ((d + 180.0) % 360.0) - 180.0

def ang_dist(az1, el1, az2, el2):
    da = wrap180(az2 - az1)
    de = el2 - el1
    return (da*da + de*de) ** 0.5

# Paquete 20 bytes
def decode20(b: bytes):
    if len(b) < 20: return None
    ra_u32  = int.from_bytes(b[8:12],  'little', signed=False)
    dec_s32 = int.from_bytes(b[12:16], 'little', signed=True)
    ra_h = (ra_u32 / 2**32) * 24.0
    dec_deg = (dec_s32 / 0x40000000) * 90.0
    if not (0.0 <= ra_h < 24.0): return None
    if not (-90.1 <= dec_deg <= 90.1): return None
    return ra_h, dec_deg, 20

# Paquete 24 bytes (variante)
def decode24(b: bytes):
    if len(b) < 24: return None
    ra_u32  = int.from_bytes(b[12:16], 'little', signed=False)
    dec_s32 = int.from_bytes(b[16:20], 'little', signed=True)
    ra_h = (ra_u32 / 2**32) * 24.0
    dec_deg = (dec_s32 / 0x40000000) * 90.0
    if not (0.0 <= ra_h < 24.0): return None
    if not (-90.1 <= dec_deg <= 90.1): return None
    return ra_h, dec_deg, 24

# ---------- RA/DEC -> AZ/EL ----------
class RadecProjector:
    def __init__(self, lat_deg, lon_deg):
        self.lat = math.radians(lat_deg)
        self.lon_deg = lon_deg

    @staticmethod
    def _jd_from_unix(t):
        return t/86400.0 + 2440587.5

    @staticmethod
    def _gmst_hours(jd):
        d = jd - 2451545.0
        gmst = 18.697374558 + 24.06570982441908 * d
        return gmst % 24.0

    def radec_to_azel(self, ra_h, dec_deg, unix_time=None):
        if unix_time is None:
            unix_time = time.time()
        jd = self._jd_from_unix(unix_time)
        gmst_h = self._gmst_hours(jd)
        lst_h  = (gmst_h + self.lon_deg/15.0) % 24.0
        H_deg  = wrap180((lst_h - ra_h) * 15.0)
        H = math.radians(H_deg)
        dec = math.radians(dec_deg)
        lat = self.lat

        sin_alt = math.sin(dec)*math.sin(lat) + math.cos(dec)*math.cos(lat)*math.cos(H)
        alt = math.asin(max(-1.0, min(1.0, sin_alt)))

        cos_az = (math.sin(dec) - math.sin(alt)*math.sin(lat)) / (max(1e-12, math.cos(alt)*math.cos(lat)))
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.acos(cos_az)
        if math.sin(H) > 0:
            az = 2*math.pi - az

        return (math.degrees(az) % 360.0), math.degrees(alt)

# ---------- servidor + tracking ----------
class StellariumServer:
    def __init__(self, bind_host, bind_port, rot: Rotctl, proj: RadecProjector,
                 deadband=0.3, min_el=0.0, dt=0.5, timeout=5.0,
                 max_rate=2.0, verbose=True, log_pkts=False):
        self.bind = (bind_host, bind_port)
        self.rot = rot
        self.proj = proj
        self.deadband = float(deadband)
        self.min_el = float(min_el)
        self.dt = float(dt)
        self.timeout = float(timeout)
        self.max_rate = float(max_rate)  # deg/s
        self.verbose = verbose
        self.log_pkts = log_pkts

        self.last_cmd = None     # (az, el) último enviado
        self.last_target = None  # (ra_h, dec_deg)
        self.tlock = threading.Lock()
        self.running = True

    def _rate_limited_set(self, az_tgt, el_tgt):
        """Aplica limitación de velocidad respecto a self.last_cmd."""
        if self.last_cmd is None:
            az_new, el_new = az_tgt, el_tgt
        else:
            az_cur, el_cur = self.last_cmd
            da = wrap180(az_tgt - az_cur)
            de = el_tgt - el_cur
            step = self.max_rate * self.dt
            if abs(da) > step:
                az_new = (az_cur + step * (1 if da > 0 else -1)) % 360.0
            else:
                az_new = (az_cur + da) % 360.0
            if abs(de) > step:
                el_new = el_cur + step * (1 if de > 0 else -1)
            else:
                el_new = el_cur + de
        if ang_dist(az_new, el_new, az_tgt, el_tgt) < self.deadband:
            az_new, el_new = az_tgt, el_tgt
        resp = self.rot.set_pos(az_new, el_new)
        if self.verbose:
            print(f"[CMD] to AZ={az_new:06.3f} EL={el_new:06.3f} (tgt {az_tgt:06.3f}/{el_tgt:06.3f}) | {resp}")
        self.last_cmd = (az_new, el_new)

    def tracking_loop(self):
        while self.running:
            tgt = None
            with self.tlock:
                if self.last_target:
                    tgt = self.last_target
            if tgt:
                ra_h, dec_d = tgt
                az, el = self.proj.radec_to_azel(ra_h, dec_d)
                if el >= self.min_el:
                    if (self.last_cmd is None) or (ang_dist(self.last_cmd[0], self.last_cmd[1], az, el) >= self.deadband):
                        try:
                            self._rate_limited_set(az, el)
                        except Exception as e:
                            print(f"[ROT ERR] {e}")
                else:
                    if self.verbose:
                        print(f"[TRACK SKIP] EL {el:.2f} < min {self.min_el:.2f}")
            time.sleep(self.dt)

    def start(self):
        print(f"[SERV] Stellarium 20/24 en {self.bind[0]}:{self.bind[1]} -> rotctld {self.rot.addr[0]}:{self.rot.addr[1]}")
        try:
            az, el = self.rot.get_pos()
            print(f"[ROT] AZ={az:.2f} EL={el:.2f}")
        except Exception as e:
            print(f"[ROT] no pude leer pose: {e}")

        threading.Thread(target=self.tracking_loop, daemon=True).start()

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(self.bind)
            s.listen(5)
            s.settimeout(1.0)
            while self.running:
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._client_loop, args=(conn, addr), daemon=True).start()

    def _client_loop(self, conn: socket.socket, addr):
        peer = f"{addr[0]}:{addr[1]}"
        if self.verbose:
            print(f"[TCP] conexión {peer}")
        conn.settimeout(self.timeout)
        buf = bytearray()
        try:
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 20:
                    if self.log_pkts:
                        print(f"[PKT] {hexdump(buf[:min(24,len(buf))])}")
                    d20 = decode20(buf)
                    if d20:
                        ra_h, dec_d, n = d20
                        buf[:n] = b""
                    elif len(buf) >= 24:
                        d24 = decode24(buf)
                        if d24:
                            ra_h, dec_d, n = d24
                            buf[:n] = b""
                        else:
                            buf[:1] = b""
                            continue
                    else:
                        break

                    with self.tlock:
                        self.last_target = (ra_h, dec_d)

                    az, el = self.proj.radec_to_azel(ra_h, dec_d)
                    if self.verbose:
                        print(f"[GOTO] RA={ra_h:06.3f}h DEC={dec_d:07.3f}° -> AZ={az:06.3f} EL={el:06.3f}")

                    if el < self.min_el:
                        if self.verbose:
                            print(f"[SKIP] EL {el:.2f} < min {self.min_el:.2f}")
                        continue

                    # En vez de saltar al target directamente, aplicamos rate limiting
                    if (self.last_cmd is None) or (ang_dist(self.last_cmd[0], self.last_cmd[1], az, el) >= self.deadband):
                        try:
                            self._rate_limited_set(az, el)
                        except Exception as e:
                            print(f"[ROT ERR] {e}")

        except socket.timeout:
            if self.verbose:
                print(f"[TCP] timeout {peer}")
        except Exception as e:
            print(f"[TCP] error {peer}: {e}")
        finally:
            try: conn.close()
            except: pass
            if self.verbose:
                print(f"[TCP] desconectado {peer}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--listen', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=10001)
    ap.add_argument('--rot-host', default='127.0.0.1')
    ap.add_argument('--rot-port', type=int, default=4533)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--alt', type=float, default=0.0)
    ap.add_argument('--deadband', type=float, default=0.3)
    ap.add_argument('--min-el', type=float, default=0.0)
    ap.add_argument('--dt', type=float, default=0.5)
    ap.add_argument('--timeout', type=float, default=5.0)
    ap.add_argument('--max-rate', type=float, default=2.0, help="Velocidad máx. (°/s) para suavizar")
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--log-pkts', action='store_true')
    args = ap.parse_args()

    rot = Rotctl(args.rot_host, args.rot_port)
    proj = RadecProjector(args.lat, args.lon)
    srv  = StellariumServer(args.listen, args.port, rot, proj,
                            deadband=args.deadband, min_el=args.min_el,
                            dt=args.dt, timeout=args.timeout,
                            max_rate=args.max_rate,
                            verbose=not args.quiet, log_pkts=args.log_pkts)
    srv.start()

if __name__ == '__main__':
    main()
