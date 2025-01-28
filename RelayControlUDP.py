import locale
import curses
import socket
import time

locale.setlocale(locale.LC_ALL, '')  # Configurar localización del sistema

TEENSY_IP = "192.168.1.150"
TEENSY_PORT = 60000
STATUS_REFRESH_INTERVAL = 2  # Tiempo en segundos entre solicitudes automáticas de estado

def clean_response(response):
    """Limpia y organiza la respuesta eliminando duplicados y caracteres innecesarios."""
    lines = response.replace("\r", "").strip().split("\n")
    cleaned_lines = []
    seen_lines = set()
    for line in lines:
        if line not in seen_lines:  # Evitar líneas duplicadas
            cleaned_lines.append(line.strip())
            seen_lines.add(line.strip())
    return "\n".join(cleaned_lines)

def send_udp_command(command):
    """Envía un comando UDP al Teensy y devuelve la respuesta limpia."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)  # Timeout de 1 segundo para recibir respuesta
    try:
        sock.sendto(command.encode(), (TEENSY_IP, TEENSY_PORT))
        response, _ = sock.recvfrom(1024)  # Espera una respuesta del Teensy
        cleaned_response = clean_response(response.decode())
        print(f"\nComando enviado: {command}\nRespuesta recibida:\n{cleaned_response}\n")  # Depuración clara
        return cleaned_response
    except socket.timeout:
        print(f"\nComando enviado: {command}\nSin respuesta del servidor.\n")  # Depuración clara
        return "No hay respuesta del servidor."
    finally:
        sock.close()

def update_status(stdscr, status):
    """Actualiza la sección de estado en la interfaz, limpiando el área antes de escribir."""
    stdscr.clear()  # Limpia toda la pantalla para evitar superposición
    stdscr.addstr(0, 2, "Interfaz de Control de Rele", curses.color_pair(1))
    stdscr.addstr(2, 2, "Usa las teclas para controlar los reles y ver el estado", curses.color_pair(1))
    stdscr.addstr(3, 2, "[1-8] Encender rele | [q-w-e-r-t-z-u-i] Apagar rele", curses.color_pair(1))
    stdscr.addstr(4, 2, "[S] Ver estado del sistema | [D] Salir", curses.color_pair(1))

    stdscr.addstr(10, 2, "Estado del sistema:", curses.color_pair(2))
    for i, line in enumerate(status.split('\n')):
        stdscr.addstr(11 + i, 4, line, curses.color_pair(2))
    stdscr.refresh()

def main(stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.curs_set(0)

    status = "Cargando estado del sistema..."
    last_status_update = time.time() - STATUS_REFRESH_INTERVAL  # Forzar actualización inicial

    # Mapeo de teclas para apagar relés
    off_keys = {
        ord('q'): 1,
        ord('w'): 2,
        ord('e'): 3,
        ord('r'): 4,
        ord('t'): 5,
        ord('z'): 6,
        ord('u'): 7,
        ord('i'): 8,
    }

    while True:
        # Solicitar estado automáticamente cada intervalo definido
        if time.time() - last_status_update >= STATUS_REFRESH_INTERVAL:
            status = send_udp_command("STATUS")
            last_status_update = time.time()

        # Mostrar el estado actual en la interfaz
        update_status(stdscr, status)

        # Dibuja comandos enviados
        stdscr.addstr(6, 2, "Comandos enviados:", curses.color_pair(2))
        stdscr.refresh()

        # Lee la entrada del usuario
        key = stdscr.getch()

        # Encender relé 1-8
        if key in range(ord('1'), ord('9')):  
            relay = chr(key)
            command = f"RELAY_ON {relay}"
            response = send_udp_command(command)
            status = f"Comando enviado: {command}\n{response}"

        # Apagar relé 1-8 usando las teclas 'q-w-e-r-t-z-u-i'
        elif key in off_keys:  
            relay = off_keys[key]
            command = f"RELAY_OFF {relay}"
            response = send_udp_command(command)
            status = f"Comando enviado: {command}\n{response}"

        # Ver estado manualmente
        elif key in (ord('s'), ord('S')):  
            command = "STATUS"
            response = send_udp_command(command)
            status = f"Estado solicitado manualmente:\n{response}"

        # Salir
        elif key in (ord('d'), ord('D')):  
            break

curses.wrapper(main)
