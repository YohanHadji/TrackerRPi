import numpy as np
from capsule import *
from display import *
import socket
import struct

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

TEENSY_IP = "192.168.1.100"
TEENSY_PORT = 8888

OTHER_RASPI_IP = "192.168.1.178"
OTHER_RASPI_PORT = 8888

UDP_IP_TRACKER = "192.168.1.114"
UDP_IP_DISPLAY = "192.168.1.178"
UDP_PORT = 8888

GUSTAVO_IP = "192.168.1.181"
GUSTAVO_PORT = 8888

joystickX = 0
joystickY = 0
joystickBtn = 0
swUp = False
swDown = False 
swLeft = False 
swRight = False

# Variables to store slider and dropdown values
cameraSetting = {
    "idRadius": 25,
    "lockRadius": 100,
    "lightLifetime": 200,
    "lightThreshold": 200,
    "switchFrame": 0,  # Assuming it's initially set to 0
    "gain": 1.0,
    "exposureTime": 100,
    "trackingEnabled": 0
}

newControllerPacketReceived = False
newPointListPacketReceived = False
newCameraSettingsPacketReceived = False

class LightPoint:
    def __init__(self, name, isVisible, x, y, age):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type
        self.age = int(age)

# Create an array of structures without specifying values        
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(10)]

# Example of using the Capsule class
class Foo:
    pass

def newPacketReceived():
    global newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived
    return newControllerPacketReceived or newPointListPacketReceived or newCameraSettingsPacketReceived

def newPacketReceivedType():
    global newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived
    if (newControllerPacketReceived):
        return "controller"
    if (newPointListPacketReceived):
        return "pointList"
    if (newCameraSettingsPacketReceived):
        return "cameraSettings"

def returnLastPacketData(packetType):
    global joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight, LightPointArray, cameraSetting, newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived
    if (packetType == "controller"):
        newControllerPacketReceived = False
        return joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight
    elif (packetType == "pointList"):
        newPointListPacketReceived = False
        return LightPointArray
    elif (packetType == "cameraSettings"):
        newCameraSettingsPacketReceived = False
        return cameraSetting

def handle_packet(packetId, dataIn, lenIn):
    global joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight, LightPointArray, newControllerPacketReceived, newPointListPacketReceived, cameraSetting, newCameraSettingsPacketReceived
    #print(f"Received packet {packetId}: {dataIn[:lenIn]}")
    #print(len(bytearray(dataIn)))
    # Joystick packet received
    if (packetId == 99):
        newControllerPacketReceived = True
         # Assuming the first 4 bytes are preamble data, and the rest is 2 floats and 5 bools
        joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight = struct.unpack('ffbbbbb', bytearray(dataIn)) 
    # List of tracked points packet
    elif (packetId == 0x02):
        newPointListPacketReceived = True
        cutSize = struct.calcsize('4siiii')
        # We need to cut the received data in chunks of 16 bytes and then apply the struct.unpack on this
        for i in range(0, len(dataIn), cutSize):
            point = struct.unpack('4siiii', bytearray(dataIn[i:i+cutSize]))
            LightPointArray[i//cutSize] = LightPoint(point[0].decode('utf-8'), point[1], point[2], point[3], point[4])

        # print("Received list of ")
        # print(len(LightPointArray))
        # for i, point in enumerate(LightPointArray):
        #     print("Point %d: (%s, %d, %d)" % (i + 1, point.name, point.x, point.y))
    elif (packetId == 0x10):
        newCameraSettingsPacketReceived = True
        cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"], cameraSetting["gain"], cameraSetting["exposureTime"], cameraSetting["trackingEnabled"] = struct.unpack('iiiiiii', bytearray(dataIn))

capsule_instance = Capsule(lambda packetId, dataIn, len: handle_packet(packetId, dataIn[:len], len))

def UDPInit(name):
    global sock
    if (name == "tracker"):
        sock.bind((UDP_IP_TRACKER, UDP_PORT))
    elif (name == "display"):
        sock.bind((UDP_IP_DISPLAY, UDP_PORT))
    sock.setblocking(0)

def sendTargetToTeensy(pointToSendIn):
    global sock
    # Send the target point to the teensy, the structure should be copied in a byte array then encoded then sent
    packet_id = 0x01
    # Pack the struct in a byte array

    pointToSend = LightPoint(pointToSendIn.name, pointToSendIn.isVisible, pointToSendIn.x, pointToSendIn.y, pointToSendIn.age)

    pointToSendName = str(pointToSend.name)
    payload_data = struct.pack('4siiii', pointToSendName.encode('utf-8'), pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age)
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    # Send the encoded packet
    sock.sendto(encoded_packet, (TEENSY_IP, TEENSY_PORT))

def sendLightPointListToRaspi(all_light_points, n):
    global sock

    # Light point structure
    # Create an array of structures without specifying values
    LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(n)]

    # Print only the first 3 light points with their name, position x and y only.
    for i, (name, _, x, y, age, _, speed_x, speed_y, acceleration_x, acceleration_y) in enumerate(all_light_points[:n]):
        # print("Point %d: (%s, %d, %d, %d, %d, %d, %d)" % (i + 1, name, x, y, speed_x, speed_y, acceleration_x, acceleration_y))
        LightPointArray[i] = LightPoint(name, 1, x, y, age)

    arrayToSend = bytearray()
    byteToSend = bytearray()
    packet_id = 0x02
    
    # Fill light point array
    for i, point in enumerate(LightPointArray):
        pointToSend = LightPoint(point.name, point.isVisible, point.x, point.y, point.age)
        pointToSendName = str(point.name)
        byteToSend = struct.pack('4siiii', pointToSendName.encode('utf-8'), pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age)
        # Concatenate the byte to the array
        sizeToSend = struct.calcsize('4siiii')
        arrayToSend[i*sizeToSend:(i+1)+sizeToSend] = byteToSend

    payload_data = arrayToSend
    packet_length = len(arrayToSend)
    encoded_packet = capsule_instance.encode(0x02, payload_data, packet_length)
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    sock.sendto(encoded_packet, (OTHER_RASPI_IP, OTHER_RASPI_PORT))

def parseIncomingDataFromUDP():
    global sock
    try:
        data, addr = sock.recvfrom(1024)  # Adjust the buffer size as needed
        # print(f"Received {len(data)} bytes from {addr}")

        # Decode the data with capsule
        for byte in data:
            capsule_instance.decode(byte)

    except socket.error as e:
        pass
