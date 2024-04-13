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
camInit(60, True, True)

img_width = 800
img_height = 606

# azimuth = 270
# elevation = 90

xPos = 0
yPos = 0

joystickX   = 0
joystickY   = 0
joystickBtn = False
swUp        = False
swDown      = False
swLeft      = False
swRight     = False


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
all_light_points = []

startTime = time.time()
firstTimeNoted = False
timeOffset = 0
timeOffsetAverage = 0
trackingEnabled = False

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

def generate_frames():
    global LightPointArray, input_values, resolution, picam2, xPos, yPos, img_width, img_height, all_light_points

    frame = None

    while True:
        frame, sensorTimeStamp = server.wait_for_frame(frame)
        # frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        # Vertical flip 
        # frame = cv2.flip(frame, 0)
        # Horizontal flip
        # frame = cv2.flip(frame, 1)

        LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(10)]

        # Print only the first 3 light points with their name, position x and y only.
        for i, (name, _, x, y, age, _, speed_x, speed_y, acceleration_x, acceleration_y) in enumerate(all_light_points[:10]):
            # print("Point %d: (%s, %d, %d, %d, %d, %d, %d)" % (i + 1, name, x, y, speed_x, speed_y, acceleration_x, acceleration_y))
            LightPointArray[i] = LightPoint(name, 1, x, y, age)


        # Encode the frame
        if (input_values["switchFrame"] == 0):
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Create a second frame with only the blue channel using cv2.cvtColor
            # Split the frame into its individual channels
            # blue_channel, green_channel, red_channel = cv2.split(frame)

            # # Set green and red channels to zero
            # green_channel[:] = 0
            # red_channel[:] = 0

            # # Merge the channels back into a BGR frame
            # blue_frame = cv2.merge((blue_channel, green_channel, red_channel))


            # METHOD 1
            _dummy, b_frame = cv2.threshold(gray_frame,np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)

            # METHOD 2
            # # Apply morphological dilation
            # kernel = np.ones((3, 3), np.uint8)
            # dilated = cv2.dilate(gray_frame, kernel)

            # # Compute the difference between the original and dilated image
            # diff = cv2.absdiff(dilated, gray_frame)

            # # Optionally, you can further threshold the difference image
            # _, b_frame = cv2.threshold(diff, np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)

            # METHOD 3 
            # Compute the gradient magnitude using Sobel operators
            # gradient_x = cv2.Sobel(gray_frame, cv2.CV_64F, 1, 0, ksize=3)
            # gradient_y = cv2.Sobel(gray_frame, cv2.CV_64F, 0, 1, ksize=3)
            # gradient_magnitude = np.sqrt(gradient_x**2 + gradient_y**2)

            # # Normalize gradient magnitude to [0, 255]
            # gradient_magnitude_normalized = cv2.normalize(gradient_magnitude, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

            # # Threshold the gradient magnitude image
            # _, thresh = cv2.threshold(gradient_magnitude_normalized, np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)

            # # Perform non-maximum suppression
            # b_frame = cv2.dilate(thresh, None)

            cv2.circle(b_frame, (400,303), input_values["lockRadius"], 255, 2)
            for point in LightPointArray:
                cv2.circle(b_frame, (point.x, point.y), 5, 255, -1)
                cv2.putText(b_frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2, cv2.LINE_AA)

            _, buffer = cv2.imencode('.jpg', b_frame,  [int(cv2.IMWRITE_JPEG_QUALITY), 100])
            b_frame = buffer.tobytes()
            yield (b'--frame\r\n'
               b'Content-Type: image/jpg\r\n\r\n' + b_frame + b'\r\n')
        else:
            cv2.circle(frame, (400,303), input_values["lockRadius"], (0, 0, 255), 2)
            for point in LightPointArray:
               cv2.circle(frame, (point.x, point.y), 5, (0, 0, 255), -1)
               cv2.putText(frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            _, buffer = cv2.imencode('.jpg', frame,  [int(cv2.IMWRITE_JPEG_QUALITY), 100])
            b_frame = buffer.tobytes() 
            yield (b'--frame\r\n'
               b'Content-Type: image/jpg\r\n\r\n' + b_frame + b'\r\n')
            
        # # Encode the frame
            
        # gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # _dummy, b_frame = cv2.threshold(gray_frame,np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)

        # if (input_values["switchFrame"] == 0):
        #     cv2.circle(b_frame, (400,303), input_values["lockRadius"], 255, 2)
        #     for point in LightPointArray:
        #         cv2.circle(b_frame, (point.x, point.y), 5, 255, -1)
        #         cv2.putText(b_frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2, cv2.LINE_AA)
        #     _, buffer = cv2.imencode('.jpg', b_frame)
        #     b_frame = buffer.tobytes()
        #     yield (b'--frame\r\n'
        #        b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')
        # else:
        #     cv2.circle(frame, (400,303), input_values["lockRadius"], (0, 0, 255), 2)
        #     for point in LightPointArray:
        #         cv2.circle(frame, (point.x, point.y), 5, (0, 0, 255), -1)
        #         cv2.putText(frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
        #     _, buffer = cv2.imencode('.jpg', frame)
        #     b_frame = buffer.tobytes() 
        #     yield (b'--frame\r\n'
        #        b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')

def tracking_loop():
    global LightPointArray, all_light_points, input_values, resolution, picam2, xPos, yPos, img_width, img_height, startTime, firstTimeNoted, timeOffset, timeOffsetAverage, trackingEnabled, joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight

    frame = None
    while True:

        if (not firstTimeNoted):
            frame,sensorTimeStamp = server.wait_for_frame(frame)
            firstTimeNoted = True
            # print("First frame received")

            numberOfFrames = 0

            while (numberOfFrames < 100):
                frame, sensorTimeStamp = getFrame()
                print(np.int64((time.time()-startTime)*1e9), sensorTimeStamp)
                timeOffset += (np.int64((time.time()-startTime)*1e9) - sensorTimeStamp)
                numberOfFrames += 1

            timeOffset /= numberOfFrames
            timeOffsetAverage = np.int64(timeOffset)
            # print("Time offset calculated")
            # print(timeOffsetAverage)

        else:
            frame,sensorTimeStamp = server.wait_for_frame(frame)
            # frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            # frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            # Vertical flip 
            # frame = cv2.flip(frame, 0)
            # Horizontal flip
            # frame = cv2.flip(frame, 1)

            # Rotate frame by 90° to the left

            all_light_points = detect(frame, sensorTimeStamp)

            pointToSend = getLockedPoint(all_light_points, joystickBtn, swUp, swDown, swLeft, swRight)
            # print(pointToSend.name, pointToSend.x, pointToSend.y)

            if (not trackingEnabled):
                # print("Tracking disabled")
                pointToSend.isVisible = False
            #else:
                # print("Tracking enabled")
            
            # pointToSend.age = np.int32((np.int64((time.time()-startTime)*1e9)-timeOffsetAverage)-sensorTimeStamp)
            # print(sensorTimeStamp, timeOffsetAverage)
            pointToSend.age = np.int32((((time.time()-startTime)*1e9)-(sensorTimeStamp+timeOffsetAverage))/1e6)
            # print(pointToSend.age)
            # oldX = pointToSend.x
            # pointToSend.x = pointToSend.x+15
            # pointToSend.y = pointToSend.y-13

            print(pointToSend.name, pointToSend.x, pointToSend.y, pointToSend.age, pointToSend.isVisible)

            sendTargetToTeensy(pointToSend, 99)

            # printFps()

            if (newPacketReceived()):
                packetType = newPacketReceivedType()
                if (packetType == "controller"):
                    joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight = returnLastPacketData(packetType)
                    # print(joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight)
                    getLockedPoint(all_light_points, joystickBtn, swUp, swDown, swLeft, swRight)
                elif (packetType == "pointList"):
                    LightPointArray = returnLastPacketData(packetType)
                elif (packetType == "cameraSettings"):
                    cameraSetting = returnLastPacketData(packetType)
                    setCameraSettings(cameraSetting["gain"], cameraSetting["exposureTime"])
                    print("Applied camera settings")
                    setDetectionSettings(cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"])
                    print(cameraSetting["trackingEnabled"])
                    if (not cameraSetting["trackingEnabled"]):
                        trackingEnabled = False
                    else:
                        trackingEnabled = True
                elif (packetType == "dataFromTracker"):
                    # Print the position of tracker and pointToSendX, pointToSendY
                    trackerAzm, trackerElv = returnLastPacketData(packetType)
                    print(trackerAzm, trackerElv, pointToSend.x, pointToSend.y)


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/update_variable', methods=['POST'])
def update_variable():
    global input_values, trackingEnabled

    data = request.get_json()
    control_id = data.get("id")
    value = data.get("value")

    if control_id in input_values:
        input_values[control_id] = int(value)
        print(f"Slider {control_id} updated to {value}")
        # sendSettingToTracker()
        setCameraSettings(input_values["gain"], input_values["exposureTime"])
        setDetectionSettings(input_values["idRadius"], input_values["lockRadius"], input_values["lightLifetime"], input_values["lightThreshold"])
        if (not input_values["trackingEnabled"]):
            trackingEnabled = False
        else:
            trackingEnabled = True
    else:
        print(f"Unknown control ID: {control_id}")
    
    # picam2.set_controls({"AnalogueGain": np.int32(input_values["gain"]), "ExposureTime": np.int32(input_values["exposureTime"])})

    return "Variable updated successfully!"

if __name__ == '__main__':
    try:
        thread1 = Thread(target=tracking_loop)
        server = FrameServer(picam2,'new')
        server.start()
        thread1.start()

        udp_thread = threading.Thread(target=udp_listener)
        udp_thread.start()
        app.run(host='0.0.0.0', port=5000, threaded=True)

    finally:
        server.stop()
        picam2.stop()