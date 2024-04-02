import struct
import socket
import time
import serial

# Constants for the packet header
PRA = 0xFF
PRB = 0xFA

# UDP setup
udp_target_ip = '192.168.1.100'
udp_target_port = 8888  # Replace with the desired UDP port

# Create a serial connection

successUsb = False
usbPortToggle = False

while (not successUsb): 
    try: 
        # Set the serial port and baud rate based on your Arduino configuration
        if (usbPortToggle):
            serial_port = '/dev/ttyACM0'  # Adjust the port based on your Arduino connection
            usbPortToggle = False
        else:
            serial_port = '/dev/ttyACM1'
            usbPortToggle = True
    
        baud_rate = 9600  # Match this with your Arduino's baud rate
        ser = serial.Serial(serial_port, baud_rate)
        successUsb = True
    except:
        print("USB not connected, trying again")
        time.sleep(1)

# Create a UDP socket
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    while True:
        # Read data from the Arduino
        line = ser.readline().decode('utf-8').strip()

        # Split the line into two values based on the comma
        values = line.split(',')

        # Check if there are two values
        if len(values) == 2:
            # Parse the values as floats
            joystickX = float(values[0])
            joystickY = float(values[1])

            # Encode joystick data
            joystick_data = struct.pack('ff', joystickX, joystickY)
            encoded_packet = bytes([PRA, PRB, 0x04, len(joystick_data)]) + joystick_data

            # Calculate and set the checksum
            checksum = sum(joystick_data) & 0xFF
            encoded_packet += bytes([checksum])

            # Send the encoded packet over UDP
            udp_socket.sendto(encoded_packet, (udp_target_ip, udp_target_port))

            # Print the parsed values
            print(f"Joystick X: {joystickX}, Joystick Y: {joystickY}")

except KeyboardInterrupt:
    # Handle Ctrl+C to gracefully exit the program
    print("\nExiting program")

finally:
    # Close the serial connection and UDP socket when done
    ser.close()
    udp_socket.close()
