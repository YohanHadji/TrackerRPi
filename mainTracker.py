import numpy as np

from communication import *
from detection import * 
from camera import *

camInit(120)
UDPInit("tracker")

firstTimeNoted = False
timeOffset = 0

class LightPoint:
    def __init__(self, name, isVisible, x, y, age):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type
        self.age = int(age)

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(10)]

joystickX   = 0
joystickY   = 0
joystickBtn = False
swUp        = False
swDown      = False
swLeft      = False
swRight     = False

trackingEnabled = False

setCameraSettings(cameraSetting["gain"], cameraSetting["exposureTime"])
setDetectionSettings(cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"])

while True:
    # Get a frame with metadata
    frame, sensorTimeStamp = getFrame()

    if (not firstTimeNoted):
        firstTimeNoted = True
        print("First frame received")
        timeOffset = np.int64(time.time()*1e9) - sensorTimeStamp

    # Detect light points
    all_light_points = detect(frame, sensorTimeStamp)

    sendLightPointListToRaspi(all_light_points, 10)

    #printFps()

    parseIncomingDataFromUDP()
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

    pointToSend = getLockedPoint(all_light_points, joystickBtn, swUp, swDown, swLeft, swRight)
    # print(pointToSend.name, pointToSend.x, pointToSend.y)

    if (not trackingEnabled):
        # print("Tracking disabled")
        pointToSend.isVisible = False
    
    pointToSend.age = np.int32((np.int64(time.time()*1e9)-timeOffset)-sensorTimeStamp)
    print(pointToSend.age)

    sendTargetToTeensy(pointToSend)

    # Exit if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release resources
cv2.destroyAllWindows()
picam2.stop()
