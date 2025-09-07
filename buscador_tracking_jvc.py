import cv2, numpy as np, time, threading, socket, struct, json, traceback, serial, os
from pathlib import Path
from flask import Flask, Response, request, jsonify, render_template
from flask_socketio import SocketIO

# ================== Config ==================
PRA, PRB = 0xFF, 0xFA
PACKET_ID_ANGLE, PACKET_ID_OMEGAS = 33, 34
FALLBACK_DPX = (0.03, 0.03)   # (H,V) deg/pixel fallback

UDP_TARGET_IP   = "192.168.1.100"   # <-- AJUSTA si corresponde
UDP_TARGET_PORT = 8888
UDP_BROADCAST   = False

VIDEO_DEVICE    = "/dev/video0"
HTTP_PORT       = 5010

# Detección / tracking (defaults; pueden cambiarse por /set_ctrl)
LOCK_RADIUS_PX, THRESH_VAL, MIN_BLOB_AREA = 120, 220, 3
ERODE_DILATE_KERNEL = 1
Kp_deg_per_err   = 0.28
MAX_SPEED_DEG_S  = 10.0
EMA_ALPHA_TARGET_PX = 0.35
JOY_DEG_PER_UNIT = 1.0
OFFSET_AZ = 0.0
OFFSET_EL = 0.0

# Señales (signo de ejes)
SIGN_AZ, SIGN_EL = -1, +1

BASE_DIR   = Path(__file__).resolve().parent
CALIB_PATH = BASE_DIR / "jvc_zoom_calib.json"
PREFS_PATH = BASE_DIR / "jvc_prefs.json"

# ================== Estado ==================
zoom_voltage = None
deg_per_px   = FALLBACK_DPX
ema_xy = None
track_enabled = False

telemetry_lock = threading.Lock()
telemetry = dict(az=None, el=None, wcmd_az=0.0, wcmd_el=0.0, wmeas_az=0.0, wmeas_el=0.0)

# ---- tracklets logging ----
TRACK_LOG_HZ = 10.0   # líneas por segundo mientras está tracking ON
track_log_fp = None
track_log_date = None
track_log_lock = threading.Lock()
next_track_log_t = 0.0

def _now_ms():
    t = time.time()
    return t, int(round(t*1000)), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + (".%03d" % int((t%1)*1000))

def _ensure_track_file():
    """Abre/rota el archivo tracklets_YYYYMMDD.jsonl según fecha local cuando se enciende el tracking."""
    global track_log_fp, track_log_date
    ymd = time.strftime("%Y%m%d", time.localtime())
    if track_log_fp is not None and track_log_date == ymd:
        return
    if track_log_fp is not None:
        try:
            track_log_fp.flush()
            track_log_fp.close()
        except Exception:
            pass
    fname = f"tracklets_{ymd}.jsonl"
    fpath = BASE_DIR / fname
    track_log_fp = open(fpath, "a", buffering=1, encoding="utf-8")
    track_log_date = ymd
    print(f"[TRACK] logging -> {fpath}", flush=True)

def _write_tracklet(rec: dict):
    with track_log_lock:
        if track_log_fp is None:
            return
        try:
            track_log_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            print("[TRACK][ERR] write:", e, flush=True)

# ---- LUT zoom ----
try:
    CALIB_LUT = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
except Exception:
    CALIB_LUT = {}

def get_deg_per_px(v):
    if v is None:
        return FALLBACK_DPX
    d = CALIB_LUT.get(f"{v:.2f}")
    if not d:
        return FALLBACK_DPX
    return (float(d.get("h", FALLBACK_DPX[0])), float(d.get("v", FALLBACK_DPX[1])))

# ---- Preferencias persistentes ----
def _save_prefs():
    d = {
        "SIGN_AZ": SIGN_AZ, "SIGN_EL": SIGN_EL,
        "Kp_deg_per_err": Kp_deg_per_err, "MAX_SPEED_DEG_S": MAX_SPEED_DEG_S,
        "JOY_DEG_PER_UNIT": JOY_DEG_PER_UNIT, "OFFSET_AZ": OFFSET_AZ, "OFFSET_EL": OFFSET_EL,
    }
    try:
        PREFS_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
        print("[PREFS] guardado en", PREFS_PATH, flush=True)
    except Exception as e:
        print("[PREFS][ERR] al guardar:", e, flush=True)

def _load_prefs():
    global SIGN_AZ, SIGN_EL, Kp_deg_per_err, MAX_SPEED_DEG_S, JOY_DEG_PER_UNIT, OFFSET_AZ, OFFSET_EL
    if not PREFS_PATH.exists():
        print("[PREFS] no encontrado, se usarán defaults", flush=True)
        return
    try:
        d = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        SIGN_AZ = int(d.get("SIGN_AZ", SIGN_AZ))
        SIGN_EL = int(d.get("SIGN_EL", SIGN_EL))
        Kp_deg_per_err = float(d.get("Kp_deg_per_err", Kp_deg_per_err))
        MAX_SPEED_DEG_S = float(d.get("MAX_SPEED_DEG_S", MAX_SPEED_DEG_S))
        JOY_DEG_PER_UNIT = float(d.get("JOY_DEG_PER_UNIT", JOY_DEG_PER_UNIT))
        OFFSET_AZ = float(d.get("OFFSET_AZ", OFFSET_AZ))
        OFFSET_EL = float(d.get("OFFSET_EL", OFFSET_EL))
        print("[PREFS] cargado:", d, flush=True)
    except Exception as e:
        print("[PREFS][ERR] al leer:", e, flush=True)

# ================== UDP ==================
udp_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
if UDP_BROADCAST:
    udp_tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

def _dest():
    return ("255.255.255.255", UDP_TARGET_PORT) if UDP_BROADCAST else (UDP_TARGET_IP, UDP_TARGET_PORT)

def send_udp_packet(pkt, tag=""):
    try:
        udp_tx.sendto(pkt, _dest())
        if tag:
            print(time.strftime("[%H:%M:%S]"), f"[UDP-TX:{tag}] {len(pkt)}B -> {_dest()}", flush=True)
    except Exception as e:
        print("[UDP-TX][ERR]", e, flush=True)

def pkt_joy_units(x_units, y_units, throttle, trigger):
    payload = struct.pack("iiiiiiff", 1, int(trigger), int(x_units*100), int(y_units*100), 0, 99, float(throttle), 30.0)
    pkt = bytes([PRA, PRB, 1, len(payload)]) + payload
    pkt += bytes([sum(payload) & 0xFF])
    return pkt

def udp_rx_loop():
    print("[UDP-RX] bind 0.0.0.0:", UDP_TARGET_PORT, flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except Exception: pass
    sock.bind(("0.0.0.0", UDP_TARGET_PORT))
    last = time.time(); cnt = 0
    while True:
        try:
            data, _ = sock.recvfrom(4096); cnt += 1
            if not data or len(data) < 4: continue
            pkt_id = data[2]
            if pkt_id == PACKET_ID_ANGLE and len(data) >= 12:
                az, el = struct.unpack_from("<ff", data, offset=4)
                with telemetry_lock:
                    telemetry["az"], telemetry["el"] = float(az), float(el)
            elif pkt_id == PACKET_ID_OMEGAS and len(data) >= 4 + 16:
                plen = data[3]
                if plen >= 16 and len(data) >= 4 + plen + 1:
                    payload = data[4:4+plen]; chk = data[4+plen]
                    if (sum(payload) & 0xFF) == chk:
                        wcmd_az, wcmd_el, wmeas_az, wmeas_el = struct.unpack_from("<ffff", payload, 0)
                        with telemetry_lock:
                            telemetry["wcmd_az"], telemetry["wcmd_el"] = float(wcmd_az), float(wcmd_el)
                            telemetry["wmeas_az"], telemetry["wmeas_el"] = float(wmeas_az), float(wmeas_el)
            if time.time() - last > 2.0:
                with telemetry_lock:
                    print(time.strftime("[%H:%M:%S]"),
                          f"[UDP-RX] Az/El={telemetry['az']}/{telemetry['el']} wmeas={telemetry['wmeas_az']}/{telemetry['wmeas_el']} pkts/2s={cnt}",
                          flush=True)
                last = time.time(); cnt = 0
        except Exception as e:
            print("[UDP-RX][ERR]", e, flush=True)

# ================== Cámara ==================
class JVCCapture:
    def __init__(self, dev):
        self.dev = dev
        print("[CAM] opening", dev, flush=True)
        self.cap = cv2.VideoCapture(dev)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video device {dev}")
        self.lock = threading.Lock()
        self.frame = None
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cnt, t0 = 0, time.time()
        while self.running:
            ok, frm = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frm
                cnt += 1
                if cnt % 120 == 0:
                    fps = cnt / max(1e-3, time.time() - t0)
                    print(time.strftime("[%H:%M:%S]"), f"[CAM] fps~{fps:.1f}", flush=True)
            else:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False
        time.sleep(0.1)
        self.cap.release()
        print("[CAM] stopped", flush=True)

# ======= Arduino (zoom analógico) =======
arduino_port = '/dev/ttyACM0'
arduino_baudrate = 115200
try:
    arduino = serial.Serial(arduino_port, arduino_baudrate, timeout=1)
    time.sleep(2)
    print(f"[Arduino] Conectado en {arduino_port} @ {arduino_baudrate} bps")
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

# ================== Dibujo overlay ==================
def draw_overlay(frm):
    h, w = frm.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.line(frm, (cx-20, cy), (cx+20, cy), (0, 255, 0), 1, cv2.LINE_AA)
    cv2.line(frm, (cx, cy-20), (cx, cy+20), (0, 255, 0), 1, cv2.LINE_AA)
    if ema_xy is not None:
        cv2.circle(frm, (int(ema_xy[0]), int(ema_xy[1])), 6, (0, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frm, (int(ema_xy[0]), int(ema_xy[1])), LOCK_RADIUS_PX, (64, 64, 64), 1, cv2.LINE_AA)
    # Telemetría + tiempo con milisegundos
    t, epoch_ms, now_str = _now_ms()
    with telemetry_lock:
        az = telemetry.get("az"); el = telemetry.get("el")
    azs = "—" if az is None else f"{az:.3f}"
    els = "—" if el is None else f"{el:.3f}"
    dpx = f"{deg_per_px[0]:.5f}/{deg_per_px[1]:.5f}"
    txt1 = f"Az:{azs}  El:{els}  dpx:{dpx}"
    txt2 = now_str
    cv2.putText(frm, txt1, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)
    cv2.putText(frm, txt2, (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)
    return frm

# ================== Detección/Tracking ==================
def detect_brightest(frm, prev_xy=None, lock_radius=LOCK_RADIUS_PX):
    gray = cv2.cvtColor(frm, cv2.COLOR_BGR2GRAY)
    if ERODE_DILATE_KERNEL > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ERODE_DILATE_KERNEL, ERODE_DILATE_KERNEL))
        gray = cv2.morphologyEx(gray, cv2.MORPH_OPEN, k)
    _, bw = cv2.threshold(gray, THRESH_VAL, 255, cv2.THRESH_BINARY)
    cnts = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    if not cnts:
        return None, bw
    cand = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < MIN_BLOB_AREA:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        if prev_xy is not None:
            dx = cx - prev_xy[0]
            dy = cy - prev_xy[1]
            if (dx*dx + dy*dy) > (lock_radius * lock_radius):
                continue
        cand.append((area, cx, cy))
    if not cand:
        return None, bw
    cand.sort(reverse=True, key=lambda t: t[0])
    _, cx, cy = cand[0]
    return (cx, cy), bw

def compute_command_from_error(dx_px, dy_px):
    v_az = SIGN_AZ * (-dx_px * deg_per_px[0] * Kp_deg_per_err) + OFFSET_AZ
    v_el = SIGN_EL * (+dy_px * deg_per_px[1] * Kp_deg_per_err) + OFFSET_EL
    v_az = float(np.clip(v_az, -MAX_SPEED_DEG_S, MAX_SPEED_DEG_S))
    v_el = float(np.clip(v_el, -MAX_SPEED_DEG_S, MAX_SPEED_DEG_S))
    return v_az, v_el

def _send_rate_cmd(v_az_deg_s, v_el_deg_s, throttle=1.0, trigger=1):
    x_units = np.clip(v_az_deg_s/JOY_DEG_PER_UNIT, -30.0, 30.0)
    y_units = np.clip(v_el_deg_s/JOY_DEG_PER_UNIT, -30.0, 30.0)
    send_udp_packet(pkt_joy_units(x_units, y_units, throttle, trigger), "rate")
    with telemetry_lock:
        telemetry["wcmd_az"], telemetry["wcmd_el"] = float(x_units*throttle), float(y_units*throttle)

def controller_loop():
    global ema_xy, next_track_log_t
    last = time.time()
    n = 0
    while True:
        try:
            frm = cam.read()
            if frm is None:
                time.sleep(0.01)
                continue
            h, w = frm.shape[:2]
            cx, cy = w // 2, h // 2
            xy, _ = detect_brightest(frm, prev_xy=ema_xy if track_enabled else None)
            if xy is not None:
                if ema_xy is None:
                    ema_xy = (float(xy[0]), float(xy[1]))
                else:
                    ema_xy = (EMA_ALPHA_TARGET_PX*xy[0] + (1-EMA_ALPHA_TARGET_PX)*ema_xy[0],
                              EMA_ALPHA_TARGET_PX*xy[1] + (1-EMA_ALPHA_TARGET_PX)*ema_xy[1])
            else:
                if ema_xy is not None:
                    ema_xy = (0.95*ema_xy[0] + 0.05*cx, 0.95*ema_xy[1] + 0.05*cy)
            if track_enabled and ema_xy is not None:
                dx = ema_xy[0] - cx
                dy = ema_xy[1] - cy
                v_az, v_el = compute_command_from_error(dx, dy)
                _send_rate_cmd(v_az, v_el, 1.0, 1)
                # --- tracklets JSONL cada 1/TRACK_LOG_HZ s ---
                t, epoch_ms, now_str = _now_ms()
                if t >= next_track_log_t:
                    with telemetry_lock:
                        rec = {
                            "ts": now_str,
                            "epoch_ms": epoch_ms,
                            "az": telemetry.get("az"),
                            "el": telemetry.get("el"),
                            "wcmd_az": telemetry.get("wcmd_az"),
                            "wcmd_el": telemetry.get("wcmd_el"),
                            "wmeas_az": telemetry.get("wmeas_az"),
                            "wmeas_el": telemetry.get("wmeas_el"),
                            "deg_per_px": {"h": deg_per_px[0], "v": deg_per_px[1]},
                            "cx": cx, "cy": cy,
                            "tx": float(ema_xy[0]), "ty": float(ema_xy[1]),
                            "dx_px": float(dx), "dy_px": float(dy),
                            "v_az": float(v_az), "v_el": float(v_el),
                            "zoom_v": zoom_voltage
                        }
                    _write_tracklet(rec)
                    next_track_log_t = t + 1.0/float(TRACK_LOG_HZ)
            n += 1
            if time.time() - last > 1.0:
                print(time.strftime("[%H:%M:%S]"),
                      f"[CTRL] track={track_enabled} ema={ema_xy} dpx={deg_per_px} signs=({SIGN_AZ},{SIGN_EL}) iter/s~{n}",
                      flush=True)
                last = time.time()
                n = 0
        except Exception as e:
            print("[CTRL][ERR]", e, flush=True)
            time.sleep(0.05)

# ================== Flask/Socket.IO ==================
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index():
    return render_template("Ojvc_index.html")

@app.route("/Ojvc_index.html")
def legacy_index():
    return render_template("Ojvc_index.html")

@app.route("/video_feed")
def video_feed():
    def generate():
        last = time.time()
        while True:
            try:
                frm = cam.read()
                if frm is None:
                    time.sleep(0.01)
                    continue
                frm = draw_overlay(frm)
                ok, jpg = cv2.imencode(".jpg", frm, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if not ok:
                    continue
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
                if time.time() - last > 2.0:
                    print(time.strftime("[%H:%M:%S]"), "[HTTP] mjpeg OK", flush=True)
                    last = time.time()
            except GeneratorExit:
                print("[HTTP] video client gone", flush=True); break
            except Exception as e:
                print("[HTTP][ERR] video loop:", e, flush=True); time.sleep(0.05)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

def _snapshot_bytes():
    frm = cam.read()
    if frm is None:
        return None
    frm = draw_overlay(frm)
    ok, jpg = cv2.imencode(".jpg", frm, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return jpg.tobytes() if ok else None

@app.route("/snapshot.jpg")
def snapshot_jpg():
    b = _snapshot_bytes()
    if b is None:
        return "no frame", 503
    resp = Response(b, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/snapshot")
def snapshot():
    return snapshot_jpg()

@app.route("/status")
def status():
    t, epoch_ms, now_str = _now_ms()
    with telemetry_lock:
        s = dict(track=track_enabled,
                 dpx=[deg_per_px[0], deg_per_px[1]],
                 signs=[SIGN_AZ, SIGN_EL],
                 az=telemetry.get("az"), el=telemetry.get("el"),
                 wcmd=[telemetry.get("wcmd_az"), telemetry.get("wcmd_el")],
                 wmeas=[telemetry.get("wmeas_az"), telemetry.get("wmeas_el")])
    s["now"] = now_str
    s["epoch_ms"] = epoch_ms
    s["zoom_v"] = zoom_voltage
    return jsonify(s)

@app.route("/toggle_tracking", methods=["POST"])
def toggle_tracking():
    global track_enabled, next_track_log_t
    track_enabled = not track_enabled
    if track_enabled:
        _ensure_track_file()
        next_track_log_t = 0.0
        print("[TRACK] ON", flush=True)
    else:
        _send_rate_cmd(0.0, 0.0, 1.0, 1)
        print("[TRACK] OFF", flush=True)
    return f"Tracking: {'ON' if track_enabled else 'OFF'}"

@app.route("/set_signs", methods=["POST"])
def set_signs():
    global SIGN_AZ, SIGN_EL
    data = request.get_json(silent=True) or {}
    SIGN_AZ = -1 if bool(data.get("flip_az", False)) else +1
    SIGN_EL = -1 if bool(data.get("flip_el", False)) else +1
    _save_prefs()
    print("[HTTP] set_signs ->", SIGN_AZ, SIGN_EL, flush=True)
    return f"Signs AZ={SIGN_AZ} EL={SIGN_EL}"

@app.route("/set_zoom", methods=["POST"])
def set_zoom():
    global zoom_voltage, deg_per_px
    v = None
    if request.is_json:
        try: v = float((request.get_json(silent=True) or {}).get("voltage"))
        except Exception: v = None
    if v is None and request.form:
        try: v = float(request.form.get("voltage"))
        except Exception: v = None
    if v is None:
        return "Falta parámetro 'voltage'", 400
    if not (0.0 <= v <= 3.0):
        return "voltage out of range [0..3]", 400
    zoom_voltage = v
    deg_per_px = get_deg_per_px(zoom_voltage)
    try: send_to_arduino(f"{zoom_voltage:.2f}")
    except Exception as e: print("[Arduino][ERR] al enviar zoom:", e)
    print("[HTTP] set_zoom ->", zoom_voltage, "deg/px=", deg_per_px, flush=True)
    return f"Zoom {zoom_voltage:.2f} V | deg/px H/V = {deg_per_px[0]:.5f}/{deg_per_px[1]:.5f}"

@app.route("/set_device", methods=["POST"])
def set_device():
    global cam, VIDEO_DEVICE
    dev = (request.get_json(silent=True) or {}).get("device") if request.is_json else request.form.get("device")
    if not dev: return "falta 'device'", 400
    try:
        if cam is not None: cam.stop()
        VIDEO_DEVICE = str(dev)
        cam = JVCCapture(VIDEO_DEVICE)
        return f"OK device={VIDEO_DEVICE}", 200
    except Exception as e:
        print("[CAM][ERR] al abrir", dev, ":", e, flush=True)
        return f"ERR al abrir {dev}: {e}", 500

# ---- Calibración ----
def _read_angles():
    with telemetry_lock:
        return telemetry.get("az"), telemetry.get("el")

def _get_target_xy(samples=4, delay=0.05):
    vals = []
    for _ in range(samples):
        frm = cam.read()
        if frm is None:
            time.sleep(delay); continue
        xy, _ = detect_brightest(frm, prev_xy=None)
        if xy: vals.append(xy)
        time.sleep(delay)
    if not vals: return None
    xs = [v[0] for v in vals]; ys = [v[1] for v in vals]
    return (sum(xs)/len(xs), sum(ys)/len(ys))

def _jog(az_deg_s, el_deg_s, dur):
    _send_rate_cmd(az_deg_s, el_deg_s, 1.0, 1)
    time.sleep(max(0.05, float(dur)))
    _send_rate_cmd(0.0, 0.0, 1.0, 1)

@app.route("/calibrate", methods=["POST"])
def calibrate():
    global deg_per_px
    try:
        data = request.get_json(silent=True) or {}
        spd = float(data.get("spd", 5.0))      # deg/s
        dur = float(data.get("dur", 0.8))      # s

        xy0 = _get_target_xy()
        if not xy0:
            return jsonify({"ok": False, "err": "No target detected"}), 409
        az0, el0 = _read_angles()
        _jog(spd, 0.0, dur)
        time.sleep(0.15)
        xy1 = _get_target_xy()
        az1, el1 = _read_angles()
        if not xy1 or az0 is None or az1 is None:
            return jsonify({"ok": False, "err": "No telemetry or target after AZ jog"}), 409
        dx  = float(xy1[0] - xy0[0])
        dAz = float(az1 - az0)
        h_dpx = abs(dAz) / max(1.0, abs(dx))

        xy0b = _get_target_xy()
        az0b, el0b = _read_angles()
        _jog(0.0, spd, dur)
        time.sleep(0.15)
        xy1b = _get_target_xy()
        az1b, el1b = _read_angles()
        if not xy1b or el0b is None or el1b is None:
            return jsonify({"ok": False, "err": "No telemetry or target after EL jog"}), 409
        dy  = float(xy1b[1] - xy0b[1])
        dEl = float(el1b - el0b)
        v_dpx = abs(dEl) / max(1.0, abs(dy))

        deg_per_px = (h_dpx, v_dpx)
        try:
            v = zoom_voltage
            if v is not None:
                d = CALIB_LUT.get(f"{v:.2f}", {})
                d["h"] = h_dpx; d["v"] = v_dpx
                CALIB_LUT[f"{v:.2f}"] = d
                CALIB_PATH.write_text(json.dumps(CALIB_LUT, indent=2), encoding="utf-8")
        except Exception as e:
            print("[CALIB][WARN] save:", e, flush=True)

        return jsonify({"ok": True, "deg_per_px": {"h": h_dpx, "v": v_dpx}, "spd": spd, "dur": dur})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

# ---- Socket.IO joystick ----
@socketio.on("connect")
def on_connect():
    print("[IO] connect", flush=True)

@socketio.on("disconnect")
def on_disconnect():
    print("[IO] disconnect", flush=True)

@socketio.on("joystick_update")
def handle_joystick_update(data):
    try:
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        throttle = float(data.get("throttle", 1.0))
        trigger  = int(data.get("trigger", 1))
        pkt = pkt_joy_units(x, y, throttle, trigger)
        send_udp_packet(pkt, "joy")
        with telemetry_lock:
            telemetry["wcmd_az"], telemetry["wcmd_el"] = x*throttle, y*throttle
    except Exception as e:
        print("[IO][ERR]", e, flush=True)
        traceback.print_exc()

# ---- Control/Persistencia ----
@app.route("/get_prefs")
def get_prefs():
    with telemetry_lock:
        d = {
            "SIGN_AZ": SIGN_AZ,
            "SIGN_EL": SIGN_EL,
            "Kp_deg_per_err": Kp_deg_per_err,
            "MAX_SPEED_DEG_S": MAX_SPEED_DEG_S,
            "JOY_DEG_PER_UNIT": JOY_DEG_PER_UNIT,
            "OFFSET_AZ": OFFSET_AZ,
            "OFFSET_EL": OFFSET_EL,
        }
    return jsonify(d)

@app.route("/set_ctrl", methods=["POST"])
def set_ctrl():
    global Kp_deg_per_err, MAX_SPEED_DEG_S, JOY_DEG_PER_UNIT, OFFSET_AZ, OFFSET_EL
    d = request.get_json(silent=True) or {}
    try:
        if "kp" in d:           Kp_deg_per_err = float(d["kp"])
        if "max_speed" in d:    MAX_SPEED_DEG_S = float(d["max_speed"])
        if "joy_unit" in d:     JOY_DEG_PER_UNIT = float(d["joy_unit"])
        if "offset_az" in d:    OFFSET_AZ = float(d["offset_az"])
        if "offset_el" in d:    OFFSET_EL = float(d["offset_el"])
        _save_prefs()
        print("[HTTP] set_ctrl", Kp_deg_per_err, MAX_SPEED_DEG_S, JOY_DEG_PER_UNIT, OFFSET_AZ, OFFSET_EL, flush=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400

# ---- Main ----
def main():
    global cam
    _load_prefs()
    threading.Thread(target=udp_rx_loop, daemon=True).start()
    cam = JVCCapture(VIDEO_DEVICE)
    threading.Thread(target=controller_loop, daemon=True).start()
    print("[HTTP] serving on 0.0.0.0:%d" % HTTP_PORT, flush=True)
    socketio.run(app, host="0.0.0.0", port=HTTP_PORT)

if __name__ == "__main__":
    main()