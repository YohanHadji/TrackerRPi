#!/usr/bin/env python3
import math, time, json, socket, threading, argparse
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from flask import Flask, request, jsonify, Response

# ====== Geodesia / conversiones ======
a = 6378137.0
f = 1/298.257223563
b = a*(1-f)
e2 = 1 - (b*b)/(a*a)
R_EARTH = 6371000.0

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

def haversine_km(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a_ = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2*math.atan2(math.sqrt(a_), math.sqrt(1-a_))
    return (R_EARTH * c) / 1000.0

def feet_to_m(ft): return 0.3048 * ft
def wrap_az_delta(new, old): return ((new - old + 540) % 360) - 180

# ====== Estado compartido ======
state = {
    "site": {"lat": 0.0, "lon": 0.0, "alt": 0.0},
    "adsb_src": "",
    "rot_host": "127.0.0.1",
    "rot_port": 4533,
    "settings": {
        "hz": 1.0,
        "min_el": 5.0,
        "max_ground": 10.0,   # km, radio horizontal
        "deadband": 0.3,      # deg
        "alpha": 0.6          # 1.0 = sin suavizado
    },
    "lock_hex": None,
    "current_target": None,   # dict con hex, az, el, rng, gnd_km
    "aircrafts": [],          # lista calculada para UI
}
lock = threading.Lock()

def send_rotctld(host, port, az, el):
    cmd = f"P {az:.2f} {el:.2f}\n"
    with socket.create_connection((host, port), timeout=0.5) as s:
        s.sendall(cmd.encode("ascii"))

def read_aircrafts(src, timeout=0.8):
    if src.startswith("http://") or src.startswith("https://"):
        with urlopen(src, timeout=timeout) as r:
            return json.load(r)
    else:
        with open(src, "r") as f:
            return json.load(f)

def compute_list(ac_raw, site, stg):
    out = []
    lat0, lon0, h0 = site["lat"], site["lon"], site["alt"]
    for ac in ac_raw:
        if "lat" not in ac or "lon" not in ac: continue
        seen = ac.get("seen_pos", ac.get("seen", 9e9)) or 9e9
        if seen > 5.0: continue
        alt_ft = ac.get("alt_geom") or ac.get("alt_baro")
        if not alt_ft: continue
        h = feet_to_m(alt_ft)
        az, el, slant_km = az_el_from_latlon(ac["lat"], ac["lon"], h, lat0, lon0, h0)
        gnd_km = haversine_km(lat0, lon0, ac["lat"], ac["lon"])
        if el < stg["min_el"] or gnd_km > stg["max_ground"]: continue
        out.append({
            "hex": ac.get("hex"),
            "flight": (ac.get("flight") or "").strip(),
            "lat": ac["lat"], "lon": ac["lon"],
            "alt_ft": alt_ft,
            "az": az, "el": el,
            "slant_km": slant_km, "gnd_km": gnd_km,
            "seen": seen,
            "gs": ac.get("gs"), "track": ac.get("track"), "squawk": ac.get("squawk")
        })
    # ordenar por distancia en planta
    out.sort(key=lambda x: (x["gnd_km"], -x["el"], x["seen"]))
    return out

def choose_target(ac_list, lock_hex):
    if lock_hex:
        for a in ac_list:
            if (a["hex"] or "").lower() == lock_hex.lower():
                return a
        return None
    # si no hay lock: el más cercano en planta y con buena elevación
    return ac_list[0] if ac_list else None

def tracker_loop():
    last_az, last_el = None, None
    while True:
        try:
            with lock:
                src = state["adsb_src"]; site = dict(state["site"]); stg = dict(state["settings"])
                rot_host, rot_port = state["rot_host"], state["rot_port"]
                lock_hex = state["lock_hex"]
            data = read_aircrafts(src)
            raw_list = data.get("aircraft", []) if isinstance(data, dict) else []
            ac_list = compute_list(raw_list, site, stg)
            tgt = choose_target(ac_list, lock_hex)
            with lock:
                state["aircrafts"] = ac_list
                state["current_target"] = tgt
            if tgt:
                az, el = tgt["az"], tgt["el"]
                if last_az is not None and stg["alpha"] < 1.0:
                    az = (last_az + stg["alpha"] * wrap_az_delta(az, last_az)) % 360.0
                    el = last_el + stg["alpha"] * (el - last_el)
                need = (last_az is None or
                        abs(wrap_az_delta(az, last_az)) > stg["deadband"] or
                        abs(el - last_el) > stg["deadband"])
                if need:
                    send_rotctld(rot_host, rot_port, az, el)
                    last_az, last_el = az, el
            time.sleep(max(0.05, 1.0/float(stg["hz"])))
        except Exception as e:
            # print y sigue (no paramos el hilo por errores de red)
            print("[TRACK] WARN:", e)
            time.sleep(0.5)

app = Flask(__name__)

HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ADS-B → ROT UI</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,Arial,sans-serif;margin:16px;}
h1{font-size:20px;margin:0 0 8px;}
.panel{display:flex;gap:16px;flex-wrap:wrap}
.card{border:1px solid #ddd;border-radius:10px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
table{border-collapse:collapse;width:100%;}
th,td{border-bottom:1px solid #eee;padding:6px 8px;font-size:14px;text-align:left;}
th{background:#fafafa;position:sticky;top:0;}
.badge{background:#eef;padding:2px 6px;border-radius:6px;}
button{padding:6px 10px;border:1px solid #ccc;border-radius:8px;background:#f6f6f6;cursor:pointer}
input{padding:6px 8px;border:1px solid #ccc;border-radius:8px;width:80px}
@media (max-width:800px){td:nth-child(6),th:nth-child(6),td:nth-child(7),th:nth-child(7){display:none}}
</style>
</head>
<body>
<h1>ADS-B → ROT UI</h1>
<div class="panel">
  <div class="card">
    <div><b>Fuente</b>: <span id="src"></span></div>
    <div><b>Sitio</b>: <span id="site"></span></div>
    <div><b>rotctld</b>: <span id="rot"></span></div>
    <div><b>Target</b>: <span id="target"></span> <button onclick="unlock()">Unlock</button></div>
  </div>
  <div class="card">
    <div><b>Parámetros</b></div>
    <div>min_el <input id="min_el" type="number" step="0.1"></div>
    <div>max_ground km <input id="max_ground" type="number" step="0.1"></div>
    <div>deadband <input id="deadband" type="number" step="0.1"></div>
    <div>alpha <input id="alpha" type="number" step="0.05" min="0" max="1"></div>
    <div>Hz <input id="hz" type="number" step="0.1" min="0.1"></div>
    <div style="margin-top:6px"><button onclick="save()">Guardar</button></div>
  </div>
</div>
<div class="card" style="margin-top:12px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
    <b>Tráficos visibles</b> <span class="badge" id="count">0</span>
    <input id="filter" placeholder="filtrar por callsign/hex" style="flex:1;max-width:300px">
  </div>
  <div style="max-height:60vh;overflow:auto">
  <table>
    <thead><tr>
      <th>Lock</th><th>HEX</th><th>Callsign</th><th>gnd km</th><th>el°</th><th>az°</th><th>alt ft</th><th>age s</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  </div>
</div>

<script>
let filt="";
document.getElementById('filter').addEventListener('input', e=>{filt=e.target.value.toLowerCase()});

async function load(){
  const st = await fetch('/api/status').then(r=>r.json());
  document.getElementById('src').textContent = st.adsb_src;
  document.getElementById('site').textContent = `${st.site.lat.toFixed(5)}, ${st.site.lon.toFixed(5)} @ ${st.site.alt} m`;
  document.getElementById('rot').textContent = `${st.rot_host}:${st.rot_port}`;
  document.getElementById('target').textContent = st.current_target ? `${st.current_target.hex}  az ${st.current_target.az.toFixed(1)}  el ${st.current_target.el.toFixed(1)}` : '—';

  const s = st.settings;
  ['min_el','max_ground','deadband','alpha','hz'].forEach(k=>{
    document.getElementById(k).value = s[k];
  });

  const ac = await fetch('/api/aircrafts').then(r=>r.json());
  const tb = document.getElementById('tbody'); tb.innerHTML='';
  let shown = 0;
  ac.forEach(a=>{
    const tag = (a.flight||"").toLowerCase() + " " + (a.hex||"");
    if(filt && !tag.includes(filt)) return;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><button onclick="lock('${a.hex}')">Lock</button></td>
      <td>${a.hex||''}</td>
      <td>${a.flight||''}</td>
      <td>${a.gnd_km.toFixed(1)}</td>
      <td>${a.el.toFixed(1)}</td>
      <td>${a.az.toFixed(1)}</td>
      <td>${a.alt_ft||''}</td>
      <td>${(a.seen||0).toFixed(1)}</td>`;
    tb.appendChild(tr);
    shown++;
  });
  document.getElementById('count').textContent = shown;
}

async function lock(hex){
  await fetch('/api/lock', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hex})});
  load();
}
async function unlock(){
  await fetch('/api/unlock', {method:'POST'});
  load();
}
async function save(){
  const s = {
    min_el: parseFloat(document.getElementById('min_el').value),
    max_ground: parseFloat(document.getElementById('max_ground').value),
    deadband: parseFloat(document.getElementById('deadband').value),
    alpha: parseFloat(document.getElementById('alpha').value),
    hz: parseFloat(document.getElementById('hz').value),
  };
  await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(s)});
}
load(); setInterval(load, 1000);
</script>
</body></html>
"""

@app.get("/")
def home():
    return Response(HTML, mimetype="text/html")

@app.get("/api/status")
def api_status():
    with lock:
        return jsonify({
            "adsb_src": state["adsb_src"],
            "site": state["site"],
            "rot_host": state["rot_host"],
            "rot_port": state["rot_port"],
            "settings": state["settings"],
            "lock_hex": state["lock_hex"],
            "current_target": state["current_target"],
        })

@app.get("/api/aircrafts")
def api_aircrafts():
    with lock:
        return jsonify(state["aircrafts"])

@app.post("/api/lock")
def api_lock():
    data = request.get_json(force=True)
    hexid = (data.get("hex") or "").strip()
    with lock:
        state["lock_hex"] = hexid or None
    return jsonify({"ok": True, "lock_hex": state["lock_hex"]})

@app.post("/api/unlock")
def api_unlock():
    with lock:
        state["lock_hex"] = None
    return jsonify({"ok": True})

@app.post("/api/settings")
def api_settings():
    data = request.get_json(force=True)
    with lock:
        s = state["settings"]
        for k in ("min_el","max_ground","deadband","alpha","hz"):
            if k in data and data[k] is not None:
                s[k] = float(data[k])
    return jsonify({"ok": True, "settings": state["settings"]})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adsb", required=True, help="URL o ruta de aircraft.json (p.ej. http://192.168.1.156:8080/data/aircraft.json)")
    ap.add_argument("--rot-host", default="127.0.0.1")
    ap.add_argument("--rot-port", type=int, default=4533)
    ap.add_argument("--site-lat", type=float, required=True)
    ap.add_argument("--site-lon", type=float, required=True)
    ap.add_argument("--site-alt", type=float, default=0.0)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--min-el", type=float, default=5.0)
    ap.add_argument("--max-ground", type=float, default=10.0)
    ap.add_argument("--deadband", type=float, default=0.3)
    ap.add_argument("--alpha", type=float, default=0.6)
    args = ap.parse_args()

    with lock:
        state["adsb_src"] = args.adsb
        state["rot_host"] = args.rot_host
        state["rot_port"] = args.rot_port
        state["site"] = {"lat": args.site_lat, "lon": args.site_lon, "alt": args.site_alt}
        state["settings"] = {
            "hz": args.hz, "min_el": args.min_el,
            "max_ground": args.max_ground, "deadband": args.deadband, "alpha": args.alpha
        }

    t = threading.Thread(target=tracker_loop, daemon=True)
    t.start()
    app.run(host=args.bind, port=args.port, threaded=True)

if __name__ == "__main__":
    main()
