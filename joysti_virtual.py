import tkinter as tk
import struct
import socket
import time

# Constantes para el encabezado del paquete
PRA = 0xFF
PRB = 0xFA

# Configuración de UDP
udp_target_ip = '192.168.1.100'
udp_target_port = 8888  # Reemplazar con el puerto UDP deseado

# Crear un socket UDP
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_udp_packet(packet):
    while True:
        try:
            udp_socket.sendto(packet, (udp_target_ip, udp_target_port))
            print("Paquete enviado exitosamente")
            break
        except OSError as e:
            if e.errno == 101:  # Red no accesible
                print("La red no es accesible. Reintentando en 5 segundos...")
                time.sleep(5)
            else:
                raise

def create_packet(x, y, throttle, trigger):
    joystick_data = struct.pack(
        'iiiiiiff', 1, trigger, int(x * 100), int(y * 100), 0, 99, throttle, 30
    )
    encoded_packet = bytes([PRA, PRB, 1, len(joystick_data)]) + joystick_data
    checksum = sum(joystick_data) & 0xFF
    encoded_packet += bytes([checksum])
    return encoded_packet

def update_values():
    try:
        x_axis = x_scale.get() / 100.0
        y_axis = y_scale.get() / 100.0
        throttle = throttle_scale.get()
        trigger = trigger_var.get()

        # Generar y enviar el paquete UDP
        packet = create_packet(x_axis, y_axis, throttle, trigger)
        send_udp_packet(packet)

        # Mostrar los valores actuales
        print(f"X-axis: {x_axis:.4f}, Y-axis: {y_axis:.4f}, Throttle: {throttle:.2f}, Trigger: {trigger}")

        # Actualizar cada 50 ms
        root.after(50, update_values)
    except Exception as e:
        print(f"Error al actualizar los valores: {e}")

def reset_values():
    """Restablece los valores de los deslizadores a sus valores predeterminados."""
    x_scale.set(0)
    y_scale.set(0)
    throttle_scale.set(0.10)
    trigger_var.set(0)
    print("Valores restablecidos: X=0, Y=0, Throttle=0.10, Trigger=0")

# Crear la ventana principal
root = tk.Tk()
root.title("Joystick Virtual")

# Eje X
x_label = tk.Label(root, text="Eje X (-14 a 14)")
x_label.pack()
x_scale = tk.Scale(root, from_=-1400, to=1400, orient="horizontal", length=300)
x_scale.set(0)
x_scale.pack()

# Eje Y
y_label = tk.Label(root, text="Eje Y (-14 a 14)")
y_label.pack()
y_scale = tk.Scale(root, from_=-1400, to=1400, orient="vertical", length=300)
y_scale.set(0)
y_scale.pack()

# Throttle
throttle_label = tk.Label(root, text="Throttle (0.10 a 30)")
throttle_label.pack()
throttle_scale = tk.Scale(root, from_=0.10, to=30, resolution=0.01, orient="horizontal", length=300)
throttle_scale.set(0.10)
throttle_scale.pack()

# Trigger
trigger_var = tk.IntVar()
trigger_checkbox = tk.Checkbutton(root, text="Trigger", variable=trigger_var)
trigger_checkbox.pack()

# Botón para restablecer los valores
reset_button = tk.Button(root, text="Restablecer", command=reset_values)
reset_button.pack()

# Iniciar el bucle de actualización de valores
update_values()

# Iniciar la interfaz gráfica
root.mainloop()
