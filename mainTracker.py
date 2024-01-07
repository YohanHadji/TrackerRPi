import numpy as np

from communication import *
from detection import * 
from camera import *

camInit(120)
UDPInit("tracker")

class LightPoint:
    def __init__(self, name, isVisible, x, y):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0) for _ in range(10)]

joystickX   = 0
joystickY   = 0
joystickBtn = False
swUp        = False
swDown      = False
swLeft      = False
swRight     = False

setCameraSettings(cameraSetting["gain"], cameraSetting["exposureTime"])
setDetectionSettings(cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"])

while True:
    # Get a frame with metadata
    frame, sensorTimeStamp = getFrame()

    # Detect light points
    all_light_points = detect(frame, sensorTimeStamp)

    sendLightPointListToRaspi(all_light_points, 10)

    printFps()

    parseIncomingDataFromUDP()
    if (newPacketReceived()):
        packetType = newPacketReceivedType()
        if (packetType == "controller"):
            joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight = returnLastPacketData(packetType)
            getLockedPoint(joystickBtn, swUp, swDown, swLeft, swRight)
        elif (packetType == "pointList"):
            LightPointArray = returnLastPacketData(packetType)
        elif (packetType == "cameraSettings"):
            cameraSetting = returnLastPacketData(packetType)
            setCameraSettings(cameraSetting["gain"], cameraSetting["exposureTime"])
            print("Applied camera settings")
            setDetectionSettings(cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"])

    pointToSend = getLockedPoint(all_light_points, joystickBtn, swUp, swDown, swLeft, swRight)
    # print(pointToSend.name, pointToSend.x, pointToSend.y)

    if (not cameraSetting["trackingEnabled"]):
        print("Tracking disabled")
        print (cameraSetting["trackingEnabled"])
        pointToSend.isVisible = False
    else:
        print("Tracking enabled")
        print (cameraSetting["trackingEnabled"])


    sendTargetToTeensy(pointToSend)

    # Exit if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release resources
cv2.destroyAllWindows()
picam2.stop()
