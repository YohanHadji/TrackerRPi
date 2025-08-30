#!/usr/bin/env python3
import argparse, struct, socket, threading, time, math, sys
from communication import (
    capsule_instance, sock, TEENSY_IP, TEENSY_PORT, UDP_PORT,
    sendTargetToTeensy, LightPoint,
    newPacketReceived, newPacketReceivedType, returnLastPacketData
)
from communication import sendAbsPosToTeensy
# ----------------- Telemetría (id=33) -----------------
_current = {"az": None, "el": None}

def _listen_capsules(bind_ip="0.0.0.0", port=UDP_PORT):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((bind_ip, port))
    s.settimeout(0.5)
    while True:
        try:
            data, _ = s.recvfrom(4096)
            for b in data:
                capsule_instance.decode(b)  # communication actualiza estados internos
        except socket.timeout:
            pass
        except Exception:
            pass

def get_tracker_pose(wait=True, timeout=1.0):
    t0 = time.time()
    while True:
        if newPacketReceived():
            typ = newPacketReceivedType()
            if typ == "dataFromTracker":
                az, el = returnLastPacketData(typ)
                _current["az"], _current["el"] = float(az), float(el)
                return _current["az"], _current["el"]
        if not wait:
            return _current["az"], _current["el"]
        if time.time() - t0 > timeout:
            return _current["az"], _current["el"]

# ----------------- Helpers de envío -----------------
def send_enable(on, idRadius=25, lockRadius=100, lightLifetime=200, lightThreshold=200, gain=1, exposureTime=100):
    vals = (int(idRadius), int(lockRadius), int(lightLifetime),
            int(lightThreshold), int(gain), int(exposureTime),
            1 if on else 0)
    payload = struct.pack("<iiiiiii", *vals)
    pkt = bytearray(capsule_instance.encode(0x10, payload, len(payload)))
    sock.sendto(pkt, (TEENSY_IP, TEENSY_PORT))
    print(f"[OK] ENABLE {'ON' if on else 'OFF'} settings={vals}")

def send_rel(dx, dy, kp=5.0, maxSpeed=50.0, cameraID=33, name="EXT", age=0):
    pt = LightPoint(name=name[:4], isVisible=True, x=int(dx), y=int(dy), age=int(age))
    sendTargetToTeensy(pt, int(cameraID), float(kp), float(maxSpeed))
    print(f"[REL] x={pt.x:+6d} y={pt.y:+6d} kp={kp:.1f} vmax={maxSpeed:.1f}")

def send_stop():
    for _ in range(3):
        send_rel(0, 0, kp=0, maxSpeed=0, cameraID=33, name="STOP")
        time.sleep(0.05)
    send_enable(False)

# ----------------- Control ABS seguro -----------------
def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

def goto_abs_safe(az_set, el_set, *,
                  base_gain=20.0, kp=15.0, vmax=2.0,
                  tol_deg=0.2, timeout=12.0,
                  max_cmd=200.0, dcmd_max=30.0,
                  invert_az=False, invert_el=False, swap=False,
                  verbose=False):
    # Listener
    t = threading.Thread(target=_listen_capsules, daemon=True)
    t.start()

    # Pose inicial
    az, el = get_tracker_pose(wait=True, timeout=2.0)
    if az is None:
        print("[WARN] No llega telemetría id=33. Abort.")
        return False
    print(f"[POSE] start az={az:.3f} el={el:.3f} -> target az={az_set:.3f} el={el_set:.3f}")

    t0 = time.time()
    prev_dx = prev_dy = 0.0
    stale_cnt = 0
    last_az, last_el = az, el

    try:
        while True:
            az, el = get_tracker_pose(wait=True, timeout=0.5)
            if az is None:
                continue

            # ¿telemetría se mueve?
            if abs(az - last_az) < 1e-3 and abs(el - last_el) < 1e-3:
                stale_cnt += 1
            else:
                stale_cnt = 0
            last_az, last_el = az, el
            if stale_cnt > 40:  # ~20 s si timeout 0.5
                print("[ERROR] Telemetría congelada. STOP.")
                send_stop()
                return False

            err_az = (az_set - az)
            err_el = (el_set - el)
            if abs(err_az) <= tol_deg and abs(err_el) <= tol_deg:
                print(f"[OK] Reached: az={az:.3f} el={el:.3f} | err={err_az:.3f},{err_el:.3f} deg")
                send_stop()
                return True

            # Ganancia adaptativa
            err_mag = math.hypot(err_az, err_el)
            gain = base_gain * (1.0 + 0.5 * clamp(err_mag/10.0, 0.0, 1.0))

            # Mapear errores a comandos (posible swap e inversión por eje)
            cmd_az = -err_az if invert_az else err_az
            cmd_el = -err_el if invert_el else err_el
            dx_raw = (cmd_el if swap else cmd_az) * gain
            dy_raw = (cmd_az if swap else cmd_el) * gain

            # Slew-rate + clamp
            dx = prev_dx + clamp(dx_raw - prev_dx, -dcmd_max, dcmd_max)
            dy = prev_dy + clamp(dy_raw - prev_dy, -dcmd_max, dcmd_max)
            dx = clamp(dx, -max_cmd, max_cmd)
            dy = clamp(dy, -max_cmd, max_cmd)

            if verbose:
                print(f"[STEP] az={az:7.3f} el={el:7.3f} | err=({err_az:+7.3f},{err_el:+7.3f}) "
                      f"| cmd=({dx:+6.1f},{dy:+6.1f}) gain={gain:5.1f}")

            send_rel(dx, dy, kp=kp, maxSpeed=vmax, cameraID=33, name="CTRL")
            prev_dx, prev_dy = dx, dy

            if time.time() - t0 > timeout:
                print(f"[TIMEOUT] err={err_az:.3f},{err_el:.3f} deg | último cmd x={dx:.1f} y={dy:.1f}")
                send_stop()
                return False

    except KeyboardInterrupt:
        print("\n[INTERRUPT] STOP de emergencia")
        send_stop()
        return False
    except Exception as e:
        print(f"[ERROR] {e}\nSTOP de emergencia")
        send_stop()
        return False

# ----------------- CLI -----------------
def main():
    p = argparse.ArgumentParser(description="Cliente GOTO seguro (con clamps, slew-rate y STOP)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # enable
    e = sub.add_parser("enable", help="Enable/disable (0x10)")
    e.add_argument("--on", action="store_true")
    e.add_argument("--idRadius", type=int, default=25)
    e.add_argument("--lockRadius", type=int, default=100)
    e.add_argument("--lightLifetime", type=int, default=200)
    e.add_argument("--lightThreshold", type=int, default=200)
    e.add_argument("--gain", type=int, default=1)
    e.add_argument("--exposureTime", type=int, default=100)
    # parser:
    d = sub.add_parser("abs-direct", help="GOTO absoluto nativo: envía packet_id=0x03 (2 floats)")
    d.add_argument("--az", type=float, required=True)
    d.add_argument("--el", type=float, required=True)
    # rel
    r = sub.add_parser("rel", help="Mover relativo (0x01)")
    r.add_argument("--dx", type=float, required=True)
    r.add_argument("--dy", type=float, required=True)
    r.add_argument("--kp", type=float, default=5.0)
    r.add_argument("--maxSpeed", type=float, default=50.0)
    r.add_argument("--cameraID", type=int, default=33)

    # abs-track
    g = sub.add_parser("abs-track", help="GOTO con lazo seguro")
    g.add_argument("--az", type=float, required=True)
    g.add_argument("--el", type=float, required=True)
    g.add_argument("--base-gain", type=float, default=20.0)
    g.add_argument("--kp", type=float, default=15.0)
    g.add_argument("--maxSpeed", type=float, default=2.0)
    g.add_argument("--tol", type=float, default=0.2)
    g.add_argument("--timeout", type=float, default=12.0)
    g.add_argument("--max-cmd", type=float, default=200.0)
    g.add_argument("--dcmd-max", type=float, default=30.0)
    g.add_argument("--invert-az", action="store_true")
    g.add_argument("--invert-el", action="store_true")
    g.add_argument("--swap", action="store_true", help="intercambia cmd az/el -> dx/dy")
    g.add_argument("--verbose", action="store_true")

    # pose
    po = sub.add_parser("pose", help="Muestra telemetría az/el")
    po.add_argument("--watch", action="store_true", help="refresca continuamente")
    po.add_argument("--period", type=float, default=0.5)

    # stop
    s = sub.add_parser("stop", help="STOP de emergencia (zeros + disable)")

    args = p.parse_args()

    if args.cmd == "enable":
        send_enable(args.on, args.idRadius, args.lockRadius, args.lightLifetime,
                    args.lightThreshold, args.gain, args.exposureTime)

    elif args.cmd == "rel":
        send_rel(args.dx, args.dy, args.kp, args.maxSpeed, args.cameraID)

    elif args.cmd == "abs-track":
        goto_abs_safe(args.az, args.el,
                      base_gain=args.base_gain, kp=args.kp, vmax=args.maxSpeed,
                      tol_deg=args.tol, timeout=args.timeout,
                      max_cmd=args.max_cmd, dcmd_max=args.dcmd_max,
                      invert_az=args.invert_az, invert_el=args.invert_el, swap=args.swap,
                      verbose=args.verbose)

    elif args.cmd == "pose":
        th = threading.Thread(target=_listen_capsules, daemon=True)
        th.start()
        az, el = get_tracker_pose(wait=True, timeout=2.0)
        if az is None:
            print("No hay telemetría (id=33).")
            return
        if not args.watch:
            print(f"az={az:.3f} el={el:.3f}")
            return
        try:
            while True:
                az, el = get_tracker_pose(wait=True, timeout=1.0)
                if az is not None:
                    print(f"az={az:.3f} el={el:.3f}")
                time.sleep(max(0.05, args.period))
        except KeyboardInterrupt:
            print("\n[pose] terminado.")

    elif args.cmd == "stop":
        send_stop()


if __name__ == "__main__":
    main()
elif args.cmd == "abs-direct":
    sendAbsPosToTeensy(args.az, args.el)
    print(f"[OK] ABS_DIRECT -> az={args.az:.3f} el={args.el:.3f}")