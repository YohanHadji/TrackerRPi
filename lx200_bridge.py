#!/usr/bin/env python3
import argparse, socket, struct, time, sys

HDR0 = 0x14
HDR1 = 0x00
ID_MANUAL = 0x63
ID_ABS    = 0x03

def checksum(b: bytes) -> int:
    return sum(b) & 0xFFFF  # <-- necesario uint16 para el Teensy

def pkt_manual(x: float, y: float, throttle: float, trigger: int) -> bytes:
    payload = struct.pack('<fffI', float(x), float(y), float(throttle), int(trigger))
    body = bytes([HDR0, HDR1, ID_MANUAL, len(payload)]) + payload
    return body + bytes([checksum(payload) & 0xFF])  # checksum 1 byte

def pkt_abs(az_deg: float, el_deg: float) -> bytes:
    payload = struct.pack('<ff', float(az_deg), float(el_deg))
    cs = checksum(payload)  # uint16
    payload_with_checksum = payload + struct.pack('<H', cs)
    body = bytes([HDR0, HDR1, ID_ABS, len(payload_with_checksum)]) + payload_with_checksum
    return body

def maybe_enable_broadcast(sock: socket.socket, ip: str):
    if ip.endswith('.255') or ip == '255.255.255.255':
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

def hexdump(b: bytes) -> str:
    return ' '.join(f'{x:02X}' for x in b)

def main():
    ap = argparse.ArgumentParser(description="Envía ABS con primer/refresh Manual")
    ap.add_argument('az', type=float)
    ap.add_argument('el', type=float)
    ap.add_argument('--ip', default='192.168.1.100')
    ap.add_argument('--port', type=int, default=8888)
    ap.add_argument('--rate-hz', type=float, default=10.0)
    ap.add_argument('--seconds', type=float, default=3.0)
    ap.add_argument('--throttle', type=float, default=0.30)
    ap.add_argument('--trigger', type=int, default=1)
    ap.add_argument('--x', type=float, default=0.0)
    ap.add_argument('--y', type=float, default=0.0)
    ap.add_argument('--final-trigger-off', action='store_true')
    args = ap.parse_args()

    period = 1.0 / max(1e-3, args.rate_hz)
    t_end = time.time() + max(0.1, args.seconds)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    maybe_enable_broadcast(sock, args.ip)
    dst = (args.ip, args.port)

    i = 0
    while time.time() < t_end:
        i += 1
        m = pkt_manual(args.x, args.y, args.throttle, args.trigger)
        a = pkt_abs(args.az, args.el)

        sock.sendto(m, dst)
        sock.sendto(a, dst)

        if i == 1:
            print(f"[DST] {args.ip}:{args.port}  rate={args.rate_hz} Hz  seconds={args.seconds}")
        if i <= 3:
            print(f"[TX{i}] 99 len={len(m)}  [HEX] {hexdump(m)}")
            print(f"[TX{i}] 03 len={len(a)}  [HEX] {hexdump(a)}")

        time.sleep(period)

    if args.final_trigger_off:
        m0 = pkt_manual(0.0, 0.0, args.throttle, 0)
        sock.sendto(m0, dst)
        print(f"[DONE] trigger=0  len={len(m0)}  [HEX] {hexdump(m0)}")

    sock.close()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
