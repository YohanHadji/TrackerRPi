#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, socket, struct, threading, time
from typing import Optional, Tuple
from skyfield.api import load, load_file, Star, wgs84

# Escalas de Stellarium 2.0
U32 = 0x100000000
DEC_SCALE = float(0x40000000)

def decode_payload(payload: bytes) -> Optional[Tuple[float, float]]:
    """
    Stellarium 2.0: payload mínimo de 16 bytes:
      <ts_us u64><ra u32><dec i32>
    Algunas variantes meten 0..4 bytes “extras” (reservados).
    """
    if len(payload) < 16:
        return None
    ts_us, ra_u32, dec_s32 = struct.unpack_from('<QIi', payload, 0)
    ra_h  = (ra_u32 / U32) * 24.0
    dec_d = (dec_s32 / DEC_SCALE) * 90.0
    if not (-90.5 <= dec_d <= 90.5):
        return None
    return (ra_h % 24.0, dec_d)

def az_wrap(az): return az % 360.0
def az_delta(a,b):
    d = (b - a + 540.0) % 360.0 - 180.0
    return d

# ===== Cliente rotctld =====
class RotctlClient:
    def __init__(self, host, port, timeout=2.0):
        self.host, self.port = host, port
        self.timeout = timeout
        self.sock = None
        self.lock = threading.Lock()

    def _ensure(self):
        if self.sock: return
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self.sock = s

    def _read_line(self) -> str:
        data = b''
        while not data.endswith(b'\n'):
            b = self.sock.recv(1)
            if not b: break
            data += b
        return data.decode('ascii','ignore').strip()

    def _send_line(self, line: str) -> str:
        self._ensure()
        self.sock.sendall(line.encode('ascii'))
        return self._read_line()

    def goto(self, az, el) -> str:
        with self.lock:
            cmd = f'P {az:.2f} {el:.2f}\n'
            try:
                return self._send_line(cmd)
            except Exception:
                try:
                    self.close()
                    return self._send_line(cmd)
                except Exception as e:
                    print(f"[ROT ERR] {e}", flush=True)
                    self.close()
                    return "RPRT -1"

    def get_pos(self):
        with self.lock:
            try:
                self._ensure()
                self.sock.sendall(b'p\n')
                az_s = self._read_line()
                el_s = self._read_line()
                return float(az_s), float(el_s)
            except Exception as e:
                print(f"[ROT ERR] get_pos: {e}", flush=True)
                self.close()
                return (0.0, 0.0)

    def close(self):
        if self.sock:
            try: self.sock.close()
            except: pass
        self.sock = None

# ===== Bridge =====
class Bridge:
    def __init__(self, args):
        self.args = args
        self.running = True
        self.last_cmd = None
        self.last_radec = None
        self.last_valid_ts = 0.0

        self.ts = load.timescale()
        kernel = os.path.expanduser(args.kernel)
        try:
            self.eph = load_file(kernel)     # usa kernel local
        except Exception:
            self.eph = load('de421.bsp')     # fallback online
        self.earth = self.eph['earth']
        self.site  = wgs84.latlon(args.lat, args.lon, elevation_m=args.alt)

        self.rot = RotctlClient(args.rot_host, args.rot_port, timeout=2.0)

        if args.track_after_goto:
            self.track_thread = threading.Thread(target=self._track_loop, daemon=True)
            self.track_thread.start()
        else:
            self.track_thread = None

    def _radec_to_altaz_now(self, ra_h, dec_d):
        t = self.ts.now()
        star = Star(ra_hours=ra_h, dec_degrees=dec_d)
        app  = (self.earth + self.site).at(t).observe(star).apparent()
        alt, az, _ = app.altaz()
        return (az_wrap(az.degrees), alt.degrees)

    def _maybe_send(self, az, el, tag):
        if el < self.args.min_el:
            if self.args.verbose:
                print(f"[SKIP] EL {el:.2f} < min {self.args.min_el:.2f}", flush=True)
            return
        if self.last_cmd:
            da = az_delta(self.last_cmd[0], az)
            de = el - self.last_cmd[1]
            if abs(da) < self.args.deadband and abs(de) < self.args.deadband:
                if self.args.verbose:
                    print(f"[HOLD] ΔAZ={da:.2f} ΔEL={de:.2f} < deadband {self.args.deadband}", flush=True)
                return
        resp = self.rot.goto(az, el)
        self.last_cmd = (az, el)
        if self.args.verbose:
            print(f"[CMD] {tag} AZ={az:.3f} EL={el:.3f} | {resp}", flush=True)

    def _track_loop(self):
        while self.running:
            now = time.time()
            if self.last_radec and (now - self.last_valid_ts) <= self.args.hold:
                ra_h, dec_d = self.last_radec
                try:
                    az, el = self._radec_to_altaz_now(ra_h, dec_d)
                    if self.args.verbose:
                        print(f"[TRACK] AZ={az:.2f} EL={el:.2f}", flush=True)
                    self._maybe_send(az, el, "TRACK")
                except Exception as e:
                    if self.args.verbose:
                        print(f"[TRACK ERR] {e}", flush=True)
            time.sleep(max(0.05, self.args.dt))

    # === I/O TCP (Stellarium 2.0) ===
    def _read_exact(self, conn: socket.socket, n: int, idle_close_s=2.5) -> Optional[bytes]:
        buf = b''
        t0 = time.time()
        while len(buf) < n:
            try:
                chunk = conn.recv(n - len(buf))
            except socket.timeout:
                if time.time() - t0 > idle_close_s:
                    return None
                continue
            if not chunk:
                return None
            buf += chunk
        return buf

    def _handle_client(self, conn: socket.socket, addr):
        conn.settimeout(0.5)
        if self.args.verbose:
            print(f"[TCP] conexión {addr[0]}:{addr[1]}", flush=True)
        try:
            buf = b''
            while self.running:
                # 1) header de 4 bytes = tamaño TOTAL del paquete (incluye header)
                hdr = self._read_exact(conn, 4)
                if hdr is None:
                    raise TimeoutError("idle/closed")
                total_len, = struct.unpack('<I', hdr)
                # sanea
                if total_len < 4 or total_len > 1024:
                    if self.args.verbose:
                        print(f"[SKIP] total_len raro: {total_len}", flush=True)
                    break
                # 2) lee el resto (total_len-4)
                body = self._read_exact(conn, total_len - 4)
                if body is None:
                    raise TimeoutError("idle/closed")

                if self.args.verbose:
                    show = ' '.join(f"{b:02X}" for b in (hdr + body)[:min(20, total_len)])
                    print("[PKT]", show, flush=True)

                radec = decode_payload(body)  # body puede ser 16..20 bytes
                if radec is None:
                    if self.args.verbose:
                        print("[SKIP] payload no válido", flush=True)
                    continue

                ra_h, dec_d = radec
                try:
                    az, el = self._radec_to_altaz_now(ra_h, dec_d)
                except Exception as e:
                    if self.args.verbose:
                        print(f"[ERR] skyfield: {e}", flush=True)
                    continue

                if self.args.verbose:
                    print(f"[GOTO] RA={ra_h:.3f}h DEC={dec_d:.3f}° -> AZ={az:.3f} EL={el:.3f}", flush=True)

                self.last_radec    = (ra_h, dec_d)
                self.last_valid_ts = time.time()
                self._maybe_send(az, el, "GOTO")

        except TimeoutError:
            if self.args.verbose:
                print(f"[TCP] timeout {addr[0]}:{addr[1]}", flush=True)
        except Exception as e:
            if self.args.verbose:
                print(f"[TCP] error {addr[0]}:{addr[1]}: {e}", flush=True)
        finally:
            try: conn.close()
            except: pass
            if self.args.verbose:
                print(f"[TCP] desconectado {addr[0]}:{addr[1]}", flush=True)

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, 'TCP_KEEPIDLE'):
                srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 5)
            if hasattr(socket, 'TCP_KEEPINTVL'):
                srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
            if hasattr(socket, 'TCP_KEEPCNT'):
                srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except Exception:
            pass

        srv.bind((self.args.listen, self.args.port))
        srv.listen(8)
        self.srv = srv

        print(f"[SERV] Stellarium20 en {self.args.listen}:{self.args.port} -> rotctld {self.args.rot_host}:{self.args.rot_port}", flush=True)
        az, el = self.rot.get_pos()
        print(f"[ROT] AZ={az:.2f} EL={el:.2f}", flush=True)

        try:
            while self.running:
                conn, addr = srv.accept()
                th = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                th.start()
        except KeyboardInterrupt:
            pass
        finally:
            try: srv.close()
            except: pass
            self.rot.close()

def parse_args():
    p = argparse.ArgumentParser(description="Bridge Stellarium 2.0 (20/24 bytes) -> rotctld")
    p.add_argument('--listen', default='0.0.0.0')
    p.add_argument('--port', type=int, default=10001)
    p.add_argument('--rot-host', default='127.0.0.1')
    p.add_argument('--rot-port', type=int, default=4533)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--alt', type=float, default=0.0)
    p.add_argument('--deadband', type=float, default=0.30)
    p.add_argument('--min-el', type=float, default=0.0)
    p.add_argument('--hold', type=float, default=6.0)
    p.add_argument('--dt', type=float, default=0.5)
    p.add_argument('--track-after-goto', action='store_true')
    p.add_argument('--kernel', default='~/.skyfield/de421.bsp')
    p.add_argument('--verbose', action='store_true')
    return p.parse_args()

def main():
    args = parse_args()
    Bridge(args).start()

if __name__ == '__main__':
    main()
