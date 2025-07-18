from flask import Flask, render_template, Response
import cv2
import numpy as np
from picamera2 import Picamera2
import time
import socket 
import threading 
import math
app = Flask(__name__)



global_frame = None
img_width = 2028
img_height = 1520

azimuth = 270
elevation = 90
# Inicializar Picamera2
picam2 = Picamera2()
#config = picam2.create_video_configuration(raw={'format': 'SRGGB10', 'size': (1332, 990)})
camera_config = picam2.create_video_configuration(main={"format": "XRGB8888", "size": (2028, 1520)})
picam2.configure(camera_config)

picam2.start()

# def capturar_y_guardar_imagen():
#     frame = picam2.capture_array()
#     cv2.imwrite('/home/pi/imagen.jpg', frame)

def fisheye_to_pixel(azimuth, elevation, img_width, img_height):
    """
    Convierte coordenadas azimutales y de elevación a coordenadas de píxeles en una imagen
    capturada con una lente ojo de pez de 190 grados.

    :param azimuth: Ángulo azimutal en grados (0-360).
    :param elevation: Ángulo de elevación en grados (0-90).
    :param img_width: Ancho de la imagen en píxeles.
    :param img_height: Altura de la imagen en píxeles.
    :return: Coordenadas de píxeles (x, y) en la imagen.
    """

    # Convertir grados a radianes
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)

    # La distancia radial máxima corresponde a un ángulo de 95 grados en la proyección
    # (un poco más de 90 para cubrir toda la imagen).
    # Usamos 95 para asegurarnos de que los bordes de la imagen están dentro del campo de visión.
    max_angle_rad = math.radians(95)
    max_radius = min(img_width, img_height) / 2

    # Calcular la distancia radial en la imagen
    # La relación es lineal en una proyección ojo de pez equidistante.
    radius = (elevation_rad / max_angle_rad) * max_radius

    # Convertir coordenadas polares a coordenadas cartesianas
    x = radius * math.sin(azimuth_rad) + img_width / 2
    y = radius * math.cos(azimuth_rad) + img_height / 2
    print(x,y)
    return int(x), int(y)



def draw_calibration(image, fov, center, horizon_line):
    # Dibujar las líneas de azimut
    num_azimuth_lines = 6  # Por ejemplo, dividir el azimut en 24 líneas
    for i in range(num_azimuth_lines):
        angle = (i / num_azimuth_lines) * fov - (fov / 2)  # ángulo en grados
        radians = np.deg2rad(angle)  # convertir a radianes
        # Calcular el punto final de la línea de azimut
        line_end_x = int(center[0] + np.cos(radians) * center[0])
        line_end_y = int(center[1] - np.sin(radians) * center[0])  # restar porque el eje y es inverso
        cv2.line(image, center, (line_end_x, line_end_y), (255, 0, 0), 2)

    # Dibujar las líneas de elevación (arcos)
    num_elevation_arcs = 4  # Por ejemplo, dividir la elevación en 4 arcos
    for i in range(1, num_elevation_arcs + 1):
        radius = int((horizon_line / num_elevation_arcs) * i)
        cv2.ellipse(image, center, (radius, radius), 0, -fov / 2, fov / 2, (0, 255, 0), 2)

    return image



def draw_calibration_with_labels(image, fov, center, horizon_line):
    # Dibujar las líneas de azimut y elevación
    image = draw_calibration(image, fov, center, horizon_line)
    
    # Definir la fuente y tamaño del texto
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    color = (255, 255, 255)  # Blanco
    
    # Dibujar los puntos cardinales
    cardinal_points = {'N': (center[0], horizon_line + 10),
                       'S': (center[0], horizon_line - 10),
                       'E': (center[0] + 10, center[1]),
                       'W': (center[0] - 10, center[1])}
    
    for point, position in cardinal_points.items():
        cv2.putText(image, point, position, font, font_scale, color, 1, cv2.LINE_AA)
    
    # Dibujar los números para los grados de azimut
    for angle in range(0, 360, 10):
        radians = np.deg2rad(angle - fov / 2)
        text_x = int(center[0] + np.cos(radians) * (center[0] - 20))
        text_y = int(center[1] - np.sin(radians) * (center[0] - 20))
        cv2.putText(image, str(angle), (text_x, text_y), font, font_scale, color, 1, cv2.LINE_AA)
    
    return image




def udp_listener():
    UDP_IP = "0.0.0.0"  # Escuchar en todas las interfaces
    UDP_PORT = 8888 # Puerto en el que escuchar

    sock = socket.socket(socket.AF_INET, # Internet
                          socket.SOCK_DGRAM) # UDP
    sock.bind((UDP_IP, UDP_PORT))

    # data, addr = sock.recvfrom(1024)
    # mensaje = data.decode('utf-8').strip()  # Decodificar y quitar espacios en blanco y caracteres de nueva línea
    # print(mensaje)  # Imprimir solo los datos decodificados
    x, y = fisheye_to_pixel(azimuth, elevation, img_width, img_height)
    print(x,y)
    
        
def detect_and_draw_luminous_points(frame):
    # Convertir a escala de grises
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Aplicar umbralización para detectar áreas luminosas
    _, thresholded = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    # Encontrar contornos
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        # Calcular el centroide de cada contorno
        M = cv2.moments(cnt)
        if M['m00'] != 0:
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
            # Dibujar un círculo en el centroide
            cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
            x, y = fisheye_to_pixel(azimuth, elevation, img_width, img_height)
            cv2.circle(frame, (x, y), 10, (0, 0, 255), -1)  # Dibuja un círculo rojo
           # cv2.circle(frame,(2004,380),15,(0,0,255),-1) test de impresion por pantalla
    return frame

def gen_frames():
    while True:
        frame = picam2.capture_array()
        frame = detect_and_draw_luminous_points(frame)
        
        # Calibrar el frame con azimut y elevación
        center = (frame.shape[1] // 2, frame.shape[0] // 2)
        horizon_line = frame.shape[0] // 2
        frame = draw_calibration_with_labels(frame, 190, center, horizon_line)
        
        # Codificar el frame para la transmisión
        _, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


# @app.route('/capturar_imagen')
# def captura_imagen():
#     capturar_y_guardar_imagen()
#     return "Imagen capturada y guardada."
       

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    # Ruta principal que renderiza la plantilla HTML
    return render_template('index.html')


if __name__ == '__main__':
    try:
        # Iniciar el hilo de actualización de imagen
        udp_thread = threading.Thread(target=udp_listener)
        udp_thread.start()
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        picam2.stop()
