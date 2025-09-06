#!/usr/bin/env python3
# Teensy UDP Hub / Arbiter
# - Binds exclusively to :8888 to receive telemetry from Teensy and fans it out to local clients.
# - Accepts commands from local clients and forwards to Teensy with arbitration to avoid collisions.
#
# Usage:
#   1) Edit TEENSY_IP if needed.
#   2) Run:  python3 teensy_hub.py
#   3) Point apps to receive on 127.0.0.1:9001/9002/9003 and send commands to 127.0.0.1:9101/9102/9103
#      OR use iptables REDIRECT so legacy apps that send to 192.168.1.100:8888 are transparently captured:
#        sudo iptables -t nat -A OUTPUT -p udp -d 192.168.1.100 --dport 8888 -j REDIRECT --to-ports 9199
#        sudo iptables -t nat -D OUTPUT -p udp -d 192.168.1.100 --dport 8888 -j REDIRECT --to-ports 9199  # remove
#
# Master arbitration:
#   - AUTO: first active client becomes master for MASTER_TTL seconds (refreshes on activity).
#   - MANUAL: write 'c1'/'c2'/'c3' or a port (9101/9102/9103) to /tmp/teensy_hub_master
#
# Environment overrides:
#   TEENSY_IP, TEENSY_PORT, HUB_MASTER_TTL
#
import socket, select, time, os, threading

TEENSY_IP = os.getenv("TEENSY_IP", "192.168.1.100")
TEENSY_PORT = int(os.getenv("TEENSY_PORT", "8888"))

# Telemetry fanout (where local clients listen)
FANOUT_RX = [
    ("127.0.0.1", 9001),  # client 1
    ("127.0.0.1", 9002),  # client 2
    ("127.0.0.1", 9003),  # client 3
]

# Command intake from local clients
CLIENT_TX_PORTS = [9101, 9102, 9103]

# Extra port to accept commands via iptables REDIRECT
REDIRECT_PORT = 9199

# Arbitration settings
MASTER_TTL = float(os.getenv("HUB_MASTER_TTL", "2.0"))  # seconds
MODE_FILE = "/tmp/teensy_hub_master"  # manual override

# Rate limiting
MAX_CMD_RATE = 250.0  # packets per second
MIN_CMD_INTERVAL = 1.0 / MAX_CMD_RATE

def _udp_bind(ip, port, reuse=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if reuse:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind((ip, port))
    return s

def main():
    print("[hub] Teensy UDP hub starting...")
    print(f"[hub] Teensy at {TEENSY_IP}:{TEENSY_PORT}")
    print(f"[hub] Telemetry fanout -> {', '.join([f'{h}:{p}' for (h,p) in FANOUT_RX])}")
    print(f"[hub] Accepting client commands on ports {CLIENT_TX_PORTS} and REDIRECT port {REDIRECT_PORT}")

    # Socket to receive telemetry from Teensy (be exclusive owner of 8888)
    s_telem_in = _udp_bind("0.0.0.0", TEENSY_PORT, reuse=False)
    s_telem_in.setblocking(False)

    # Socket to send to teensy and to fanout to local
    s_to_teensy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_fanout = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Command input sockets
    cmd_socks = []
    label_by_sock = {}
    for i, port in enumerate(CLIENT_TX_PORTS, start=1):
        s = _udp_bind("127.0.0.1", port, reuse=False)
        s.setblocking(False)
        cmd_socks.append(s)
        label_by_sock[s.fileno()] = f"c{i}"
    s_redirect = _udp_bind("0.0.0.0", REDIRECT_PORT, reuse=False)
    s_redirect.setblocking(False)
    cmd_socks.append(s_redirect)
    label_by_sock[s_redirect.fileno()] = "redir"

    # Arbitration state
    master_id = None     # "c1"/"c2"/"c3"/"redir"
    master_expire = 0.0
    last_cmd_ts = 0.0
    manual_mode = False
    last_mode_check = 0.0

    def current_mode():
        return "MANUAL" if manual_mode else "AUTO"

    print(f"[hub] Arbitration: {current_mode()} (TTL={MASTER_TTL:.2f}s)")

    while True:
        now = time.time()

        # Manual mode file check
        if now - last_mode_check > 0.5:
            last_mode_check = now
            try:
                if os.path.exists(MODE_FILE):
                    with open(MODE_FILE, "r") as f:
                        val = f.read().strip()
                    if val:
                        if not manual_mode:
                            print("[arb] MANUAL mode enabled")
                        manual_mode = True
                        if val in ("c1", "c2", "c3", "redir"):
                            master_id = val
                        else:
                            # maybe it's a port
                            try:
                                port = int(val)
                                for s in cmd_socks:
                                    if s.getsockname()[1] == port:
                                        master_id = label_by_sock[s.fileno()]
                                        break
                            except ValueError:
                                pass
                        master_expire = float("inf")
                        print(f"[arb] MANUAL master -> {master_id}")
                else:
                    if manual_mode:
                        print("[arb] Manual mode cleared; back to AUTO")
                    manual_mode = False
                    master_id = None
                    master_expire = 0.0
            except Exception as e:
                print(f"[hub][warn] mode file error: {e}")

        # Poll sockets
        rlist = [s_telem_in] + cmd_socks
        readable, _, _ = select.select(rlist, [], [], 0.1)

        for s in readable:
            if s is s_telem_in:
                # Telemetry from Teensy -> fan out
                try:
                    data, addr = s.recvfrom(65535)
                except BlockingIOError:
                    continue
                for (h, p) in FANOUT_RX:
                    try:
                        s_fanout.sendto(data, (h, p))
                    except Exception as e:
                        print(f"[telem][warn] fanout to {h}:{p} failed: {e}")
            else:
                # Command from a client
                try:
                    data, addr = s.recvfrom(65535)
                except BlockingIOError:
                    continue

                sender_label = label_by_sock.get(s.fileno(), "unknown")

                # Arbitration
                if manual_mode:
                    if sender_label != master_id:
                        continue
                else:
                    if master_id is None or time.time() > master_expire:
                        master_id = sender_label
                        master_expire = time.time() + MASTER_TTL
                        print(f"[arb] master -> {master_id} (auto)")
                    elif sender_label != master_id:
                        continue
                    else:
                        master_expire = time.time() + MASTER_TTL

                # Rate limit
                now_ts = time.time()
                if now_ts - last_cmd_ts < MIN_CMD_INTERVAL:
                    time.sleep(max(0.0, MIN_CMD_INTERVAL - (now_ts - last_cmd_ts)))
                last_cmd_ts = time.time()

                # Forward to Teensy
                try:
                    s_to_teensy.sendto(data, (TEENSY_IP, TEENSY_PORT))
                except Exception as e:
                    print(f"[cmd][err] forward to Teensy failed: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n[hub] bye!")
