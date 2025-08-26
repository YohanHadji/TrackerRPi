from flask import Flask, Response, render_template, request
import cv2
import time
from threading import Thread
import socket
import struct
import serial
from flask_socketio import SocketIO, emit
# --- Sitio / metadatos ---
SITE_LAT = 46.532308
SITE_LON = 6.590961   # Este positivo

SITE_ID       = "ARG-TDF-01"
INSTRUMENT_ID = "N300_QHY4040_A"
EXP_MS        = 30
SEEING_ARCSEC = 1.8

# --- Gating de tracklets ---
TRACKLET_PERIOD_MS     = 100      # 10 Hz máx.
TRACKLET_DELTA_MIN_DEG = 0.02     # umbral de cambio
TRACKLET_HEARTBEAT_MS  = 1000     # 1/s como mínimo

# --- Carpeta absoluta para logs JSONL ---
from pathlib import Path
from datetime import datetime, timezone
import json, math, time

BASE_DIR = Path(__file__).resolve().parent
TRACKLET_DIR = BASE_DIR / "tracklets"
TRACKLET_DIR.mkdir(exist_ok=True)

def current_tracklet_path():
    return TRACKLET_DIR / f"tracklets_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

# --- AltAz -> RA/Dec con UTC de la Pi ---
def _deg2rad(d): return d * math.pi / 180.0
def _rad2deg(r): return r * 180.0 / math.pi

def _jd_from_unix_ms(utc_ms):
    return 2440587.5 + (utc_ms / 86400000.0)

def _gmst_rad_from_jd(jd):
    T = (jd - 2451545.0)/36525.0
    gmst = 280.46061837 + 360.98564736629*(jd-2451545.0) + 0.000387933*T*T - T*T*T/38710000.0
    gmst = gmst % 360.0
    return _deg2rad(gmst)

def altaz_to_radec_pi(az_deg, el_deg, lat_deg=SITE_LAT, lon_deg=SITE_LON):
    az  = _deg2rad(az_deg)
    alt = _deg2rad(el_deg)
    lat = _deg2rad(lat_deg)
    lon = _deg2rad(lon_deg)

    # Dec (no depende del tiempo)
    sinDec = math.sin(lat)*math.sin(alt) + math.cos(lat)*math.cos(alt)*math.cos(az)
    sinDec = min(1.0, max(-1.0, sinDec))
    dec = math.asin(sinDec)

    # Hora local H
    den  = (math.cos(lat)*math.cos(dec))
    den  = den if abs(den) > 1e-12 else 1e-12
    cosH = (math.sin(alt) - math.sin(lat)*math.sin(dec)) / den
    cosH = min(1.0, max(-1.0, cosH))
    sinH = -math.sin(az)*math.cos(alt) / (math.cos(dec) + 1e-12)
    H = math.atan2(sinH, cosH)

    # UTC real de la Pi
    now_ms = int(time.time() * 1000)
    jd  = _jd_from_unix_ms(now_ms)
    gmst = _gmst_rad_from_jd(jd)
    lst  = gmst + lon

    ra = (lst - H) % (2*math.pi)
    return _rad2deg(ra), _rad2deg(dec), now_ms

def iso8601_from_ms(ms):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ms/1000)) + f".{ms%1000:03d}Z"


# ======= UDP TX (igual que en joysti_virtual.py) =======
PRA = 0xFF
PRB = 0xFA
udp_target_ip = '192.168.1.100'   # <-- AJUSTA a la IP real de tu receptor
udp_target_port = 8888
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_udp_packet(packet: bytes):
    try:
        udp_socket.sendto(packet, (udp_target_ip, udp_target_port))
    except OSError as e:
        if e.errno == 101:
            print("[UDP] La red no es accesible (errno 101).")
        else:
            raise

def create_packet(x, y, throttle, trigger):
    # MISMO layout que joysti_virtual.py (nativo). Si tu receptor espera little-endian, cambia por '<iiiiiiff'
    joystick_data = struct.pack(
        'iiiiiiff', 1, int(trigger), int(x * 100), int(y * 100), 0, 99, float(throttle), 30.0
    )
    encoded_packet = bytes([PRA, PRB, 1, len(joystick_data)]) + joystick_data
    checksum = sum(joystick_data) & 0xFF
    encoded_packet += bytes([checksum])
    return encoded_packet

# ======= Video =======
class FrameServer:
    """Captura de video + overlay de telemetría (Az/El) y tracklets (RA/Dec, timestamp)."""

    def __init__(self, video_device='/dev/video0'):
        print(f"[Video] Inicializando captura en: {video_device}")
        self.cap = cv2.VideoCapture(video_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el dispositivo de video: {video_device}")
        self.running = True
        self.frame_rate = self.cap.get(cv2.CAP_PROP_FPS) or 30

        # Telemetría de montura
        self.azimut = None
        self.elevacion = None

        # Último tracklet recibido
        self.ra_deg = None
        self.dec_deg = None
        self.ts_iso = ""

    # --- Helpers internos ---
    @staticmethod
    def _norm_az_360(az):
        az = az % 360.0
        return az if az >= 0 else az + 360.0

    @staticmethod
    def _deg_to_hms(deg):
        total_seconds = (deg / 360.0) * 24.0 * 3600.0
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        s = total_seconds % 60.0
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    @staticmethod
    def _deg_to_dms(deg):
        sign = '-' if deg < 0 else '+'
        d = abs(deg)
        dd = int(d)
        mm = int((d - dd) * 60.0)
        ss = (d - dd - mm/60.0) * 3600.0
        return f"{sign}{dd:02d}:{mm:02d}:{ss:04.1f}"

    @staticmethod
    def _ts_unsynced(ts_iso: str) -> bool:
        try:
            return int(ts_iso[:4]) < 2000
        except Exception:
            return False

    # --- API para actualizar datos ---
    def update_values(self, azimut, elevacion):
        self.azimut = azimut
        self.elevacion = elevacion

    def update_tracklet(self, ra_deg, dec_deg, ts_iso):
        try:
            self.ra_deg = float(ra_deg) if ra_deg is not None else None
            self.dec_deg = float(dec_deg) if dec_deg is not None else None
        except Exception:
            self.ra_deg = None
            self.dec_deg = None
        self.ts_iso = ts_iso or ""

    # --- Generación de frame con overlay ---
    def get_frame(self):
        if not self.running:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None

        frame_height, _ = frame.shape[:2]

        # Reloj local + FPS
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        millis = int(time.time() * 1000) % 1000
        fps_text = f"FPS: {self.frame_rate:.2f}"
        cv2.putText(frame, f"{current_time}.{millis:03d}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, fps_text, (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Az/El (Az normalizado a 0..360 para visual)
        if self.azimut is not None and self.elevacion is not None:
            az = self._norm_az_360(float(self.azimut))
            el = float(self.elevacion)
            az_el_text = f"Az: {az:06.2f}  El: {el:06.2f}"
            cv2.putText(frame, az_el_text, (10, frame_height - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # RA/Dec + timestamp del último tracklet
        if self.ra_deg is not None and self.dec_deg is not None:
            ra_txt = self._deg_to_hms(self.ra_deg)
            dec_txt = self._deg_to_dms(self.dec_deg)
            cv2.putText(frame, f"RA: {ra_txt}  Dec: {dec_txt}", (10, 110),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            ts_label = self.ts_iso
            if self._ts_unsynced(ts_label):
                ts_label += " (unsynced)"
            cv2.putText(frame, f"T:  {ts_label}", (10, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def stop(self):
        self.running = False
        self.cap.release()

# ======= UDP RX (telemetría para azimut/elevación) =======
# ======= UDP RX (telemetría para azimut/elevación) =======
def udp_receiver(server: FrameServer):
    udp_ip = '0.0.0.0'
    udp_port = 8888
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))
    print(f"[UDP RX] Escuchando en {udp_ip}:{udp_port} ...")

    # Estado para gating
    last_send_ms = 0
    last_hb_ms   = 0
    last_ra = None
    last_dec = None

    while server.running:
        try:
            data, _ = sock.recvfrom(4096)

            # --- Paquete binario id=33: <ff> az, el ---
            if len(data) >= 12 and data[2] == 33:
                azimut, elevacion = struct.unpack_from('<ff', data, offset=4)
                server.update_values(azimut, elevacion)

                # Calcular RA/Dec con UTC real de la Pi
                ra_deg, dec_deg, now_ms = altaz_to_radec_pi(azimut, elevacion)
                ts_iso = iso8601_from_ms(now_ms)

                # Gating: periodo + delta + heartbeat
                send_ok = False
                if (now_ms - last_send_ms) >= TRACKLET_PERIOD_MS:
                    delta_ok = (last_ra is None or
                                abs(ra_deg  - last_ra ) >= TRACKLET_DELTA_MIN_DEG or
                                abs(dec_deg - last_dec) >= TRACKLET_DELTA_MIN_DEG)
                    heartbeat = (now_ms - last_hb_ms) >= TRACKLET_HEARTBEAT_MS
                    send_ok = delta_ok or heartbeat
                    if heartbeat: last_hb_ms = now_ms

                if send_ok:
                    last_send_ms = now_ms
                    last_ra, last_dec = ra_deg, dec_deg

                    # Actualizar overlay
                    server.update_tracklet(ra_deg, dec_deg, ts_iso)

                    # Construir tracklet (Pi como fuente)
                    obj = {
                        "timestamp": ts_iso,
                        "ra_deg": float(f"{ra_deg:.6f}"),
                        "dec_deg": float(f"{dec_deg:.6f}"),
                        "ra_sigma_arcsec": 1.5,
                        "dec_sigma_arcsec": 1.5,
                        "mag": None,
                        "snr": None,
                        "site_id": SITE_ID,
                        "instrument_id": INSTRUMENT_ID,
                        "exp_ms": EXP_MS,
                        "seeing_arcsec": SEEING_ARCSEC,
                        # útil para debugging:
                        "az_deg": float(f"{((azimut%360)+360)%360:.2f}"),
                        "el_deg": float(f"{elevacion:.2f}"),
                        "source": "pi"
                    }

                    # Guardar JSONL del día
                    p = current_tracklet_path()
                    with p.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(obj) + "\n")
                    # Emitir a la UI
                    socketio.emit('tracklet', obj)

            # (Ignoramos cualquier otra cosa, incluido JSON del Teensy si lo hubiera)
        except Exception as e:
            print(f"[UDP RX] Error: {e}")
    sock.close()


# ======= Flask / Socket.IO =======
app = Flask(__name__, template_folder='templates')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

video_device = '/dev/video0'
server = FrameServer(video_device)

# ======= Arduino (zoom analógico) =======
arduino_port = '/dev/ttyACM0'
arduino_baudrate = 115200
try:
    arduino = serial.Serial(arduino_port, arduino_baudrate, timeout=1)
    time.sleep(2)
    # print(f"[Arduino] Conectado en {arduino_port} @ {arduino_baudrate} bps")
except Exception as e:
    arduino = None
    print(f"[Arduino][WARN] No se pudo abrir {arduino_port}: {e}")

def send_to_arduino(command: str):
    if arduino is None:
        print(f"[Arduino][WARN] No conectado. Ignoro cmd: {command!r}")
        return
    try:
        if not command.endswith('\n'):
            command += '\n'
        arduino.write(command.encode())
        arduino.flush()
        print(f"[Arduino] TX: {command.strip()}")
    except Exception as e:
        print(f"[Arduino][ERR] {e}")

# ======= Rutas HTTP =======
@app.route('/')
def index():
    return render_template('jvc_index.html')

@app.route('/set_zoom', methods=['POST'])
def set_zoom():
    voltage = request.form.get('voltage', type=float)
    if voltage is None:
        return "Falta parámetro 'voltage'", 400
    if 0.0 <= voltage <= 3.0:
        send_to_arduino(f"{voltage:.2f}")
        return "OK", 200
    return "Valor fuera de rango", 400

@app.route('/video_feed')
def video_feed():
    def generate():
        while server.running:
            frame = server.get_frame()
            if frame is None:
                break
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ======= Socket.IO (Joystick) =======
@socketio.on('joystick_update')
def handle_joystick_update(data):
    try:
        # data: {x: [-14..14], y: [-14..14], throttle: [0.10..30], trigger: 0/1}
        x = float(data.get('x', 0.0))
        y = float(data.get('y', 0.0))
        throttle = float(data.get('throttle', 0.10))
        trigger = int(data.get('trigger', 0))

        pkt = create_packet(x, y, throttle, trigger)
        send_udp_packet(pkt)
        #print(f"[JSK] x={x:.2f} y={y:.2f} thr={throttle:.2f} trig={trigger} -> UDP {udp_target_ip}:{udp_target_port} ({len(pkt)} bytes)")

        emit('ack', {'ok': True}, broadcast=False)
    except Exception as e:
        print("[JSK][ERR]", e)
        emit('ack', {'ok': False, 'error': str(e)}, broadcast=False)
        
@app.route('/tracklets/today')
def tracklets_today():
    # MOD: descarga de tracklets del día (JSON Lines)
    p = current_tracklet_path()
    if not p.exists():
        return "No hay datos hoy", 404
    return Response(p.read_text(encoding='utf-8'),
                    mimetype='application/jsonlines')
        
@socketio.on('connect')
def on_connect():
    print('[socket] cliente conectado')

@socketio.on('disconnect')
def on_disconnect():
    print('[socket] cliente desconectado')

# ======= Main =======
if __name__ == '__main__':
    try:
        udp_thread = Thread(target=udp_receiver, args=(server,), daemon=True)
        udp_thread.start()
        socketio.run(app, host='0.0.0.0', port=5002)  # sin eventlet, sin threaded=True
    finally:
        server.stop()
        if arduino:
            arduino.close()
