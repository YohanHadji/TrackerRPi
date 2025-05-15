import locale
import curses
import socket
import time
from datetime import datetime

locale.setlocale(locale.LC_ALL, '')

TEENSY_IP = "192.168.1.150"
TEENSY_PORT = 60000
STATUS_REFRESH_INTERVAL = 2
LOG_FILE = "relay_log.txt"


RELAY_NAMES = {
    1: "Teensy control motores (Q)",
    2: "Driver Motores Azi y Ele (W)",
    3: "Swich Eternet (E)",
    4: "Camara Buscador  pi (R)",
    5: "Control Fuente 12V Servos del colimador (T)",
    6: "control Swich USB colimador (G)",
    7: "Colimador PI5 (U)",
    8: "Camara canon colimador (I)",
    9: "....(O)",
    10: ".....(P)",
    11: ".....(J)",
    12: "......(K)"
}
def log_action(relay, action, origin="RPI-Terminal"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = RELAY_NAMES.get(relay, f"RELAY {relay}")
    with open(LOG_FILE, "a") as f:
        f.write(f"{timestamp} | {name} (RELAY {relay}) | {action.upper()} | from {origin}\n")

def clean_response(response):
    lines = response.replace("\r", "").strip().split("\n")
    cleaned, seen = [], set()
    for line in lines:
        line = line.strip()
        if line and line not in seen:
            cleaned.append(line)
            seen.add(line)
    return "\n".join(cleaned)

def format_status_with_names(status_text):
    lines = status_text.split("\n")
    formatted_lines = []
    for line in lines:
        if line.startswith("Relé"):
            try:
                num = int(line.split()[1].strip(":"))
                name = RELAY_NAMES.get(num, "")
                if name and f"→ {name}" not in line:
                    line += f"  → {name}"
            except:
                pass
        formatted_lines.append(line)
    return "\n".join(formatted_lines)

def send_udp_command(command):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        sock.sendto(command.encode(), (TEENSY_IP, TEENSY_PORT))
        response, _ = sock.recvfrom(1024)
        return clean_response(response.decode())
    except socket.timeout:
        return "⚠️ Sin respuesta del Teensy."
    except Exception as e:
        return f"⚠️ Error: {e}"
    finally:
        sock.close()

def update_status(stdscr, status_text, msg=""):
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    stdscr.addstr(0, 2, "🟢 Interfaz de Control de Rele", curses.color_pair(1))
    stdscr.addstr(2, 2, "[1–9,a,b,c]=ON | [q–g,o,p,j,k]=OFF", curses.color_pair(1))
    stdscr.addstr(3, 2, "[S]=Estado | [X]=All ON | [Z]=All OFF | [D]=Salir", curses.color_pair(1))

    stdscr.addstr(5, 2, "📊 Estado del sistema:", curses.color_pair(2))

    for i, line in enumerate(status_text.split('\n')):
        if 6 + i < height:
            if "ON" in line:
                color = curses.color_pair(1)
            elif "OFF" in line:
                color = curses.color_pair(3)
            else:
                color = curses.color_pair(2)
            stdscr.addstr(6 + i, 4, line[:width - 5], color)

    if msg:
        stdscr.addstr(height - 3, 2, msg[:width - 4], curses.color_pair(3))

    stdscr.refresh()

def main(stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)  # ON
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK) # Info
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)    # OFF
    curses.curs_set(0)

    raw_status = send_udp_command("STATUS")
    status = format_status_with_names(raw_status)
    last_status_update = time.time()
    message = ""

    on_keys = {
        ord('1'): 1, ord('2'): 2, ord('3'): 3, ord('4'): 4, ord('5'): 5,
        ord('6'): 6, ord('7'): 7, ord('8'): 8, ord('9'): 9,
        ord('a'): 10, ord('b'): 11, ord('c'): 12
    }

    off_keys = {
        ord('q'): 1, ord('w'): 2, ord('e'): 3, ord('r'): 4, ord('t'): 5,
        ord('g'): 6, ord('u'): 7, ord('i'): 8,
        ord('o'): 9, ord('p'): 10, ord('j'): 11, ord('k'): 12
    }

    while True:
        if time.time() - last_status_update >= STATUS_REFRESH_INTERVAL:
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)
            last_status_update = time.time()

        update_status(stdscr, status, message)
        message = ""

        key = stdscr.getch()

        if key in on_keys:
            relay = on_keys[key]
            command = f"RELAY_ON{relay}"
            result = send_udp_command(command)
            log_action(relay, "ON")
            message = f"✅ {RELAY_NAMES[relay]} encendido."
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)

        elif key in off_keys:
            relay = off_keys[key]
            command = f"RELAY_OFF{relay}"
            result = send_udp_command(command)
            log_action(relay, "OFF")
            message = f"⛔ {RELAY_NAMES[relay]} apagado."
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)

        elif key in (ord('s'), ord('S')):
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)
            message = "🔄 Estado actualizado."

        elif key in (ord('x'), ord('X')):
            send_udp_command("RELAY_ALL_ON")
            log_action("ALL", "ON")
            message = "✅ Todos los relés ENCENDIDOS."
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)

        elif key in (ord('z'), ord('Z')):
            send_udp_command("RELAY_ALL_OFF")
            log_action("ALL", "OFF")
            message = "⛔ Todos los relés APAGADOS."
            raw_status = send_udp_command("STATUS")
            status = format_status_with_names(raw_status)

        elif key in (ord('d'), ord('D')):
            break

curses.wrapper(main)
