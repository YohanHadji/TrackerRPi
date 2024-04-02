import serial
import struct
import socket
import time

# Constants for the packet header
PRA = 0xFF
PRB = 0xFA

# UDP setup
udp_target_ip = '192.168.1.100'
udp_target_ip_2 = '192.168.1.114'
udp_target_port = 8888  # Replace with the desired UDP port

baud_rate = 9600
usbSuccess = False

def open_serial_connection():
    global baud_rate, usbSuccess
    while (not usbSuccess):
        # Try connecting to either ttyACM0 or ttyACM1
        for port_suffix in range(2):
            serial_port = f'/dev/ttyACM{port_suffix}'
            print(f"Trying to connect to {serial_port}...")
            try:
                ser = serial.Serial(serial_port, baud_rate)
                print(f"Connected to {serial_port}")
                usbSuccess = True
                return ser
            except:
                print(f"Failed to connect to {serial_port}")
                continue

    # If no successful connection is established, return None
    return None

def send_udp_packet(packet):
    global baud_rate
    while True:
        try:
            udp_socket.sendto(packet, (udp_target_ip, udp_target_port))
            udp_socket.sendto(packet, (udp_target_ip_2,udp_target_port))
            print("Packet sent successfully")
            break
        except OSError as e:
            if e.errno == 101:  # Network is unreachable
                print("Network is unreachable. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                raise
# Set the baud rate based on your Arduino configuration
    
# Try to open a serial connection
ser = open_serial_connection()

# Create a UDP socket
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while ser is None:
    print("Failed to connect. Retrying in 5 seconds...")
    time.sleep(5)
    ser = open_serial_connection()

try:
    while True:
        # Read data from the Arduino
        line = ser.readline().decode('utf-8').strip()

        # Split the line into two values based on the comma
        values = line.split(',')

        # Check if there are two values
        if len(values) == 7:
            # Parse the values as floats
            joystickX = float(values[0])
            joystickY = float(values[1])
            joystickBtn = int(values[2])
            swUp = int(values[3])
            swDown = int(values[4])
            swLeft = int(values[5])
            swRight = int(values[6])

            # Encode joystick data
            joystick_data = struct.pack('ffbbbbb', joystickX, joystickY, joystickBtn,  swUp, swDown, swLeft, swRight)
            encoded_packet = bytes([PRA, PRB, 99, len(joystick_data)]) + joystick_data
            # Calculate and set the checksum
            checksum = sum(joystick_data) & 0xFF
            encoded_packet += bytes([checksum])

            # Send the encoded packet over UDP
            send_udp_packet(encoded_packet)

            # Print the parsed values
            print(f"Joystick X: {joystickX}, Joystick Y: {joystickY}")

except KeyboardInterrupt:
    # Handle Ctrl+C to gracefully exit the program
    print("\nExiting program")

finally:
    # Close the serial connection and UDP socket when done
    if ser is not None:
        ser.close()
    udp_socket.close()

