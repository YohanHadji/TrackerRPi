import numpy as np
from capsule import *
from display import *
import socket
import struct
import serial

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sockImage = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ser = None

TEENSY_IP = "192.168.1.100"
TEENSY_PORT = 8888

OTHER_RASPI_IP = "192.168.1.178"
OTHER_RASPI_PORT = 8888

UDP_IP_TRACKER = "localhost"
UDP_IP_DISPLAY = "localhost"
UDP_IP_TRACKER180 = "localhost"
UDP_PORT = 8888

GUSTAVO_IP = "192.168.1.181"
GUSTAVO_PORT = 8888

SELF_IP = "0.0.0.0"

IMAGE_PORT = 9999

joystickX = 0
joystickY = 0
joystickBtn = 0
swUp = False
swDown = False 
swLeft = False 
swRight = False

trackerAzm = 0
trackerElv = 0

colimator1 = 1500
colimator2 = 1500

colimator1 = 1500
colimator2 = 1500

lastFrame = None

def arduinoInit():
    global ser
    # Arduino connected on USB serial, use try, except to try to connect
    try:
        ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
    except:
        print("Arduino not connected")

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
newDataFromTrackerReceived = False

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
    global newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived, newDataFromTrackerReceived
    return newControllerPacketReceived or newPointListPacketReceived or newCameraSettingsPacketReceived or newDataFromTrackerReceived

def newPacketReceivedType():
    global newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived, newDataFromTrackerReceived
    if (newControllerPacketReceived):
        return "controller"
    if (newPointListPacketReceived):
        return "pointList"
    if (newCameraSettingsPacketReceived):
        return "cameraSettings"
    if (newDataFromTrackerReceived):   
        return "dataFromTracker"

def returnLastPacketData(packetType):
    global joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight, LightPointArray, cameraSetting, newControllerPacketReceived, newPointListPacketReceived, newCameraSettingsPacketReceived, newDataFromTrackerReceived, trackerAzm, trackerElv
    if (packetType == "controller"):
        newControllerPacketReceived = False
        return joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight
    elif (packetType == "pointList"):
        newPointListPacketReceived = False
        return LightPointArray
    elif (packetType == "cameraSettings"):
        newCameraSettingsPacketReceived = False
        return cameraSetting
    elif (packetType == "dataFromTracker"):
        newDataFromTrackerReceived = False
        return trackerAzm, trackerElv
    

def handle_packet(packetId, dataIn, lenIn):
    global joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight, LightPointArray, newControllerPacketReceived, newPointListPacketReceived, cameraSetting, newCameraSettingsPacketReceived, newDataFromTrackerReceived, trackerAzm, trackerElv
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

    elif (packetId == 33):
        newDataFromTrackerReceived = True
        trackerAzm, trackerElv = struct.unpack('ff', bytearray(dataIn))
        # print("Received data from tracker: ")
        # print(trackerAzm)
        # print(trackerElv)

capsule_instance = Capsule(lambda packetId, dataIn, len: handle_packet(packetId, dataIn[:len], len))

def UDPInit(name):
    global sock
    if (name == "tracker"):
        sock.bind(('192.168.1.220', UDP_PORT))
    elif (name == "display"):
        sock.bind((UDP_IP_DISPLAY, UDP_PORT))
    elif (name == "tracker180"):
        sock.bind((UDP_IP_TRACKER180, UDP_PORT))
        sockImage.bind((UDP_IP_TRACKER180, IMAGE_PORT))
        sockImage.connect(('localhost', IMAGE_PORT))
    sock.setblocking(0)

def sendFrameToSelf(frame):
    global sockImage 
    print("Sent frame to self")
    sockImage.sendall(frame.tobytes())

def sendAbsPosToTeensy(azm, elv):
    global sock
    # Send the target point to the teensy, the structure should be copied in a byte array then encoded then sent
    packet_id = 0x03
    # Pack the struct in a byte array
    print(f"Sending azm: {azm}, elv: {elv}")

    payload_data = struct.pack('ff', float(azm), float(elv))
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    # Send the encoded packet
    sock.sendto(encoded_packet, (TEENSY_IP, TEENSY_PORT))
    
def sendTargetToTeensy(pointToSendIn, cameraID, Kp, maxSpeed):
    global sock
    # Send the target point to the teensy, the structure should be copied in a byte array then encoded then sent
    packet_id = 0x01
    # Pack the struct in a byte array

    pointToSend = LightPoint(pointToSendIn.name, pointToSendIn.isVisible, pointToSendIn.x, pointToSendIn.y, pointToSendIn.age)

    pointToSendName = str(pointToSend.name)
    payload_data = struct.pack('4siiiiiff', pointToSendName.encode('utf-8'), pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age, cameraID, Kp, maxSpeed)
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
    # Send the encoded packet
    sock.sendto(encoded_packet, (TEENSY_IP, TEENSY_PORT))

def getPositionFromColimator():
    global ser, colimator1, colimator2
    
    newPacket = False
    
    while ser.in_waiting > 0:
        line = ser.readline().decode('utf-8').rstrip()
        # print(line)
        try:
            colimator1, colimator2 = line.split(',')
            newPacket = True
        except: 
            print("Error parsing colimator data")
        # print("Servo 1: " + servo1Position + " Servo 2: " + servo2Position)
        
    return colimator1, colimator2, newPacket
        
# Send target to arduino via USB serial
def sendTargetToColimator(pointToSendIn):
    global ser
    # Send the target point to the arduino, the structure should be copied in a byte array then encoded then sent
    packet_id = 0x01
    # Pack the struct in a byte array
    
    
    # s1 = 1403 + (-0.01779 * pointToSendIn.x) + (0.6801 * pointToSendIn.y)
    # s2 = 1561 + (-0.8265 * pointToSendIn.x) + (-0.03777 * pointToSendIn.y)
    
   # s1 = 1350.039802650483 + (-0.91674131 * pointToSendIn.x) + (-0.02420612 * pointToSendIn.y)
   #  s2 = 1468.0770404111263 + (0.01674877 * pointToSendIn.x) + (0.89634829 * pointToSendIn.y)
    # calibracion 2024-12-20
    #s1 = 1333.141207480285 + (-0.91674131 * pointToSendIn.x) + (-0.02420612 * pointToSendIn.y)
    #s2 = 1501.435197615967 + (0.00769191 * pointToSendIn.x) + (-0.89521636 * pointToSendIn.y)
    # calibarcion 2024-12-28 
    s1 = 1343.7939625310407 + (-0.01367876 * pointToSendIn.x) + (-0.90776423 * pointToSendIn.y)
    s2 = 1503.554479850552 + (-0.91229297 * pointToSendIn.x) + (-0.01122311 * pointToSendIn.y)
    # x2 = round(x2, 3)
    # y2 = round(y2, 3)
    
    print(f"Sending target to colimator: {s1}, {s2}")

    pointToSend = LightPoint(pointToSendIn.name, pointToSendIn.isVisible, s1, s2, pointToSendIn.age)

    pointToSendName = str(pointToSend.name)
    # payload_data = struct.pack('4siiiiiff', pointToSendName.encode('utf-8'), pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age, 0,0,0)
    payload_data = struct.pack('4siiiiiff', pointToSendName.encode('utf-8'), pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age, 0,0,0)
    packet_length = len(payload_data)
    encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
    # Print the encoded packet
    #print(f"Encoded Packet: {encoded_packet}")
    # Convert encoded_packet to a bytearray
    encoded_packet = bytearray(encoded_packet)
        
    if (ser != None):
        try:
            # Send the encoded packet
            ser.write(encoded_packet)
        except Exception as e:
            print(f"Error occurred while sending data: {e}")
    else:
        try:
            ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
        except:
            print("Teensy not found")
        
        

def sendAbsFocToArduino(focus):
    global ser
    
    packet_id = 0x15
    print(f"Focus: {focus}")

    try:
        payload_data = struct.pack('L', int(focus))
        packet_length = len(payload_data)
        encoded_packet = capsule_instance.encode(packet_id, payload_data, packet_length)
        
        encoded_packet = bytearray(encoded_packet)
        
        ser.write(encoded_packet)
        print("Write success")
    except struct.error as e:
        print(f"Struct error: {e}")
        raise
    except serial.SerialException as e:
        print(f"Serial error: {e}")
        raise
    except Exception as e:
        print(f"General error: {e}")
        raise

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
    #encoded_packet = bytes([0xFF,0xFA,0x00])
    #print(encoded_packet)
    #print(OTHER_RASPI_IP)
    #print(OTHER_RASPI_PORT)
    sock.sendto(encoded_packet, ('192.168.1.178', 8888))

def parseIncomingDataFromUDP():
    global sock
    try:
        data, addr = sock.recvfrom(1024)  # Adjust the buffer size as needed
        print(f"Received {len(data)} bytes from {addr}")

        # Decode the data with capsule
        for byte in data:
            capsule_instance.decode(byte)

    except socket.error as e:
        pass

def parseImageFromUDP():
    global sockImage, lastFrame
    try:
        lastFrame, addr = sockImage.recvfrom(10e6)  # Adjust the buffer size as needed
        # print(f"Received {len(data)} bytes from {addr}")
        return True

    except socket.error as e:
        pass
        return False

def returnLastFrame():
    global lastFrame
    return lastFrame