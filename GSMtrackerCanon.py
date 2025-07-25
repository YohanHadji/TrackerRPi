from flask import Flask, render_template, Response, request,jsonify, stream_with_context
import serial
import numpy as np
from communication import *
from playerOne import *
#from canon import *
from canonAutoDetec import *
# from camera import *
import threading 
import cv2
import time
from detection import *
import serial.tools.list_ports
import logging

from gpiozero import LED   # activacion camara canon cada 28 minutos 
import threading


calibrationMode = False

camRes = (1920, 1080)

joystickX   = 0
joystickY   = 0
joystickBtn = False
swUp        = False
swDown      = False
swLeft      = False
swRight     = False

offsetS1 = 0
offsetS2 = 0

# Light point structure
class LightPoint:
    def __init__(self, name, isVisible, x, y, age):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type
        self.age = int(age)

def handle_packet_arduino(packetId, dataIn, lenIn):
    print("Packet ID: " + str(packetId))

capsule_instance_arduino = Capsule(lambda packetId, dataIn, len: handle_packet_arduino(packetId, dataIn[:len], len))

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age = 0) for _ in range(10)]
all_light_points = []

startTime = time.time()
firstTimeNoted = False
timeOffset = 0
timeOffsetAverage = 0
trackingEnabled = False

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)  # Establece el nivel de logging a DEBUG para ver más detalles
# Inicializar GPIO18 como salida
gpio_led = LED(18)

# Función que mantiene el pin encendido y lo reinicia cada 28 minutos
def gpio_maintain_and_restart():
    gpio_led.on()  # Encender inicialmente
    print("GPIO18 encendido permanentemente")
    while True:
        time.sleep(28 * 60)  # Esperar 28 minutos
        print("Reiniciando GPIO18...")
        gpio_led.off()
        time.sleep(1)  # Apagado durante 1 segundo
        gpio_led.on()
        print("GPIO18 reactivado")

# Función para encontrar el Arduino basado en su VID y PID.
def find_arduino(vid_pid="2A03:0043"):
    vid_pid = vid_pid.upper()  # Asegura comparación en mayúsculas
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        print(f"Port: {port.device}, HWID: {port.hwid}")  # Imprime detalles del puerto
        if vid_pid in port.hwid.upper():
            return port.device
    return None

# Función para crear la conexión serial.
def create_serial_connection():
    arduino_port = find_arduino()
    if arduino_port:
        try:
            return serial.Serial(arduino_port, 115200, timeout=1)
        except serial.SerialException as e:
            print(f"Error opening the port: {e}")
    else:
        print("Arduino no encontrado.")
    return None

# Intenta establecer la conexión serial al iniciar la aplicación.
# arduino = create_serial_connection()

arduinoInit()

@app.route('/send_command', methods=['POST'])
def send_command():
    global arduino
    return "", 200
    # if not arduino:
    #     print("Reintentando conexión con Arduino...")
    #     arduino = create_serial_connection()  # Reintentar establecer conexión si no existe.
    #     if not arduino:
    #         print("Fallo al reconectar con Arduino.")
    #         return jsonify({"error": "Arduino no está conectado"}), 500

    # data = request.get_json()
    # command = data.get('command', '')
    # print(f"Datos recibidos: {data}")  # Imprimir los datos recibidos
    # print(f"Comando recibido: {command}")  # Imprimir el comando específico

    # try:
    #     response = send_command_to_arduino(command)
    #     return jsonify({"message": "Comando enviado al Arduino", "response": response}), 200
    # except Exception as e:
    #     print(f"Error al enviar comando: {e}")
    #     return jsonify({"error": str(e)}), 500

def send_command_to_arduino(command):
    global arduino
    # """Envía un comando al Arduino y espera una respuesta."""
    # try:
    #     arduino.write((command + '\n').encode())
    #     response = arduino.readline().decode().strip()  # Espera una respuesta del Arduino
    #     print("Respuesta de Arduino:", response)
    #     return response
    # except serial.SerialException as e:
    #     raise Exception(f"Error de comunicación serial: {e}")
    # except Exception as e:
    #     raise Exception(f"Error general en la comunicación: {e}")

# camInit(30)
playerOneCamInit()

# Variables to store slider and dropdown values
input_values = {
    "idRadius": 25,
    "lockRadius": 400,
    "lightLifetime": 200,
    "lightThreshold": 200,
    "switchFrame": 0,  # Assuming it's initially set to 0
    "trackingEnabled": 0
}

# picam2.set_controls({"AnalogueGain": np.int32(input_values["gain"]), "ExposureTime": np.int32(input_values["exposureTime"])})

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

def generate_frames():
    global LightPointArray, input_values, camRes

    while True:
        # print("Generating frames")
        # Get a frame with metadata
        frame,sensorTimestamp = serverPlayerOne.wait_for_frame()
           
        top_left = (0, 0)   #375 ,150 
        bottom_right = (frame.shape[1], frame.shape[0]) # 1550,925 
        
        # all_light_points = detect(frame, sensorTimestamp)
        # # print(all_light_points)
        
        LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(30)]

        # Print only the first 3 light points with their name, position x and y only.
        for i, (name, _, x, y, age, _, speed_x, speed_y, acceleration_x, acceleration_y) in enumerate(all_light_points[:30]):
            # print("Point %d: (%s, %d, %d, %d, %d, %d, %d)" % (i + 1, name, x, y, speed_x, speed_y, acceleration_x, acceleration_y))
            LightPointArray[i] = LightPoint(name, 1, x, y, age)


        gray_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        _dummy, b_frame = cv2.threshold(gray_frame,np.int32(input_values["lightThreshold"]), 255, cv2.THRESH_BINARY)

        
        # Encode the frame
        if (input_values["switchFrame"] == 0):
            cv2.circle(b_frame, (np.int16(camRes[0]/2),np.int16(camRes[1]/2)), input_values["lockRadius"], 255, 2)
            for point in LightPointArray:
                cv2.circle(b_frame, (point.x, point.y), 5, 255, -1)
                cv2.rectangle(b_frame, top_left, bottom_right, 255, 2)
                cv2.putText(b_frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2, cv2.LINE_AA)
            _, buffer = cv2.imencode('.jpg', b_frame)
            b_frame = buffer.tobytes()
            yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')
        else:
            cv2.circle(frame, (np.int16(camRes[0]/2),np.int16(camRes[1]/2)), input_values["lockRadius"], (0, 0, 255), 2)
            for point in LightPointArray:
                cv2.circle(frame, (point.x, point.y), 5, (0, 0, 255), -1)
                cv2.rectangle(frame, top_left, bottom_right, (0, 0, 255), 2)
                cv2.putText(frame, point.name, (point.x, point.y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            _, buffer = cv2.imencode('.jpg', frame)
            b_frame = buffer.tobytes() 
            yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + b_frame + b'\r\n')


def tracking_loop():
    global LightPointArray, all_light_points, input_value, xPos, yPos, img_width, img_height, startTime, firstTimeNoted, timeOffset, timeOffsetAverage, trackingEnabled, joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight, offsetS1, offsetS2, calibrationMode

    frame = None
    
    while True:

        if (not firstTimeNoted):
            frame,sensorTimeStamp = serverPlayerOne.wait_for_frame(frame)
            firstTimeNoted = True
            print("First frame received")

            numberOfFrames = 0

            while (numberOfFrames < 100):
                frame, sensorTimeStamp = serverPlayerOne.wait_for_frame(frame)
                print(np.int64((time.time()-startTime)*1e9), sensorTimeStamp)
                timeOffset += (np.int64((time.time()-startTime)*1e9) - sensorTimeStamp)
                numberOfFrames += 1

            timeOffset /= numberOfFrames
            timeOffsetAverage = np.int64(timeOffset)
            print("Time offset calculated")
            print(timeOffsetAverage)

        else:            
            frame,sensorTimeStamp = serverPlayerOne.wait_for_frame(frame)
                        
            # Define the rectangle coordinates
            top_left = (375, 150)
            bottom_right = (1550, 925)

            # Create a mask with the same dimensions as the frame, initially all black
            mask = np.zeros_like(frame)

            # Draw a filled white rectangle on the mask
            cv2.rectangle(mask, top_left, bottom_right, (255, 255, 255), -1)

            # Apply the mask to the original image using bitwise operations
            result = cv2.bitwise_and(frame, mask)  
            
            frame = result   
                                          
            all_light_points = detect(frame, sensorTimeStamp)
            # print(all_light_points)
                        
            # If all light points is not null, then continue
            if (all_light_points is not None):
                pointToSend = getLockedPoint(all_light_points, camRes, joystickBtn, swUp, swDown, swLeft, swRight)
                # print(pointToSend.name, pointToSend.x, pointToSend.y)

                if (not getTrackingEnabled()):
                    # print("Tracking disabled")
                    pointToSend.isVisible = False
                # else:
                    # print("Tracking enabled")
                
                if (calibrationMode) :
                    col1, col2, newPacket = getPositionFromColimator()
                    if (newPacket):
                        print(col1,col2,pointToSend.x,pointToSend.y)
                else:
                    # Parse text coming from the teensy via serial
                    pointToSend.age = np.int32((((time.time()-startTime)*1e9)-(sensorTimeStamp+timeOffsetAverage))/1e6)
                    
                    # print(pointToSend.name, pointToSend.x, pointToSend.y, pointToSend.age, pointToSend.isVisible)
                    
                    pointToSendColimator = LightPoint(pointToSend.name, pointToSend.isVisible, pointToSend.x, pointToSend.y, pointToSend.age)
                    
                    pointToSendColimator.x = pointToSendColimator.x+offsetS1
                    pointToSendColimator.y = pointToSendColimator.y+offsetS2
                    
                    # print(offsetS1,offsetS2)                
                    sendTargetToColimator(pointToSendColimator) 
                    # if (newPacket):
                    #     print(col1, col2, pointToSend.x, pointToSend.y)
                    
                    offsetX = 0
                    offsetY = 0
                    
                    # Draw a circle with offsetX and Y following a sin and cos of time with a frequency of 0.05Hz and amplitude of 200 pixels
                    # offsetX = np.int32(250*np.cos(2*np.pi*0.03*(time.time()-startTime)))
                    # offsetY = np.int32(250*np.sin(2*np.pi*0.03*(time.time()-startTime)))
                    
                    pointToSend.y = -pointToSend.y
                    
                    pointToSend.x = pointToSend.x+offsetX
                    pointToSend.y = pointToSend.y+offsetY
                                
                    # sendTargetToTeensy(pointToSend, 33, 0.05, 2)

                if (newPacketReceived()):
                    packetType = newPacketReceivedType()
                    if (packetType == "controller"):
                        joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight = returnLastPacketData(packetType)
                        # print(joystickX, joystickY, joystickBtn, swUp, swDown, swLeft, swRight)
                        getLockedPoint(all_light_points, camRes, joystickBtn, swUp, swDown, swLeft, swRight)
                    elif (packetType == "pointList"):
                        LightPointArray = returnLastPacketData(packetType)
                    elif (packetType == "cameraSettings"):
                        cameraSetting = returnLastPacketData(packetType)
                        # setCameraSettings(cameraSetting["gain"], cameraSetting["exposureTime"])
                        print("Applied camera settings")
                        # setDetectionSettings(cameraSetting["idRadius"], cameraSetting["lockRadius"], cameraSetting["lightLifetime"], cameraSetting["lightThreshold"])
                        # print(cameraSetting["trackingEnabled"])
                        # if (not cameraSetting["trackingEnabled"]):
                        #     trackingEnabled = False
                        # else:
                        #     trackingEnabled = True
                    # elif (packetType == "dataFromTracker"):
                    #     # Print the position of tracker and pointToSendX, pointToSendY
                    #     trackerAzm, trackerElv = returnLastPacketData(packetType)
                    #     print(trackerAzm, trackerElv, pointToSend.x, pointToSend.y)

@app.route('/send_udp', methods=['POST'])
def send_udp():
    data = request.get_json()
    azm = data.get('azm')
    elv = data.get('elv')
    sendAbsPosToTeensy(azm, elv)
    
@app.route('/send_offset', methods=['POST'])
def send_offset():
    global offsetS1, offsetS2
    
    data = request.get_json()
    offsetS1 = int(data.get('s1'))
    offsetS2 = int(data.get('s2'))
    
    print("Offset received")    
    print(offsetS1, offsetS2)
    
    return jsonify({"message": "Offset command sent successfully"}), 200
    
@app.route('/send_focus', methods=['POST'])
def send_focus():
    data = request.get_json()
    foc = data.get('foc')

    if foc is None:
        return jsonify({"error": "No focus value provided"}), 400

    try:
        foc = int(foc)
        sendAbsFocToArduino(foc)
        return jsonify({"message": "Focus command sent successfully"}), 200
    except ValueError:
        return jsonify({"error": "Invalid focus value"}), 400
    except Exception as e:
        app.logger.error(f"Error in send_focus: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/video_feed')
def video_feed():
    print("Video feed requested")
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('colimador_index.html')

@app.route('/update_variable', methods=['POST'])
def update_variable():
    global input_values

    data = request.get_json()
    control_id = data.get("id")
    value = data.get("value")

    if control_id in input_values:
        input_values[control_id] = int(value)
        print(f"Slider {control_id} updated to {value}")
        # sendSettingToTracker()
        # setCameraSettings(input_values["gain"], input_values["exposureTime"])
        # setPlayerOneCameraSettings(input_values["gain"], input_values["exposureTime"])
        setDetectionSettings(input_values["idRadius"], input_values["lockRadius"], input_values["lightLifetime"], input_values["lightThreshold"], input_values["trackingEnabled"])
    else:
        print(f"Unknown control ID: {control_id}")
    
    return "Variable updated successfully!"
def get_camlink_device():
    import subprocess
    try:
        output = subprocess.check_output(['v4l2-ctl', '--list-devices'], text=True)
        lines = output.splitlines()
        for i in range(len(lines)):
            if "Cam Link 4K" in lines[i]:
                devs = []
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith('\t/dev/video'):
                        devs.append(lines[j].strip())
                    else:
                        break
                if devs:
                    print(f"Cam Link detectado en: {devs}")
                    return devs[0]  # Usa el primero detectado
    except Exception as e:
        print(f"Error buscando Cam Link: {e}")
    return None


if __name__ == '__main__':
    try:
        # Buscar el dispositivo de cámara
        device = get_camlink_device()
        if not device:
            print("No se encontró Cam Link. Probando /dev/video1 como fallback.")
            device = '/dev/video1'

        serverPlayerOne = FrameServerCanon(device)
        serverPlayerOne.start()

        thread1 = threading.Thread(target=tracking_loop)
        thread1.start()

        handler = logging.FileHandler('app.log')  # Guarda los logs en app.log
        handler.setLevel(logging.DEBUG)
        app.logger.addHandler(handler)

        udp_thread = threading.Thread(target=udp_listener)
        udp_thread.start()

        # Iniciar el hilo para mantener GPIO18 activo con reinicio periódico
        gpio_thread = threading.Thread(target=gpio_maintain_and_restart, daemon=True)
        gpio_thread.start()

        app.run(host='0.0.0.0', port=5001, threaded=True)

    finally:
        serverPlayerOne.stop()
        print("Closing the application")
