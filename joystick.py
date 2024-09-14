import pygame
import time
import serial
import struct
import socket

# Constants for the packet header
PRA = 0xFF
PRB = 0xFA

# UDP setup
udp_target_ip = '192.168.1.100'
udp_target_port = 8888  # Replace with the desired UDP port

# Create a UDP socket
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_udp_packet(packet):
    global baud_rate
    while True:
        try:
            udp_socket.sendto(packet, (udp_target_ip, udp_target_port))
            # udp_socket.sendto(packet, (udp_target_ip_2,udp_target_port))
            print("Packet sent successfully")
            break
        except OSError as e:
            if e.errno == 101:  # Network is unreachable
                print("Network is unreachable. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                raise

# Initialize Pygame
pygame.init()

# Initialize the joystick
pygame.joystick.init()

# Check for joystick availability
if pygame.joystick.get_count() == 0:
    print("No joystick found.")
    exit()

# Initialize the first joystick
joystick = pygame.joystick.Joystick(0)
joystick.init()

print("Joystick name:", joystick.get_name())
print("Number of axes:", joystick.get_numaxes())
print("Number of buttons:", joystick.get_numbuttons())

joystickInitialised = False

try:
    while True:
        # Process pygame events
        pygame.event.get()
        
        # if event.type == pygame.JOYAXISMOTION:
        x_axis = round(joystick.get_axis(0),2)  # X-axis value
        y_axis = -round(joystick.get_axis(1),2) # Y-axis value
        speed = joystick.get_axis(2)  # Throttle level
        trigger = joystick.get_button(0)
        
        if  (x_axis==0):
            joystickInitialized = True
        if (y_axis==0):
            joystickInitialised = True
        
        speed = round(((((-speed)+1)/2.0)*29.9), 2)+0.1
        
        x_axis = x_axis*speed
        y_axis = y_axis*speed
        
        if (joystickInitialised): 
            # Encode joystick data
            joystick_data = struct.pack('iiiiiiff',1,trigger,int(x_axis*100),int(y_axis*100), 0, 99, 1.0, 30)
            encoded_packet = bytes([PRA, PRB, 1, len(joystick_data)]) + joystick_data
            # # Calculate and set the checksum
            checksum = sum(joystick_data) & 0xFF
            encoded_packet += bytes([checksum])

            # Send the encoded packet over UDP
            send_udp_packet(encoded_packet)

            print(f"X-axis: {x_axis:.4f}, Y-axis: {y_axis:.4f}, Throttle: {speed:.2f}")
            
        time.sleep(0.05)
    

except KeyboardInterrupt:
    print("Exiting...")

finally:
    # Quit pygame
    pygame.quit()
