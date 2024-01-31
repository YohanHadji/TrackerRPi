from flask import Flask, render_template, Response, request, stream_with_context
import numpy as np
from communication import *
from camera import *
import threading 
#from picamera2 import Picamera2
import cv2
import time
from detection import *
import math

app = Flask(__name__)

#camInit(30)
camInit180(30)

img_width = 2028
img_height = 1520

img_width = 800
img_height = 606

# azimuth = 270
# elevation = 90

xPos = 0
yPos = 0

# Variables to store slider and dropdown values
input_values = {
    "idRadius": 25,
    "lockRadius": 100,
    "lightLifetime": 200,
    "lightThreshold": 200,
    "switchFrame": 0,  # Assuming it's initially set to 0
    "gain": 1.0,
    "exposureTime": 100,
    "trackingEnabled": 0
}

picam2.set_controls({"AnalogueGain": np.int32(input_values["gain"]), "ExposureTime": np.int32(input_values["exposureTime"])})

# input_values = {}  # Assuming you have a global dictionary to store input values

# Light point structure
class LightPoint:
    def __init__(self, name, isVisible, x, y, age):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type
        self.age = int(age)

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age = 0) for _ in range(10)]

def udp_listener():
    UDP_IP = "0.0.0.0" 
    UDP_PORT = 8888

    sock = socket.socket(socket.AF_INET, # Internet
                         socket.SOCK_DGRAM) # UDP
    sock.bind((UDP_IP, UDP_PORT))

    while True:
        data, addr = sock.recvfrom(1024) 
        # Decode the data with capsule
        for byte in data:
            capsule_instance.decode(byte)

def sendSettingToTracker():
    global input_values, sock
    # Send the target point to the teensy, the structure should be copied in a byte array then encoded then sent
    packet_id = 0x10
    # Pack the struct in a byte array

    payload_data = struct.pack('iiiiiii', np.int32(input_values["idRadius"]), np.int32(input_values["lockRadius"]), np.int32(input_values["lightLifetime"]), np.int32(input_values["lightThreshold"]), np.int32(input_values["switchFrame"]), np.int32(input_values["exposureTime"]), np.int32(input_values["trackingEnabled"]))
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    encoded_packet = bytearray(encoded_packet)
    sock.sendto(encoded_packet, (UDP_IP_TRACKER, UDP_PORT))
    print("Sent settings to tracker")


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
    # print(x,y)
    return int(x), int(y)

def generate_frames():
    global LightPointArray, input_values, resolution, picam2, xPos, yPos, img_width, img_height

    while True:
        # Capture the frame
        # frame = picam2.capture_array()

        # Get a frame with metadata
        frame, sensorTimeStamp = getFrame()
        frame = cv2.resize(frame, (507, 380))

        if (newPacketReceived()):
            packetType = newPacketReceivedType()
            if (packetType == "pointList"):
                LightPointArray = returnLastPacketData(packetType)
            if (packetType == "dataFromTracker"):
                trackerAzm, trackerElv = returnLastPacketData(packetType)
                # print(trackerAzm)
                # print(trackerElv)
                xPos, yPos = fisheye_to_pixel(trackerAzm, 90-trackerElv, img_width, img_height)
                # Draw a white point on the frame at coordinate x and y (in pixels)


        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _dummy, b_frame = cv2.threshold(gray_frame,np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)
                
        printFps()

        # Encode the frame
        if (input_values["switchFrame"] == 0):
            # cv2.circle(b_frame, (400,303), input_values["lockRadius"], 255, 2)
            # for point in LightPointArray:
            #     cv2.circle(b_frame, (point.x, point.y), 5, 255, -1)
            #     cv2.putText(b_frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2, cv2.LINE_AA)
            #cv2.circle(frame, (xPos, yPos), 5, 255, -1)
            #_, buffer = cv2.imencode('.jpg', b_frame)
            file_path = 'imgTest.jpg'  # Update with the correct file path
            # Read all bytes from the image file into a buffer
            with open(file_path, 'rb') as file:
                b_frame = file.read()
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')
        else:
            # cv2.circle(frame, (400,303), input_values["lockRadius"], (0, 0, 255), 2)
            # for point in LightPointArray:
            #     cv2.circle(frame, (point.x, point.y), 5, (0, 0, 255), -1)
            #     cv2.putText(frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            #cv2.circle(frame, (xPos, yPos), 5, (0,0, 255), -1)
            #_, buffer = cv2.imencode('.jpg', frame)
            file_path = 'imgTest.jpg'  # Update with the correct file path

            # Read all bytes from the image file into a buffer
            with open(file_path, 'rb') as file:
                b_frame = file.read()
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/update_variable', methods=['POST'])
def update_variable():
    global input_values

    data = request.get_json()
    control_id = data.get("id")
    value = data.get("value")

    if control_id in input_values:
        input_values[control_id] = int(value)
        print(f"Slider {control_id} updated to {value}")
        sendSettingToTracker()
        setCameraSettings(input_values["gain"], input_values["exposureTime"])
    else:
        print(f"Unknown control ID: {control_id}")
    
    #picam2.set_controls({"AnalogueGain": np.int32(input_values["gain"]), "ExposureTime": np.int32(input_values["exposureTime"])})

    return "Variable updated successfully!"

if __name__ == '__main__':
    try:
        udp_thread = threading.Thread(target=udp_listener)
        udp_thread.start()
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        picam2.stop()