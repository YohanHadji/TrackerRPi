from flask import Flask, render_template, Response, request, stream_with_context
import numpy as np
from communication import *
from camera import *
import threading 
#from picamera2 import Picamera2
import cv2
import time
from detection import *

app = Flask(__name__)

camInit(30)
# picam2 = Picamera2()
# camera_config = picam2.create_video_configuration(main={"format": "BGR888", "size": (800, 606)}, raw={"format": "SRGGB10", "size": (1332, 990)})
# picam2.configure(camera_config)
# picam2.set_controls({"FrameRate": 30})
# picam2.start()


# Variables to store slider and dropdown values
input_values = {
    "idRadius": 25,
    "lockRadius": 100,
    "lightLifetime": 200,
    "lightThreshold": 200,
    "switchFrame": 0,  # Assuming it's initially set to 0
    "gain": 1.0,
    "exposureTime": 100,
    "trackingEnabled": False
}

picam2.set_controls({"AnalogueGain": np.int32(input_values["gain"]), "ExposureTime": np.int32(input_values["exposureTime"])})

# input_values = {}  # Assuming you have a global dictionary to store input values

# Light point structure
class LightPoint:
    def __init__(self, name, isVisible, x, y):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0) for _ in range(10)]

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

    payload_data = struct.pack('iiiiiii', np.int32(input_values["idRadius"]), np.int32(input_values["lockRadius"]), np.int32(input_values["lightLifetime"]), np.int32(input_values["lightThreshold"]), np.int32(input_values["switchFrame"]), np.int32(input_values["exposureTime"], np.int32(input_values["trackingEnabled"])))
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    encoded_packet = bytearray(encoded_packet)
    sock.sendto(encoded_packet, (UDP_IP_TRACKER, UDP_PORT))
    print("Sent settings to tracker")

def generate_frames():
    global LightPointArray, input_values, resolution, picam2

    while True:
        # Capture the frame
        # frame = picam2.capture_array()

        # Get a frame with metadata
        frame, sensorTimeStamp = getFrame()

        if (newPacketReceived()):
            packetType = newPacketReceivedType()
            if (packetType == "pointList"):
                LightPointArray = returnLastPacketData(packetType)

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _dummy, b_frame = cv2.threshold(gray_frame,np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)
                
        printFps()

        # Encode the frame
        if (input_values["switchFrame"] == 0):
            cv2.circle(b_frame, (400,303), input_values["lockRadius"], 255, 2)
            for point in LightPointArray:
                cv2.circle(b_frame, (point.x, point.y), 5, 255, -1)
                cv2.putText(b_frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2, cv2.LINE_AA)
            _, buffer = cv2.imencode('.jpg', b_frame)
            b_frame = buffer.tobytes()
            yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')
        else:
            cv2.circle(frame, (400,303), input_values["lockRadius"], (0, 0, 255), 2)
            for point in LightPointArray:
                cv2.circle(frame, (point.x, point.y), 5, (0, 0, 255), -1)
                cv2.putText(frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            _, buffer = cv2.imencode('.jpg', frame)
            b_frame = buffer.tobytes() 
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