#!/usr/bin/env python3
import argparse, json, math, time, socket
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# --- Constantes WGS84 ---
a = 6378137.0
f = 1/298.257223563
b = a*(1-f)
e2 = 1 - (b*b)/(a*a)

def geodetic_to_ecef(lat, lon, h):
    lat, lon = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2*math.sin(lat)**2)
    x = (N + h) * math.cos(lat) * math.cos(lon)
    y = (N + h) * math.cos(lat) * math.sin(lon)
    z = (N*(1 - e2) + h) * math.sin(lat)
    return x, y, z

def ecef_to_enu(x, y, z, lat0, lon0, h0):
    x0, y0, z0 = geodetic_to_ecef(lat0, lon0, h0)
    dx, dy, dz = x - x0, y - y0, z - z0
    lat0, lon0 = math.radians(lat0), math.radians(lon0)
    slat, clat = math.sin(lat0), math.cos(lat0)
    slon, clon = math.sin(lon0), math.cos(lon0)
    e = -slon*dx + clon*dy
    n = -clon*slat*dx - slon*slat*dy + clat*dz
    u =  clon*clat*dx + slon*clat*dy + slat*dz
    return e, n, u

def az_el_from_latlon(lat, lon, h, lat0, lon0, h0):
    x, y, z = geodetic_to_ecef(lat, lon, h)
    e, n, u = ecef_to_enu(x, y, z, lat0, lon0, h0)
    az = (math.degrees(math.atan2(e, n)) + 360.0) % 360.0
    slant = math.sqrt(e*e + n*n + u*u)
    el = math.degrees(math.asin(u / slant))
    rng_km = slant / 1000.0
    return az, el, rng_km

def feet_to_m(ft): return 0.3048 * ft

def read_aircrafts(src, timeout=0.8):
    if src.startswith("http://") or src.startswith("https://"):
        with urlopen(src, timeout=timeout) as r:
            return json.load(r)
    else:
        with open(src, "r") as f:
            return json.load(f)

def choose_target(ac_list, lat0, lon0, h0, min_el, max_range_km):
    now = time.time()
    best = None
    best_score = 1e9
    for ac in ac_list:
        if "lat" not in ac or "lon" not in ac:
            continue
        seen = ac.get("seen_pos", ac.get("seen", 9e9)) or 9e9
        if seen > 3.0:
            continue  # posición fresca
        alt_ft = ac.get("alt_geom") or ac.get("alt_baro")
        if not alt_ft:
            continue
        h = feet_to_m(alt_ft)
        az, el, rng = az_el_from_latlon(ac["lat"], ac["lon"], h, lat0, lon0, h0)
        if el < min_el or rng > max_range_km:
            continue
        # score simple: cerca + alto + reciente
        score = rng - 0.02*el + 0.5*seen
        if score < best_score:
            best_score = score
            best = {"hex": ac.get("hex"), "az": az, "el": el, "rng": rng}
    return best

def wrap_az_delta(new, old):
    # devuelve delta en [-180, +180]
    return ((new - old + 540) % 360) - 180

def send_rotctld(host, port, az, el):
    cmd = f"P {az:.2f} {el:.2f}\n"
    with socket.create_connection((host, port), timeout=0.5) as s:
        s.sendall(cmd.encode("ascii"))

def main():
    ap = argparse.ArgumentParser(description="ADS-B (dump1090) -> rotctld bridge")
    ap.add_argument("--adsb", default="/run/dump1090-fa/aircraft.json",
                    help="Ruta local o URL de aircraft.json (p.ej. http://192.168.1.156:8080/data/aircraft.json)")
    ap.add_argument("--rot-host", default="127.0.0.1")
    ap.add_argument("--rot-port", type=int, default=4533)
    ap.add_argument("--site-lat", type=float, required=True)
    ap.add_argument("--site-lon", type=float, required=True)
    ap.add_argument("--site-alt", type=float, default=0.0, help="Altura del sitio en metros")
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--min-el", type=float, default=5.0)
    ap.add_argument("--max-range", type=float, default=150.0)
    ap.add_argument("--deadband", type=float, default=0.3, help="histeresis en grados")
    ap.add_argument("--alpha", type=float, default=1.0, help="suavizado [0..1], 1=sin filtro")
    ap.add_argument("--fix-hex", default=None, help="seguir solo este hex (opcional)")
    args = ap.parse_args()

    lat0, lon0, h0 = args.site_lat, args.site_lon, args.site_alt
    dt = 1.0 / max(args.hz, 0.1)

    last_az, last_el = None, None
    print(f"[ADSBR] leyendo de {args.adsb} -> rotctld {args.rot_host}:{args.rot_port} @ {args.hz} Hz")
    while True:
        try:
            data = read_aircrafts(args.adsb)
            ac_list = data.get("aircraft", []) if isinstance(data, dict) else []
            if args.fix_hex:
                ac_list = [a for a in ac_list if a.get("hex","").lower()==args.fix_hex.lower()]
            tgt = choose_target(ac_list, lat0, lon0, h0, args.min_el, args.max_range)
            if tgt:
                az, el = tgt["az"], tgt["el"]
                # suavizado angular
                if last_az is not None and args.alpha < 1.0:
                    az = (last_az + args.alpha * wrap_az_delta(az, last_az)) % 360.0
                    el = last_el + args.alpha * (el - last_el)
                # deadband
                if (last_az is None or
                    abs(wrap_az_delta(az, last_az)) > args.deadband or
                    abs(el - last_el) > args.deadband):
                    send_rotctld(args.rot_host, args.rot_port, az, el)
                    last_az, last_el = az, el
            time.sleep(dt)
        except (URLError, HTTPError) as e:
            print("[ADSBR] URL error:", e)
            time.sleep(1.0)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print("[ADSBR] Lectura JSON:", e)
            time.sleep(0.5)
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print("[ADSBR] rotctld:", e)
            time.sleep(0.5)
        except Exception as e:
            print("[ADSBR] WARN:", e)
            time.sleep(0.2)

if __name__ == "__main__":
    main()
