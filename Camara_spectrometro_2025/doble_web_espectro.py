from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
from picamera2 import Picamera2
import threading
import numpy as np
import cv2
import datetime
import csv
import os
import time
from calibracion_CAM01 import pixel_to_wavelength
log_file = "logs/log.txt"
os.makedirs("logs", exist_ok=True)

def registrar_log(mensaje):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entrada = f"[{timestamp}] {mensaje}"
    with open(log_file, "a") as f:
        f.write(entrada + "\n")
    print(entrada)
    socketio.emit("nuevo_log", {"mensaje": entrada})


# === CONFIGURACIÓN GENERAL ===
app = Flask(__name__)
socketio = SocketIO(app)
os.makedirs("datos", exist_ok=True)

# === CÁMARAS ===
picam_spectro = Picamera2(0)
picam_spectro.configure(picam_spectro.create_preview_configuration(main={"size": (1280, 720), "format": "BGR888"}))
picam_spectro.start()

picam_rgb = Picamera2(1)
picam_rgb.configure(picam_rgb.create_preview_configuration(main={"size": (1280, 720), "format": "BGR888"}))
picam_rgb.start()

# === VARIABLES GLOBALES ===
paused = False
autodisparo = False
integrando = False
grabando = False
duracionVideo = 3
umbral = 50
roi_top = 0.4
roi_height = 0.2
xmin_nm = 400
xmax_nm = 780
integracion_frames = []
writer_video = None
writer_video_rgb = None

# === THREAD DE VIDEO PARA STREAMING ===
def generate_frames(camera):
    while True:
        if paused:
            time.sleep(0.1)
            continue
        frame = camera.capture_array()
        _, buffer = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_spectro')
def video_spectro():
    return Response(generate_frames(picam_spectro), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_rgb')
def video_rgb():
    return Response(generate_frames(picam_rgb), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('index.html')
@app.route('/api/log')
def leer_log():
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lineas = f.readlines()
    else:
        lineas = []
    return jsonify({"log": lineas})
@app.route('/api/clear_log', methods=['POST'])
def clear_log():
    open(log_file, "w").close()
    return jsonify({"status": "log borrado"})

# === CONTROL DE PARÁMETROS DESDE LA INTERFAZ ===
@app.route('/api/control', methods=['POST'])
def control():
    global paused, autodisparo, integrando, duracionVideo, grabando, umbral, xmin_nm, xmax_nm
    data = request.json
    if 'pause' in data:
        paused = data['pause']
    if 'umbral' in data:
        umbral = int(data['umbral'])
    if 'xmin' in data:
        xmin_nm = int(data['xmin'])
    if 'xmax' in data:
        xmax_nm = int(data['xmax'])
    if 'autodisparo' in data:
        autodisparo = data['autodisparo']
    if 'duracionVideo' in data:
        duracionVideo = int(data['duracionVideo'])
    return jsonify({"status": "ok"})

# === GUARDAR VIDEO RGB AUTOMÁTICAMENTE CON NOMBRE BASE ===
def grabar_video_rgb(nombre_base, duracion):
    writer = cv2.VideoWriter(f"datos/{nombre_base}_rgb.avi", cv2.VideoWriter_fourcc(*'XVID'), 10, (1280, 720))
    t0 = time.time()
    while time.time() - t0 < duracion:
        frame_rgb = picam_rgb.capture_array()
        writer.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))
        time.sleep(0.1)
    writer.release()
    print(f"🎞️ Video RGB guardado: {nombre_base}_rgb.avi")
    registrar_log(f"🎞️ Video RGB guardado: {nombre_base}_rgb.avi")

# === GUARDAR ESPECTRO: IMAGEN + CSV + VIDEO RGB ===
def guardar_datos(frame, perfil, etiqueta=None):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"espectro_{timestamp}"
    if etiqueta:
        base += f"_{etiqueta}"

    cv2.imwrite(f"datos/{base}.jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    
    datos = [(pixel_to_wavelength(i), val) for i, val in enumerate(perfil)]
    datos.sort(key=lambda x: x[0])
    with open(f"datos/{base}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Longitud de onda (nm)", "Intensidad"])
        writer.writerows(datos)
    
    if etiqueta == "integrado":
        registrar_log(f"🧪 Espectro integrado guardado: {base}")
    elif etiqueta:
        registrar_log(f"✅ Espectro guardado ({etiqueta}): {base}")
    else:
        registrar_log(f"✅ Espectro guardado: {base}")

    if duracionVideo:
        threading.Thread(target=grabar_video_rgb, args=(base, duracionVideo), daemon=True).start()

@app.route('/api/guardar', methods=['POST'])
def guardar_manual():
    frame = picam_spectro.capture_array()
    h = frame.shape[0]
    y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
    frame_roi = frame[y1:y2, :]
    gray = cv2.cvtColor(frame_roi, cv2.COLOR_RGB2GRAY)
    perfil = np.mean(gray, axis=0)
    guardar_datos(frame_roi, perfil)
    return jsonify({"status": "espectro guardado"})

@app.route('/api/grabar', methods=['POST'])
def toggle_grabar():
    global grabando, writer_video, writer_video_rgb
    if not grabando:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        writer_video = cv2.VideoWriter(f"datos/video_spectro_{ts}.avi", cv2.VideoWriter_fourcc(*'XVID'), 10, (1280, 720))
        writer_video_rgb = cv2.VideoWriter(f"datos/video_rgb_{ts}.avi", cv2.VideoWriter_fourcc(*'XVID'), 10, (1280, 720))
        grabando = True
        print("🔴 Grabando ambas cámaras")
        registrar_log("🔴 Grabando ambas cámaras")
        
    else:
        if writer_video:
            writer_video.release()
        if writer_video_rgb:
            writer_video_rgb.release()
        grabando = False
        print("⏹️ Grabación detenida")
        registrar_log("⏹️ Grabación detenida")
    return jsonify({"status": "ok"})

@app.route('/api/integrar', methods=['POST'])
def iniciar_integracion():
    global integrando, integracion_frames
    duracion = request.json.get("duracion", 3)
    integrando = True
    integracion_frames = []
    threading.Thread(target=terminar_integracion, args=(duracion,), daemon=True).start()
    return jsonify({"status": "integrando"})

def terminar_integracion(duracion):
    global integrando
    time.sleep(duracion)
    if integracion_frames:
        suma = np.sum(integracion_frames, axis=0)
        perfil = suma / len(integracion_frames)
        frame = picam_spectro.capture_array()
        h = frame.shape[0]
        y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
        frame_roi = frame[y1:y2, :]
        guardar_datos(frame_roi, perfil, etiqueta="integrado")
    integrando = False


# === LOOP PRINCIPAL DE PROCESAMIENTO ESPECTRAL ===
def espectro_loop():
    global integrando, integracion_frames
    while True:
        if paused:
            time.sleep(0.1)
            continue

        frame = picam_spectro.capture_array()
        h = frame.shape[0]
        y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
        frame_roi = frame[y1:y2, :]
        gray = cv2.cvtColor(frame_roi, cv2.COLOR_RGB2GRAY)
        profile = np.mean(gray, axis=0)

        x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
        mask = [(x >= xmin_nm and x <= xmax_nm) for x in x_nm]
        x_filtered = np.array(x_nm)[mask].tolist()
        y_filtered = np.array(profile)[mask].tolist()

        socketio.emit('espectro_data', {'x': x_filtered, 'y': y_filtered})

        if autodisparo and max(profile) > umbral:
            guardar_datos(frame_roi, profile)

        if integrando:
            integracion_frames.append(profile)

        if grabando:
            writer_video.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            frame_rgb = picam_rgb.capture_array()
            writer_video_rgb.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

        time.sleep(0.2)

# === INICIAR THREAD DE PROCESAMIENTO ===
threading.Thread(target=espectro_loop, daemon=True).start()

# === MAIN ===
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
