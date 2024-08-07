from flask import Flask, render_template, Response, request
from picamera import PiCamera
from picamera.array import PiRGBArray
import cv2
import io
import time
import serial
from capsule import *
from communication import *
import struct

capsule_instance = Capsule(lambda packetId, dataIn, len: handle_packet(packetId, dataIn[:len], len))

azmFromSlider = 0
elvFromSlider = 0
circle1_x = 300  # Position X for circle 1
circle1_y = 300  # Position Y for circle 1
circle2_x = 500  # Position X for circle 2
circle2_y = 500  # Position Y for circle 2

def handle_packet(packetId, dataIn, lenIn):
    print("Packet ID: " + str(packetId))
    
app = Flask(__name__)

# Initialize the camera
camera = PiCamera()
camera.resolution = (1280, 720)
camera.framerate = 24
rawCapture = PiRGBArray(camera, size=(1280, 720))

# Allow the camera to warm up
time.sleep(0.1)

# Initialize serial communication with Arduino
try: 
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
except:
    ser = serial.Serial('/dev/ttyACM1', 115200, timeout=1)

def gen_frames():
    global circle1_x, circle1_y, circle2_x, circle2_y
    for frame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
        image = frame.array

        # Draw the central circle
        center_x = image.shape[1] // 2
        center_y = image.shape[0] // 2
        cv2.circle(image, (center_x, center_y), 50, (0, 255, 0), 2)

        # Draw the additional circles
        cv2.circle(image, (circle1_x, circle1_y), 50, (255, 0, 0), 2)
        cv2.circle(image, (circle2_x, circle2_y), 50, (0, 0, 255), 2)

        ret, buffer = cv2.imencode('.jpg', image)
        frame = buffer.tobytes()
        
        # Clear the stream for the next frame
        rawCapture.truncate(0)

        # Yield frame to Flask response
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/update_variable', methods=['POST'])
def update_variable():
    global azmFromSlider, elvFromSlider

    data = request.get_json()
    control_id = data.get("id")
    value = float(data.get("value"))
    
    print("Control ID: " + control_id)
    
    if control_id == "azm":
        azmFromSlider = value
        print("Azimuth: " + str(azmFromSlider))
    elif control_id == "elv":
        elvFromSlider = value
        print("Elevation: " + str(elvFromSlider))
        
    sendAbsPosToTeensy(azmFromSlider, elvFromSlider)
    
    return "Variable updated successfully!"

def sendZoom(zoomDir):
    packet_id = 0x13
    # Pack the struct in a byte array

    payload_data = struct.pack('i', zoomDir)
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    ser.write(encoded_packet)

def record_toggle():
    print("Record On called")
    packet_id = 0x14
    
    # Pack the struct in a byte array
    
    payload_data = struct.pack('i', 1)
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    ser.write(encoded_packet)
    # camera.start_recording('video.h264')

@app.route('/')
def index():
    return render_template('oldIndex.html')

@app.route('/zoom_in', methods=['POST'])
def button1():
    sendZoom(-50)
    return '', 204

@app.route('/zoom_out', methods=['POST'])
def button2():
    sendZoom(50)
    return '', 204

@app.route('/record_on', methods=['POST'])
def button3():
    record_toggle()
    return '', 204

@app.route('/record_off', methods=['POST'])
def button4():
    record_toggle()
    return '', 204

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
