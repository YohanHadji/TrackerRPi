from seabreeze.spectrometers import Spectrometer,list_devices 
import serial

spec = Spectrometer.from_first_available()
spec.integration_time_micros(200000)

# # Open the serial port receive messages from the Teensy 4.1 microcontroller connected via USB
# ser = serial.Serial('/dev/ttyACM0', 115200)

# servo1Position = 0
# servo2Position = 0

while True:
    wavelengthsData = spec.wavelengths()
    intensitiesData = spec.intensities()

    # Find the peak wavelength
    maxValueFound = 0
    for i in range(0, len(wavelengthsData)):
        if intensitiesData[i] > maxValueFound:
            maxIndex = i
            maxValueFound = intensitiesData[i]

    peakWavelength = wavelengthsData[maxIndex]
    
    # If a new line received from the Teensy, read the new servo positions data is "pos1,pos2"
    # servo1Position = 0
    # servo2Position = 0
    # while ser.in_waiting > 0:
    #     line = ser.readline().decode('utf-8').rstrip()
    #     # print(line)
    #     servo1Position, servo2Position = line.split(',')
    #     # print("Servo 1: " + servo1Position + " Servo 2: " + servo2Position)
    
    # print("Peak wavelength: " + str(round(peakWavelength,2)) + " nm" + " Intensity: " + str(maxValueFound))
    print(round(peakWavelength,2), maxValueFound)

