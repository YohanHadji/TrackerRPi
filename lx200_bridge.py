#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import socket, struct, threading, time, math, os
from datetime import datetime, timezone
from pathlib import Path
import os

TEENSY_IP   = os.getenv("TEENSY_IP", "192.168.1.100")  # <-- fijo
TEENSY_PORT = int(os.getenv("TEENSY_PORT", "8888"))

PI_IP = "192.168.1.220"  # solo informativo/debug
s_cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ---------- Config ----------
SITE_LAT = 46.532308
SITE_LON = 6.590961
TZ       = timezone.utc

UDP_LISTEN_IP   = '0.0.0.0'
UDP_LISTEN_PORT = 8888

LX200_BIND_IP   = '0.0.0.0'
LX200_PORT      = int(os.getenv("LX200_PORT", "10010"))

# Socket.IO (para activar trigger desde el bridge)
JOY_SIO_URL   = os.getenv("JOY_SIO_URL", "http://127.0.0.1:5002")
JOY_THROTTLE  = float(os.getenv("JOY_THROTTLE", "0.30"))  # 0.10..30
JOY_ENABLE    = int(os.getenv("JOY_ENABLE", "1")) != 0    # 1=activar trigger auto



PACKET_ID_TELEM33 = 33
PACKET_ID_ABS     = 0x03
PRA, PRB          = 0xFF, 0xFA

AZ_TOL_DEG = 0.4
EL_TOL_DEG = 0.4
MAX_GOTO_LOOP_S = 8.0
RESEND_ABS_EVERY_S = 0.8
STALE_MS_WARN = 4000

# ---------- Logs ----------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "offset_logs"
LOG_DIR.mkdir(exist_ok=True)
DBG_FILE = LOG_DIR / "lx200_debug.log"
SYNC_CSV = LOG_DIR / "lx200_sync.csv"

def dbg(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with DBG_FILE.open('a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass

dbg("=== LX200 bridge iniciado ===")

# ---------- Estado ----------
state = {
    "az": None, "el": None,
    "ra": None, "dec": None,
    "last_update_ms": 0,
    "last_teensy_ip": None,   # ip de origen del id=33
    "target_ra_deg": None, "target_dec_deg": None,
    "ra_off_deg": 0.0, "dec_off_deg": 0.0,
    "last_sync": None,
}
lock = threading.Lock()

# ---------- Astro ----------
def _deg2rad(d): return d*math.pi/180.0
def _rad2deg(r): return r*180.0/math.pi
def _wrap_360(x): return x % 360.0
def _wrap_m180_180(dx): return (dx + 180.0) % 360.0 - 180.0
def _jd_from_unix_ms(utc_ms): return 2440587.5 + (utc_ms/86400000.0)
def _gmst_rad_from_jd(jd):
    T = (jd - 2451545.0)/36525.0
    gmst = 280.46061837 + 360.98564736629*(jd-2451545.0) + 0.000387933*T*T - T*T*T/38710000.0
    return _deg2rad(gmst % 360.0)

def altaz_to_radec(az_deg, el_deg, lat_deg=SITE_LAT, lon_deg=SITE_LON, utc_ms=None):
    if utc_ms is None: utc_ms = int(time.time()*1000)
    az  = _deg2rad(az_deg); alt = _deg2rad(el_deg)
    lat = _deg2rad(lat_deg); lon = _deg2rad(lon_deg)
    sDec = math.sin(lat)*math.sin(alt) + math.cos(lat)*math.cos(alt)*math.cos(az)
    sDec = min(1, max(-1, sDec))
    dec  = math.asin(sDec)
    den  = max(1e-12, math.cos(lat)*math.cos(dec))
    cosH = (math.sin(alt) - math.sin(lat)*math.sin(dec)) / den
    cosH = min(1, max(-1, cosH))
    sinH = -math.sin(az)*math.cos(alt) / max(1e-12, math.cos(dec))
    H = math.atan2(sinH, cosH)
    jd = _jd_from_unix_ms(utc_ms); gmst = _gmst_rad_from_jd(jd)
    lst = gmst + lon
    ra  = (lst - H) % (2*math.pi)
    return _rad2deg(ra), _rad2deg(dec)

def radec_to_altaz(ra_deg, dec_deg, lat_deg=SITE_LAT, lon_deg=SITE_LON, utc_ms=None):
    if utc_ms is None: utc_ms = int(time.time()*1000)
    ra  = _deg2rad(ra_deg); dec = _deg2rad(dec_deg)
    lat = _deg2rad(lat_deg); lon = _deg2rad(lon_deg)
    jd = _jd_from_unix_ms(utc_ms); gmst = _gmst_rad_from_jd(jd)
    H  = (gmst + lon - ra) % (2*math.pi)
    sinAlt = math.sin(lat)*math.sin(dec) + math.cos(lat)*math.cos(dec)*math.cos(H)
    alt = math.asin(max(-1, min(1, sinAlt)))
    sinAz = -math.sin(H)*math.cos(dec)/max(1e-12, math.cos(alt))
    cosAz = (math.sin(dec) - math.sin(alt)*math.sin(lat)) / max(1e-12, (math.cos(alt)*math.cos(lat)))
    az = math.atan2(sinAz, cosAz) % (2*math.pi)
    return _rad2deg(az), _rad2deg(alt)

def ra_deg_to_hms_str(ra_deg):
    total_sec = (ra_deg/360.0)*24.0*3600.0
    h = int(total_sec//3600); m = int((total_sec%3600)//60); s = int(total_sec%60)
    return f"{h:02d}:{m:02d}:{s:02d}#"

def dec_deg_to_dms_str(dec_deg):
    sign = '-' if dec_deg<0 else '+'
    d = abs(dec_deg); dd = int(d); mm = int((d-dd)*60.0); ss = int((d-dd-mm/60.0)*3600.0)
    return f"{sign}{dd:02d}*{mm:02d}:{ss:02d}#"

def hms_str_to_ra_deg(hms):
    try:
        hh, mm, ss = hms.split(':')
        return ((int(hh)*3600 + int(mm)*60 + float(ss))/3600.0)*15.0
    except: return None

def dms_str_to_dec_deg(dms):
    try:
        sign = -1.0 if dms[0]=='-' else 1.0
        body = dms[1:]; deg_str, rest = body.split('*',1); min_str, sec_str = rest.split(':',1)
        dd = float(deg_str); mm = float(min_str); ss = float(sec_str)
        return sign*(dd + mm/60.0 + ss/3600.0)
    except: return None

# ---------- UDP I/O ----------
def make_udp_rx_sock():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError): pass
    s.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))
    return s

udp_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

def send_abs_azel(az_deg, el_deg):
    PRA, PRB, PID = 0xFF, 0xFA, 0x03
    pay = struct.pack('<ff', float(az_deg), float(el_deg))
    pkt = bytes([PRA, PRB, PID, len(pay)]) + pay + bytes([sum(pay) & 0xFF])
    s_cmd.sendto(pkt, (TEENSY_IP, TEENSY_PORT))
    dbg(f"[ABS] Enviado 0x03 Az/El = {az_deg:.2f}/{el_deg:.2f} -> {TEENSY_IP}:{TEENSY_PORT}")


def udp_reader():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))
    dbg(f"[UDP] Escuchando Az/El en {UDP_LISTEN_IP}:{UDP_LISTEN_PORT} (id=33)")
    while True:
        try:
            packet, _ = sock.recvfrom(4096)  # <— ¡esto faltaba!
            # Paquete: [0]=0xFF [1]=0xFA [2]=id [3]=len payload...
            if len(packet) >= 12 and packet[2] == 33:
                az, el = struct.unpack_from('<ff', packet, offset=4)
                utc_ms = int(time.time() * 1000)
                ra, dec = altaz_to_radec(az, el, utc_ms=utc_ms)
                with lock:
                    state["az"] = az
                    state["el"] = el
                    state["ra"] = ra
                    state["dec"] = dec
                    state["last_update_ms"] = utc_ms
            else:
                # opcional: loguear ids desconocidos en muy bajo volumen
                pass
        except Exception as e:
            dbg(f"[UDP] Error: {e}")


# ---------- Socket.IO (activar trigger) ----------
_sio = None
if JOY_ENABLE:
    try:
        import socketio
        _sio = socketio.Client()
        _sio.connect(JOY_SIO_URL, wait_timeout=3)
        dbg(f"[JOY] Conectado a {JOY_SIO_URL}")
    except Exception as e:
        dbg(f"[JOY] Deshabilitado (no pude conectar a {JOY_SIO_URL}): {e}")
        _sio = None

def joy_trigger(on: bool):
    if not _sio or not JOY_ENABLE:
        dbg("[JOY] Trigger no disponible (SIO off)"); return
    try:
        payload = {"x": 0.0, "y": 0.0, "throttle": float(JOY_THROTTLE), "trigger": 1 if on else 0}
        _sio.emit('joystick_update', payload)
        dbg(f"[JOY] joystick_update emitido: {payload}")
    except Exception as e:
        dbg(f"[JOY] Error emitiendo joystick_update: {e}")

# ---------- GOTO ----------
def goto_abs_with_loop(target_az, target_el):
    # Asegurar trigger ON antes de mandar ABS
    joy_trigger(True)
    send_abs_azel(target_az, target_el)
    t0 = time.time(); last_sent = t0
    while time.time() - t0 < MAX_GOTO_LOOP_S:
        with lock:
            az = state["az"]; el = state["el"]
        if az is not None and el is not None:
            if abs(_wrap_m180_180(target_az-az)) <= AZ_TOL_DEG and abs(target_el-el) <= EL_TOL_DEG:
                dbg("[GOTO] Centrado. Loop detenido."); return True
        if time.time() - last_sent >= RESEND_ABS_EVERY_S:
            send_abs_azel(target_az, target_el); last_sent = time.time()
        time.sleep(0.2)
    dbg("[GOTO] Loop timeout."); return False

# ---------- LX200 ----------
def handle_client(conn, addr):
    dbg(f"[LX200] Cliente conectado: {addr}")
    conn.settimeout(30.0); buf = b""
    try:
        while True:
            chunk = conn.recv(1024)
            if not chunk: break
            dbg(f"[LX200] RAW {addr}: {chunk!r}")
            buf += chunk
            while b'#' in buf:
                cmd_bytes, buf = buf.split(b'#', 1)
                cmd = cmd_bytes.decode('ascii', errors='ignore').strip()
                dbg(f"[LX200] RX {addr}: {cmd}")

                if cmd == ':GR':
                    with lock:
                        ra = state["ra"]; ra_off = state["ra_off_deg"]; ms = state["last_update_ms"]
                    if not ra:
                        resp = "00:00:00#"
                    else:
                        stale = (int(time.time()*1000)-ms) > STALE_MS_WARN
                        resp = ra_deg_to_hms_str(_wrap_360(ra + ra_off))
                        if stale: dbg("[WARN] :GR con telemetría vieja")
                    conn.sendall(resp.encode('ascii')); dbg(f"[LX200] TX -> {resp}")

                elif cmd == ':GD':
                    with lock:
                        dec = state["dec"]; dec_off = state["dec_off_deg"]; ms = state["last_update_ms"]
                    if dec is None:
                        resp = "+00*00:00#"
                    else:
                        stale = (int(time.time()*1000)-ms) > STALE_MS_WARN
                        resp = dec_deg_to_dms_str(dec + dec_off)
                        if stale: dbg("[WARN] :GD con telemetría vieja")
                    conn.sendall(resp.encode('ascii')); dbg(f"[LX200] TX -> {resp}")

                elif cmd.startswith(':Sr '):
                    ra_t = hms_str_to_ra_deg(cmd[4:].strip()); ok = ra_t is not None
                    with lock: state["target_ra_deg"] = ra_t if ok else None
                    conn.sendall(('1#' if ok else '0#').encode('ascii')); dbg(f"[LX200] TX -> {'1#' if ok else '0#'}")

                elif cmd.startswith(':Sd '):
                    dec_t = dms_str_to_dec_deg(cmd[4:].strip()); ok = dec_t is not None
                    with lock: state["target_dec_deg"] = dec_t if ok else None
                    conn.sendall(('1#' if ok else '0#').encode('ascii')); dbg(f"[LX200] TX -> {'1#' if ok else '0#'}")

                elif cmd == ':MS':
                    with lock:
                        tra = state["target_ra_deg"]; tde = state["target_dec_deg"]
                        ra_off = state["ra_off_deg"];  de_off = state["dec_off_deg"]
                        last_ms = state["last_update_ms"]
                    if tra is None or tde is None:
                        conn.sendall(b'0#'); dbg("[LX200] TX -> 0# (sin target)"); continue
                    if int(time.time()*1000) - last_ms > STALE_MS_WARN:
                        dbg("[WARN] :MS con telemetría inexistente/vieja (no podremos cerrar el lazo)")

                    tra_use = _wrap_360(tra - ra_off); tde_use = tde - de_off
                    az_t, el_t = radec_to_altaz(tra_use, tde_use)
                    ok = goto_abs_with_loop(az_t, el_t)
                    conn.sendall(b'1#' if ok else b'0#')
                    dbg(f"[GOTO] :MS aceptado -> ABS+loop (tgt Az/El={az_t:.2f}/{el_t:.2f})")

                elif cmd == ':Q':
                    conn.sendall(b'1#'); dbg("[LX200] TX -> 1# (:Q)")

                elif cmd == ':CM':
                    with lock:
                        tra = state["target_ra_deg"]; tde = state["target_dec_deg"]
                        cra = state["ra"]; cde = state["dec"]; ms = state["last_update_ms"]
                    if None in (tra, tde, cra, cde) or (int(time.time()*1000)-ms) > STALE_MS_WARN:
                        conn.sendall(b'0#'); dbg("[LX200] TX -> 0# (:CM sin datos frescos)")
                    else:
                        dra = tra - cra; dde = tde - cde; ts = datetime.now(TZ).isoformat()
                        with lock:
                            state["ra_off_deg"]  = _wrap_360(state["ra_off_deg"] + dra)
                            state["dec_off_deg"] = state["dec_off_deg"] + dde
                            ra_off = state["ra_off_deg"]; de_off = state["dec_off_deg"]
                            state["last_sync"] = {"ts": ts, "dra_deg": dra, "dde_deg": dde}
                        try:
                            new = not SYNC_CSV.exists()
                            with SYNC_CSV.open('a', encoding='utf-8') as f:
                                if new:
                                    f.write("ts,ra_now_deg,dec_now_deg,ra_tgt_deg,dec_tgt_deg,dra_deg,dde_deg,ra_off_deg,dec_off_deg\n")
                                f.write(f"{ts},{cra:.6f},{cde:.6f},{tra:.6f},{tde:.6f},{dra:.6f},{dde:.6f},{ra_off:.6f},{de_off:.6f}\n")
                        except Exception as e:
                            dbg(f"[SYNC][ERR] {e}")
                        conn.sendall(b'1#'); dbg("[LX200] TX -> 1# (:CM)")

                else:
                    conn.sendall(b'0#'); dbg("[LX200] TX -> 0# (no impl)")

    except socket.timeout:
        dbg(f"[LX200] Timeout de conexión: {addr}")
    except Exception as e:
        dbg(f"[LX200] Error cliente: {e}")
    finally:
        try: conn.close()
        except: pass
        dbg(f"[LX200] Cliente desconectado: {addr}")

def lx200_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LX200_BIND_IP, LX200_PORT)); s.listen(4)
    dbg(f"[LX200] Servidor LX200 escuchando en {LX200_BIND_IP}:{LX200_PORT}")
    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=udp_reader, daemon=True).start()
    lx200_server()
