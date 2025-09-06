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
# Velocidad comandada en overlay: deg/s = x * throttle * JOY_GAIN
JOY_GAIN = 1.0
# --- IDs de paquetes que manda el Teensy ---
PACKET_ID_ANGLE  = 33   # <ff> az, el
PACKET_ID_OMEGAS = 34   # <ffff> wcmd_az, wcmd_el, wmeas_az, wmeas_el  (deg/s)

# --- Joystick -> deg/s (fallback para ωcmd) ---
JOY_DEG_PER_UNIT = 1.0  # cada unidad de X/Y vale 1 deg/s cuando throttle=1.0 (ajustá a gusto)

def joy_to_deg_s(x, y, throttle):
    try:
        return (float(x) * float(throttle) * JOY_DEG_PER_UNIT,
                float(y) * float(throttle) * JOY_DEG_PER_UNIT)
    except Exception:
        return (0.0, 0.0)



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
#udp_target_ip = '192.168.1.100'   # <-- AJUSTA a la IP real de tu receptor
#udp_target_port = 8888
udp_target_ip = '127.0.0.1'   # <-- envio al hub de teensy
udp_target_port = 9102


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
# ======= Video =======
class FrameServer:
    """Captura de video + overlay de telemetría (Az/El), tracklets (RA/Dec, timestamp)
    y velocidades (comandada y medida) en °/s.
    """

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

        # Velocidades (comandada y medida)
        self.v_cmd_az = 0.0
        self.v_cmd_el = 0.0
        self.v_meas_az = 0.0
        self.v_meas_el = 0.0

    # --- Helpers ---
    @staticmethod
    def _norm_az_360(az: float) -> float:
        az = az % 360.0
        return az if az >= 0 else az + 360.0

    @staticmethod
    def _deg_to_hms(deg: float) -> str:
        total_seconds = (deg / 360.0) * 24.0 * 3600.0
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        s = total_seconds % 60.0
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    @staticmethod
    def _deg_to_dms(deg: float) -> str:
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

    # Setters de velocidades para overlay
    def update_command_speed(self, vcmd_az_deg_s: float, vcmd_el_deg_s: float) -> None:
        self.v_cmd_az = float(vcmd_az_deg_s)
        self.v_cmd_el = float(vcmd_el_deg_s)

    def update_measured_speed(self, vmeas_az_deg_s: float, vmeas_el_deg_s: float) -> None:
        self.v_meas_az = float(vmeas_az_deg_s)
        self.v_meas_el = float(vmeas_el_deg_s)

    # API para actualizar datos
    def update_values(self, azimut: float, elevacion: float) -> None:
        self.azimut = azimut
        self.elevacion = elevacion

    def update_tracklet(self, ra_deg, dec_deg, ts_iso: str) -> None:
        try:
            self.ra_deg = float(ra_deg) if ra_deg is not None else None
            self.dec_deg = float(dec_deg) if dec_deg is not None else None
        except Exception:
            self.ra_deg = None
            self.dec_deg = None
        self.ts_iso = ts_iso or ""

    # Generación de frame con overlay
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

        # RA/Dec + timestamp del último tracklet (si hay)
        y = 110
        if self.ra_deg is not None and self.dec_deg is not None:
            ra_txt = self._deg_to_hms(self.ra_deg)
            dec_txt = self._deg_to_dms(self.dec_deg)
            cv2.putText(frame, f"RA:  {ra_txt}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            y += 40
            cv2.putText(frame, f"Dec: {dec_txt}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            y += 40
            ts_label = self.ts_iso
            if self._ts_unsynced(ts_label):
                ts_label += " (unsynced)"
            cv2.putText(frame, f"T:   {ts_label}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            y += 40
        else:
            # Si aún no hay RA/Dec, reservamos el espacio para que no “salte” el layout
            y = 150

        # SIEMPRE dibujar velocidades (antes dependía de RA/Dec)
        txt_w = (
            f"wcmd Az/El: {self.v_cmd_az:+.2f}/{self.v_cmd_el:+.2f} deg/s   "
            f"wmeas Az/El: {self.v_meas_az:+.2f}/{self.v_meas_el:+.2f} deg/s"
        )
        cv2.putText(frame, txt_w, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def stop(self) -> None:
        self.running = False
        self.cap.release()

# ======= UDP RX (telemetría para azimut/elevación) =======
def udp_receiver(server: FrameServer):
    #udp_ip = '0.0.0.0'
    #udp_port = 8888
    udp_ip = '127.0.0.1'    # recpcion teensy
    udp_port = 9002
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    sock.bind((udp_ip, udp_port))
    print(f"[UDP RX] Escuchando en {udp_ip}:{udp_port} ...")
    ...


    # Estado para gating (RA/Dec -> JSONL/UI)
    last_send_ms = 0
    last_hb_ms   = 0
    last_ra = None
    last_dec = None

    # Estado para velocidad medida (desde Az/El)
    last_az = None
    last_el = None
    last_t_ms = None
    EMA_ALPHA = 0.2  # suavizado de ωmeas

    while server.running:
        try:
            data, _ = sock.recvfrom(4096)
            if not data:
                continue

            # --- Paquete 33: <ff> az, el ---
            if len(data) >= 12 and data[2] == PACKET_ID_ANGLE:
                azimut, elevacion = struct.unpack_from('<ff', data, offset=4)
                server.update_values(azimut, elevacion)

                # ωmeas (deg/s) con wrap en Az (359->0)
                now_ms = int(time.time() * 1000)
                if last_az is not None and last_el is not None and last_t_ms is not None:
                    dt = max(1e-3, (now_ms - last_t_ms) / 1000.0)
                    delta_az = (azimut - last_az) % 360.0
                    if delta_az > 180.0:
                        delta_az -= 360.0
                    v_az = delta_az / dt
                    v_el = (elevacion - last_el) / dt
                    v_az_f = EMA_ALPHA * v_az + (1 - EMA_ALPHA) * server.v_meas_az
                    v_el_f = EMA_ALPHA * v_el + (1 - EMA_ALPHA) * server.v_meas_el
                    server.update_measured_speed(v_az_f, v_el_f)
                last_az, last_el, last_t_ms = azimut, elevacion, now_ms

                # RA/Dec con UTC de la Pi -> SIEMPRE refresca overlay
                ra_deg, dec_deg, now_ms = altaz_to_radec_pi(azimut, elevacion)
                ts_iso = iso8601_from_ms(now_ms)
                server.update_tracklet(ra_deg, dec_deg, ts_iso)

                # Gating sólo para persistir/emitir tracklet
                send_ok = False
                if (now_ms - last_send_ms) >= TRACKLET_PERIOD_MS:
                    delta_ok = (last_ra is None or
                                abs(ra_deg  - last_ra ) >= TRACKLET_DELTA_MIN_DEG or
                                abs(dec_deg - last_dec) >= TRACKLET_DELTA_MIN_DEG)
                    heartbeat = (now_ms - last_hb_ms) >= TRACKLET_HEARTBEAT_MS
                    send_ok = delta_ok or heartbeat
                    if heartbeat:
                        last_hb_ms = now_ms

                if send_ok:
                    last_send_ms = now_ms
                    last_ra, last_dec = ra_deg, dec_deg

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
                        "az_deg": float(f"{((azimut % 360) + 360) % 360:.2f}"),
                        "el_deg": float(f"{elevacion:.2f}"),
                        "source": "pi",
                        # ωcmd: fallback desde joystick o sobrescrito por paquete 34
                        "wcmd_az_deg_s":  float(f"{server.v_cmd_az:.3f}"),
                        "wcmd_el_deg_s":  float(f"{server.v_cmd_el:.3f}"),
                        # ωmeas: EMA desde Az/El
                        "wmeas_az_deg_s": float(f"{server.v_meas_az:.3f}"),
                        "wmeas_el_deg_s": float(f"{server.v_meas_el:.3f}")
                    }

                    p = current_tracklet_path()
                    with p.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(obj) + "\n")
                    socketio.emit('tracklet', obj)

            # --- Paquete 34: <ffff> wcmd_az, wcmd_el, wmeas_az, wmeas_el ---
            elif len(data) >= 4 + 16 and data[2] == PACKET_ID_OMEGAS:
                plen = data[3]
                if plen >= 16 and len(data) >= 4 + plen:
                    payload  = data[4:4+plen]
                    recv_chk = data[4+plen] if len(data) >= 5 + plen else None
                    if recv_chk is None or ((sum(payload) & 0xFF) != recv_chk):
                        print("[UDP RX][ω] checksum inválido")
                    else:
                        v_cmd_az, v_cmd_el, v_meas_az, v_meas_el = struct.unpack_from('<ffff', payload, offset=0)
                        server.update_command_speed(v_cmd_az, v_cmd_el)
                        server.update_measured_speed(v_meas_az, v_meas_el)
                        # print(f"[ω] cmd=({v_cmd_az:+.2f},{v_cmd_el:+.2f}) meas=({v_meas_az:+.2f},{v_meas_el:+.2f})")

            # (Ignoramos cualquier otra cosa)
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

        # >>> Fallback en la Pi: inferimos ωcmd para overlay y JSONL inmediatamente
        vcmd_az, vcmd_el = joy_to_deg_s(x, y, throttle)
        server.update_command_speed(vcmd_az, vcmd_el)

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
