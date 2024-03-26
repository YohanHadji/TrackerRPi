import sys
import serial
import PythonLibMightyZap_Rasp_PC
import time

MightyZap = PythonLibMightyZap_Rasp_PC

Actuator_ID_X = 100
Actuator_ID_Y = 101

MightyZap.OpenMightyZap('/dev/ttyAMA0',57600)
time.sleep(1.0)
pos =0

while True: 

    print("Moving to 3000")

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID_X,3000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID_Y,3000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)
    
    time.sleep(3.0)

    print("Moving to 0")

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID_X,1000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)

    successWrite = False
    while (not successWrite):
        try:
            MightyZap.GoalPosition(Actuator_ID_Y,1000)
            successWrite = True
        except serial.SerialException as e:
            print("Serial write issue:", e)
        time.sleep(0.1)

    time.sleep(3.0)
    
