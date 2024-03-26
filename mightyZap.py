import sys
import serial
import PythonLibMightyZap_Rasp_PC
import time

MightyZap = PythonLibMightyZap_Rasp_PC

Actuator_ID = 1

MightyZap.OpenMightyZap('/dev/ttyAMA0',57600)
time.sleep(1.0)
pos =0

while True: 

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID,3000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)
    
    time.sleep(3.0)

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID,3000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)

    time.sleep(3.0)
    
