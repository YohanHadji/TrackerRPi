from flask import Flask, Response, render_template
import cv2
from threading import Thread

class FrameServer:
    def __init__(self, video_device='/dev/video0'):
        print(f"Inicializando captura de video con dispositivo: {video_device}")
        self.cap = cv2.VideoCapture(video_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el dispositivo de video: {video_device}")
        self.running = True

    def get_frame(self):
        if not self.running:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def stop(self):
        self.running = False
        self.cap.release()

app = Flask(__name__)
video_device = '/dev/video0'  # Cambia esto si es necesario
server = FrameServer(video_device)

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

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        server.stop()
