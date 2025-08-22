from flask import Flask, Response, render_template, request
import cv2
import time
from threading import Thread
import socket
import struct
import serial
from flask_socketio import SocketIO, emit

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
    def __init__(self, video_device='/dev/video0'):
        print(f"[Video] Inicializando captura en: {video_device}")
        self.cap = cv2.VideoCapture(video_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el dispositivo de video: {video_device}")
        self.running = True
        self.frame_rate = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.azimut = None
        self.elevacion = None

    def update_values(self, azimut, elevacion):
        self.azimut = azimut
        self.elevacion = elevacion

    def get_frame(self):
        if not self.running:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None

        frame_height, frame_width = frame.shape[:2]
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        millis = int(time.time() * 1000) % 1000
        fps_text = f"FPS: {self.frame_rate:.2f}"

        overlay_text = f"{current_time}.{millis:03d}"
        cv2.putText(frame, overlay_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, fps_text, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        if self.azimut is not None and self.elevacion is not None:
            az_el_text = f"Azimut: {self.azimut:.2f}, Elevación: {self.elevacion:.2f}"
            text_x = 10
            text_y = frame_height - 10
            cv2.putText(frame, az_el_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def stop(self):
        self.running = False
        self.cap.release()

# ======= UDP RX (telemetría para azimut/elevación) =======
def udp_receiver(server: FrameServer):
    udp_ip = '0.0.0.0'
    udp_port = 8888
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))
    print(f"[UDP RX] Escuchando en {udp_ip}:{udp_port} ...")
    while server.running:
        try:
            data, _ = sock.recvfrom(1024)
            if len(data) >= 12:
                packet_id = data[2]
                if packet_id == 33:
                    azimut, elevacion = struct.unpack_from('<ff', data, offset=4)
                    server.update_values(azimut, elevacion)
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
        print(f"[JSK] x={x:.2f} y={y:.2f} thr={throttle:.2f} trig={trigger} -> UDP {udp_target_ip}:{udp_target_port} ({len(pkt)} bytes)")

        emit('ack', {'ok': True}, broadcast=False)
    except Exception as e:
        print("[JSK][ERR]", e)
        emit('ack', {'ok': False, 'error': str(e)}, broadcast=False)

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
