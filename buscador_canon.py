from flask import Flask, Response, render_template, request
import cv2
import time
from threading import Thread
import socket
import struct
import serial


class FrameServer:
    def __init__(self, video_device='/dev/video0'):
        print(f"Inicializando captura de video con dispositivo: {video_device}")
        self.cap = cv2.VideoCapture(video_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el dispositivo de video: {video_device}")
        self.running = True
        self.frame_rate = self.cap.get(cv2.CAP_PROP_FPS) or 30  # Default to 30 FPS if not provided
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

        # Obtener las dimensiones del marco
        frame_height, frame_width = frame.shape[:2]

        # Obtener el tiempo actual y formatearlo
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        millis = int(time.time() * 1000) % 1000
        fps_text = f"FPS: {self.frame_rate:.2f}"

        # Añadir la información de tiempo y FPS al marco
        overlay_text = f"{current_time}.{millis:03d}"
        cv2.putText(frame, overlay_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, fps_text, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Añadir azimut y elevación en la parte inferior del marco
        if self.azimut is not None and self.elevacion is not None:
            az_el_text = f"Azimut: {self.azimut:.2f}, Elevación: {self.elevacion:.2f}"
            text_size = cv2.getTextSize(az_el_text, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]  # Tamaño del texto
            text_x = 10  # Posición horizontal (izquierda)
            text_y = frame_height - 10  # Posición vertical (10 píxeles desde la parte inferior)

            # Dibujar el texto
            cv2.putText(frame, az_el_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Codificar el marco a JPEG
        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def stop(self):
        self.running = False
        self.cap.release()


def udp_receiver(server):
    """
    Hilo para recibir datos UDP y actualizar azimut y elevación en el servidor.
    """
    udp_ip = '0.0.0.0'
    udp_port = 8888

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))
    print(f"Escuchando datos UDP en {udp_ip}:{udp_port}...")

    while server.running:
        try:
            data, _ = sock.recvfrom(1024)
            if len(data) >= 12:
                packet_id = data[2]
                if packet_id == 33:
                    azimut, elevacion = struct.unpack_from('<ff', data, offset=4)
                    server.update_values(azimut, elevacion)
        except Exception as e:
            print(f"Error en UDP receiver: {e}")

    sock.close()


app = Flask(__name__)
video_device = '/dev/video0'  # Cambia esto si es necesario
server = FrameServer(video_device)

# Configuración del puerto serie para Arduino
arduino_port = '/dev/ttyACM1'  # Cambia esto según tu sistema
arduino_baudrate = 921620
arduino = serial.Serial(arduino_port, arduino_baudrate, timeout=1)


def send_to_arduino(command):
    try:
        arduino.write((command + '\n').encode())
        print(f"Comando enviado al Arduino: {command}")
    except Exception as e:
        print(f"Error al enviar comando al Arduino: {e}")


@app.route('/')
def index():
    return render_template('buscador_canon_index.html')


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


@app.route('/zoom_in', methods=['POST'])
def zoom_in():
    send_to_arduino("1")
    return "OK", 200


@app.route('/zoom_out', methods=['POST'])
def zoom_out():
    send_to_arduino("2")
    return "OK", 200


@app.route('/rec', methods=['POST'])
def rec():
    send_to_arduino("3")
    return "OK", 200


if __name__ == '__main__':
    try:
        # Iniciar el hilo para recibir datos UDP
        udp_thread = Thread(target=udp_receiver, args=(server,))
        udp_thread.daemon = True
        udp_thread.start()

        # Iniciar el servidor Flask
        app.run(host='0.0.0.0', port=5002, threaded=True)
    finally:
        server.stop()
        arduino.close()
