#!/usr/bin/env python3
import math, time, json, socket, threading, argparse, re
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from flask import Flask, request, jsonify, Response

# ====== Geodesia / conversiones ======
a = 6378137.0
f = 1/298.257223563
b = a*(1-f)
e2 = 1 - (b*b)/(a*a)
R_EARTH = 6371000.0
KT_TO_MPS = 0.514444

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

def bearing_deg(lat1, lon1, lat2, lon2):
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dλ = math.radians(lon2-lon1)
    y = math.sin(dλ) * math.cos(φ2)
    x = math.cos(φ1)*math.sin(φ2) - math.sin(φ1)*math.cos(φ2)*math.cos(dλ)
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    return brng

def feet_to_m(ft): return 0.3048 * ft
def wrap180(d): return ((d + 180.0) % 360.0) - 180.0
def wrap_az_delta(new, old): return ((new - old + 540) % 360) - 180

# ====== Estado compartido ======
state = {
    "site": {"lat": 0.0, "lon": 0.0, "alt": 0.0},
    "adsb_src": "",
    "rot_host": "127.0.0.1",
    "rot_port": 4533,
    "settings": {
        "hz": 1.5,
        "min_el": 5.0,
        "max_ground": 10.0,    # km, radio horizontal
        "deadband": 0.3,       # deg
        "alpha": 0.6,          # 1.0 = sin suavizado
        "min_dwell_s": 8.0,    # permanencia mínima del objetivo
        "switch_margin_km": 3.0, # margen de mejora en gnd_km para permitir cambio
        "predict_hold_s": 8.0  # cuánto tiempo mantenemos con predicción si se corta el feed
    },
    "offset": {"az": 0.0, "el": 0.0},
    "lock_hex": None,
    "current_target": None,    # dict con campos enriquecidos
    "aircrafts": [],           # lista para la UI
    "profile": "Normal"        # Suave / Normal / Agresivo
}
lock = threading.Lock()

# Historial simple por HEX (para radial y predicción)
# {hex: {lat, lon, alt_m, gs_mps, track_deg, ts}}
history = {}

# ====== I/O rotctld ======
def send_rotctld(host, port, az, el):
    cmd = f"P {az:.2f} {el:.2f}\n"
    with socket.create_connection((host, port), timeout=0.6) as s:
        s.sendall(cmd.encode("ascii"))

FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
def read_rot_pos(host, port):
    with socket.create_connection((host, port), timeout=0.6) as s:
        s.sendall(b"p\n")
        s.settimeout(0.6)
        data = s.recv(256).decode("ascii", "ignore")
    nums = [float(x) for x in FLOAT_RE.findall(data)]
    if len(nums) >= 2:
        return float(nums[0]) % 360.0, float(nums[1])
    raise RuntimeError(f"rotctld response not parsed: {data!r}")

def read_aircrafts(src, timeout=0.8):
    if src.startswith("http://") or src.startswith("https://"):
        with urlopen(src, timeout=timeout) as r:
            return json.load(r)
    else:
        with open(src, "r") as f:
            return json.load(f)

# ====== Selección / enriquecimiento ======
def enrich_aircraft(ac, site, stg):
    """Devuelve dict con az/el, distancias, radial y tendencia."""
    lat0, lon0, h0 = site["lat"], site["lon"], site["alt"]
    lat, lon = ac["lat"], ac["lon"]
    alt_ft = ac.get("alt_geom") or ac.get("alt_baro")
    if not alt_ft:
        # usa última alt conocida si existe en history
        h = history.get(ac.get("hex",""), {}).get("alt_m", None)
        if h is None:
            return None
    else:
        h = feet_to_m(alt_ft)

    az, el, slant_km = az_el_from_latlon(lat, lon, h, lat0, lon0, h0)
    gnd_km = haversine_km(lat0, lon0, lat, lon)
    if el < stg["min_el"] or gnd_km > stg["max_ground"]:
        return None

    # velocidad y rumbo
    gs_mps = None
    if ac.get("gs") is not None:
        gs_mps = float(ac["gs"]) * KT_TO_MPS  # dump1090 da knots
    track = ac.get("track")

    # si falta gs/track, calcula con historial
    hexid = ac.get("hex","")
    prev = history.get(hexid)
    now = time.time()
    if (gs_mps is None or track is None) and prev and (now - prev["ts"]) <= 10:
        dt = max(0.1, now - prev["ts"])
        brg_prev = bearing_deg(prev["lat"], prev["lon"], lat, lon)
        dist_km = haversine_km(prev["lat"], prev["lon"], lat, lon)
        gs_mps = (dist_km*1000.0)/dt
        track = brg_prev

    # radial respecto al sitio (positivo si se ACERCA)
    trend = "cross"; radial_mps = 0.0
    try:
        if gs_mps is not None and track is not None:
            brg_site_to_ac = bearing_deg(lat0, lon0, lat, lon)
            # radial = -gs * cos(track - bearing_site_to_ac)
            radial_mps = - gs_mps * math.cos(math.radians((track - brg_site_to_ac + 540) % 360 - 180))
            if radial_mps > 10: trend = "approach"
            elif radial_mps < -10: trend = "recede"
            else: trend = "cross"
    except Exception:
        pass

    return {
        "hex": hexid,
        "flight": (ac.get("flight") or "").strip(),
        "lat": lat, "lon": lon,
        "alt_ft": alt_ft,
        "az": az, "el": el,
        "slant_km": slant_km, "gnd_km": gnd_km,
        "seen": ac.get("seen_pos", ac.get("seen", 9e9)) or 9e9,
        "gs": ac.get("gs"), "track": ac.get("track"),
        "radial_mps": radial_mps, "trend": trend
    }

def compute_list(ac_raw, site, stg):
    out = []
    for ac in ac_raw:
        if "lat" not in ac or "lon" not in ac: 
            continue
        e = enrich_aircraft(ac, site, stg)
        if e: out.append(e)
    out.sort(key=lambda x: (x["gnd_km"], -x["el"], x["seen"]))
    return out

def choose_target(ac_list, lock_hex, current, stg):
    now = time.time()
    if lock_hex:
        for a in ac_list:
            if (a["hex"] or "").lower() == lock_hex.lower():
                return a
        return None

    # “pegajosidad” (no cambiar salvo mejora clara o caducidad)
    if current:
        # ¿sigue válido?
        still = [a for a in ac_list if a["hex"] == current["hex"]]
        if still:
            cur = still[0]
            # tiempo mínimo de permanencia
            dwell_ok = (now - current.get("_since", now)) >= stg["min_dwell_s"]
            # si no cumplió dwell, seguir igual
            if not dwell_ok:
                cur["_since"] = current.get("_since", now)
                return cur
            # si cumplió dwell, solo cambiar si hay mejora clara
            best = ac_list[0]
            if best["hex"] == cur["hex"]:
                cur["_since"] = current.get("_since", now)
                return cur
            better = (best["gnd_km"] + 1e-3) < (cur["gnd_km"] - stg["switch_margin_km"])
            if better:
                best["_since"] = now
                return best
            else:
                cur["_since"] = current.get("_since", now)
                return cur
        else:
            # si nuestro target “desapareció” pero tenemos historial, lo sostengo por predict_hold_s
            if (now - current.get("_last_seen_ts", now)) <= stg["predict_hold_s"]:
                return current
            # caducó: escoger nuevo si hay, si no None
    if ac_list:
        ac_list[0]["_since"] = now
        return ac_list[0]
    return None

def predict_forward(lat, lon, alt_m, gs_mps, track_deg, dt_s):
    # Aproximación pequeña distancia
    d_km = (gs_mps * dt_s) / 1000.0
    brng = math.radians(track_deg)
    d_r = d_km * 1000.0 / R_EARTH
    φ1 = math.radians(lat)
    λ1 = math.radians(lon)
    φ2 = math.asin(math.sin(φ1)*math.cos(d_r) + math.cos(φ1)*math.sin(d_r)*math.cos(brng))
    λ2 = λ1 + math.atan2(math.sin(brng)*math.sin(d_r)*math.cos(φ1), math.cos(d_r)-math.sin(φ1)*math.sin(φ2))
    return math.degrees(φ2), (math.degrees(λ2)+540)%360-180, alt_m

# ====== Bucle de seguimiento ======
def tracker_loop():
    last_az, last_el = None, None
    last_hex = None
    last_sample_ts = None

    while True:
        try:
            with lock:
                src = state["adsb_src"]; site = dict(state["site"]); stg = dict(state["settings"])
                rot_host, rot_port = state["rot_host"], state["rot_port"]
                lock_hex = state["lock_hex"]
                off = dict(state["offset"])
                current = state["current_target"]

            data = read_aircrafts(src)
            raw_list = data.get("aircraft", []) if isinstance(data, dict) else []

            # Actualiza historial base
            now = time.time()
            for ac in raw_list:
                if "lat" in ac and "lon" in ac:
                    hexid = ac.get("hex","")
                    alt_ft = ac.get("alt_geom") or ac.get("alt_baro")
                    alt_m = feet_to_m(alt_ft) if alt_ft else history.get(hexid,{}).get("alt_m", None)
                    gs_mps = float(ac["gs"])*KT_TO_MPS if ac.get("gs") is not None else history.get(hexid,{}).get("gs_mps", None)
                    track_deg = ac.get("track") if ac.get("track") is not None else history.get(hexid,{}).get("track_deg", None)
                    history[hexid] = {"lat": ac["lat"], "lon": ac["lon"], "alt_m": alt_m,
                                      "gs_mps": gs_mps, "track_deg": track_deg, "ts": now}

            ac_list = compute_list(raw_list, site, stg)

            # Elegir/retener objetivo
            tgt = choose_target(ac_list, lock_hex, current, stg)

            # Si perdimos posición fresca de tgt, intentar predecir
            predicted = False
            if tgt is None and current:
                hx = current.get("hex")
                h = history.get(hx)
                if h and h.get("gs_mps") and h.get("track_deg"):
                    dt = now - h["ts"]
                    if dt <= stg["predict_hold_s"]:
                        plat, plon, palt = predict_forward(h["lat"], h["lon"], h["alt_m"] or 10000, h["gs_mps"], h["track_deg"], dt)
                        az, el, _ = az_el_from_latlon(plat, plon, palt, site["lat"], site["lon"], site["alt"])
                        tgt = dict(current)
                        tgt["az"], tgt["el"] = az, el
                        predicted = True

            # Publicar lista y target
            with lock:
                state["aircrafts"] = ac_list
                if tgt:
                    # sellar tiempos para dwell/predict
                    if (not current) or (current and current.get("hex") != tgt.get("hex")):
                        tgt["_since"] = now
                    tgt["_last_seen_ts"] = now
                state["current_target"] = tgt

            # Enviar al rotador
            if tgt:
                az, el = tgt["az"], tgt["el"]
                # Suavizado
                if last_az is not None and stg["alpha"] < 1.0:
                    az = (last_az + stg["alpha"] * wrap_az_delta(az, last_az)) % 360.0
                    el = last_el + stg["alpha"] * (el - last_el)
                # Offset de calibración
                az_cmd = (az + off["az"]) % 360.0
                el_cmd = el + off["el"]
                need = (last_az is None or
                        abs(wrap_az_delta(az_cmd, last_az)) > stg["deadband"] or
                        abs(el_cmd - last_el) > stg["deadband"])
                if need:
                    send_rotctld(rot_host, rot_port, az_cmd, el_cmd)
                    last_az, last_el = az_cmd, el_cmd
                    last_hex = tgt.get("hex"); last_sample_ts = now

            time.sleep(max(0.05, 1.0/float(stg["hz"])))
        except Exception as e:
            print("[TRACK] WARN:", e)
            time.sleep(0.5)

# ====== Web ======
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
input,select{padding:6px 8px;border:1px solid #ccc;border-radius:8px}
.num{width:90px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.trend-approach{background:#e9f7ef;}
.trend-recede{background:#fdecea;}
.trend-cross{background:#f5f5f5;}
@media (max-width:900px){td:nth-child(6),th:nth-child(6),td:nth-child(7),th:nth-child(7){display:none}}
</style>
</head>
<body>
<h1>ADS-B → ROT UI</h1>
<div class="panel">
  <div class="card">
    <div><b>Fuente</b>: <span id="src"></span></div>
    <div><b>Sitio</b>: <span id="site"></span></div>
    <div><b>rotctld</b>: <span id="rot"></span></div>
    <div><b>Modo</b>: <span id="mode"></span> — Perfil <select id="profile">
      <option>Suave</option><option selected>Normal</option><option>Agresivo</option>
    </select>
    </div>
    <div><b>Target</b>: <span id="target"></span> <button onclick="unlock()">Unlock</button></div>
  </div>
  <div class="card">
    <div><b>Parámetros</b></div>
    <div class="row">min_el <input id="min_el" class="num" type="number" step="0.1"></div>
    <div class="row">max_ground km <input id="max_ground" class="num" type="number" step="0.1"></div>
    <div class="row">deadband <input id="deadband" class="num" type="number" step="0.1"></div>
    <div class="row">alpha <input id="alpha" class="num" type="number" step="0.05" min="0" max="1"></div>
    <div class="row">Hz <input id="hz" class="num" type="number" step="0.1" min="0.1"></div>
    <div class="row">min_dwell_s <input id="min_dwell_s" class="num" type="number" step="0.5"></div>
    <div class="row">switch_margin_km <input id="switch_margin_km" class="num" type="number" step="0.1"></div>
    <div class="row">predict_hold_s <input id="predict_hold_s" class="num" type="number" step="0.5"></div>
    <div style="margin-top:6px"><button onclick="save()">Guardar</button></div>
  </div>
  <div class="card">
    <div><b>Calibración</b></div>
    <div id="rotpos">Rot —</div>
    <div id="err">Error —</div>
    <div>Offset AZ <span id="offaz">0.0</span>° — Offset EL <span id="offel">0.0</span>°</div>
    <div class="row" style="margin-top:6px">
      <button onclick="nudge('az',-1)">AZ −1°</button>
      <button onclick="nudge('az',-0.1)">AZ −0.1°</button>
      <button onclick="nudge('az',+0.1)">AZ +0.1°</button>
      <button onclick="nudge('az',+1)">AZ +1°</button>
    </div>
    <div class="row">
      <button onclick="nudge('el',-1)">EL −1°</button>
      <button onclick="nudge('el',-0.1)">EL −0.1°</button>
      <button onclick="nudge('el',+0.1)">EL +0.1°</button>
      <button onclick="nudge('el',+1)">EL +1°</button>
    </div>
    <div class="row">
      <button onclick="autoOffset()">Auto-offset</button>
      <button onclick="zeroOffsets()">Reset offsets</button>
    </div>
    <div class="row" style="margin-top:6px">
      <b>GOTO</b>
      AZ <input id="goto_az" class="num" type="number" step="0.1">
      EL <input id="goto_el" class="num" type="number" step="0.1">
      <button onclick="gotoSend()">Ir</button>
    </div>
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
      <th>Lock</th><th>HEX</th><th>Callsign</th><th>trend</th><th>gnd km</th><th>el°</th><th>az°</th><th>alt ft</th><th>age s</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  </div>
</div>

<script>
let filt="";
document.getElementById('filter').addEventListener('input', e=>{filt=e.target.value.toLowerCase()});

function applyProfile(name){
  const p = name || document.getElementById('profile').value;
  if(p==='Suave'){ hz.value=1.0; deadband.value=0.7; alpha.value=0.4; }
  else if(p==='Agresivo'){ hz.value=5.0; deadband.value=0.15; alpha.value=0.85; }
  else { hz.value=1.5; deadband.value=0.3; alpha.value=0.6; }
  save();
}

async function load(){
  const st = await fetch('/api/status').then(r=>r.json());
  document.getElementById('src').textContent = st.adsb_src;
  document.getElementById('site').textContent = `${st.site.lat.toFixed(5)}, ${st.site.lon.toFixed(5)} @ ${st.site.alt} m`;
  document.getElementById('rot').textContent = `${st.rot_host}:${st.rot_port}`;
  document.getElementById('mode').textContent = st.lock_hex ? ('LOCK '+st.lock_hex) : 'AUTO';
  document.getElementById('profile').value = st.profile || 'Normal';
  document.getElementById('target').textContent = st.current_target ? `${st.current_target.hex}  az ${st.current_target.az.toFixed(1)}  el ${st.current_target.el.toFixed(1)}` : '—';
  document.getElementById('offaz').textContent = (st.offset.az).toFixed(2);
  document.getElementById('offel').textContent = (st.offset.el).toFixed(2);

  const s = st.settings;
  ['min_el','max_ground','deadband','alpha','hz','min_dwell_s','switch_margin_km','predict_hold_s'].forEach(k=>{
    document.getElementById(k).value = s[k];
  });

  const ac = await fetch('/api/aircrafts').then(r=>r.json());
  const tb = document.getElementById('tbody'); tb.innerHTML='';
  let shown = 0;
  ac.forEach(a=>{
    const tag = (a.flight||"").toLowerCase() + " " + (a.hex||"");
    if(filt && !tag.includes(filt)) return;
    const tr = document.createElement('tr');
    let arrow = '↔'; let cls='trend-cross';
    if(a.trend==='approach'){arrow='⬆︎'; cls='trend-approach';}
    else if(a.trend==='recede'){arrow='⬇︎'; cls='trend-recede';}
    tr.className = cls;
    tr.innerHTML = `
      <td><button onclick="lock('${a.hex}')">Lock</button></td>
      <td>${a.hex||''}</td>
      <td>${a.flight||''}</td>
      <td>${arrow} ${(a.radial_mps||0).toFixed(0)} m/s</td>
      <td>${a.gnd_km.toFixed(1)}</td>
      <td>${a.el.toFixed(1)}</td>
      <td>${a.az.toFixed(1)}</td>
      <td>${a.alt_ft||''}</td>
      <td>${(a.seen||0).toFixed(1)}</td>`;
    tb.appendChild(tr);
    shown++;
  });
  document.getElementById('count').textContent = shown;

  const dg = await fetch('/api/diag').then(r=>r.json());
  document.getElementById('rotpos').textContent = dg.rot ? `Rot AZ ${dg.rot.az.toFixed(1)}  EL ${dg.rot.el.toFixed(1)}` : 'Rot —';
  document.getElementById('err').textContent = (dg.err) ? `Error AZ ${dg.err.az.toFixed(1)}  EL ${dg.err.el.toFixed(1)}` : 'Error —';
}

async function lock(hex){ await fetch('/api/lock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hex})}); }
async function unlock(){ await fetch('/api/unlock',{method:'POST'}); }
async function save(){
  const s = {
    min_el:+min_el.value, max_ground:+max_ground.value, deadband:+deadband.value, alpha:+alpha.value, hz:+hz.value,
    min_dwell_s:+min_dwell_s.value, switch_margin_km:+switch_margin_km.value, predict_hold_s:+predict_hold_s.value
  };
  await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
}
async function nudge(axis,delta){ await fetch('/api/nudge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({axis,delta})}); }
async function zeroOffsets(){ await fetch('/api/zero_offsets',{method:'POST'}); }
async function autoOffset(){ await fetch('/api/auto_offset',{method:'POST'}); }
async function gotoSend(){
  const az = parseFloat(document.getElementById('goto_az').value);
  const el = parseFloat(document.getElementById('goto_el').value);
  if(isFinite(az) && isFinite(el)){
    await fetch('/api/goto',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({az,el})});
  }
}
document.getElementById('profile').addEventListener('change', ()=>applyProfile());
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
            "offset": state["offset"],
            "lock_hex": state["lock_hex"],
            "current_target": state["current_target"],
            "profile": state["profile"],
        })

@app.get("/api/aircrafts")
def api_aircrafts():
    with lock:
        return jsonify(state["aircrafts"])

@app.get("/api/diag")
def api_diag():
    try:
        with lock:
            rot_host, rot_port = state["rot_host"], state["rot_port"]
            tgt = state["current_target"]; off = dict(state["offset"])
        rot_az, rot_el = read_rot_pos(rot_host, rot_port)
        resp = {"rot": {"az": rot_az, "el": rot_el}}
        if tgt:
            az_cmd = (tgt["az"] + off["az"]) % 360.0
            el_cmd = tgt["el"] + off["el"]
            err_az = wrap180(az_cmd - rot_az)
            err_el = (el_cmd - rot_el)
            resp.update({"target": {"az": tgt["az"], "el": tgt["el"]}, "cmd": {"az": az_cmd, "el": el_cmd}, "err": {"az": err_az, "el": err_el}})
        return jsonify(resp)
    except Exception as e:
        return jsonify({"rot": None, "error": str(e)})

@app.post("/api/lock")
def api_lock():
    data = request.get_json(force=True)
    hexid = (data.get("hex") or "").strip()
    with lock:
        state["lock_hex"] = hexid or None
        state["profile"] = "Normal"
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
        for k in ("min_el","max_ground","deadband","alpha","hz","min_dwell_s","switch_margin_km","predict_hold_s"):
            if k in data and data[k] is not None:
                s[k] = float(data[k])
    return jsonify({"ok": True, "settings": state["settings"]})

@app.post("/api/nudge")
def api_nudge():
    data = request.get_json(force=True)
    axis = data.get("axis"); delta = float(data.get("delta",0))
    with lock:
        if axis == "az":
            state["offset"]["az"] = (state["offset"]["az"] + delta) % 360.0
            if state["offset"]["az"] > 180: state["offset"]["az"] -= 360.0
        elif axis == "el":
            state["offset"]["el"] += delta
    return jsonify({"ok": True, "offset": state["offset"]})

@app.post("/api/zero_offsets")
def api_zero_off():
    with lock:
        state["offset"] = {"az": 0.0, "el": 0.0}
    return jsonify({"ok": True, "offset": state["offset"]})

@app.post("/api/auto_offset")
def api_auto_off():
    try:
        with lock:
            rot_host, rot_port = state["rot_host"], state["rot_port"]
            tgt = state["current_target"]; off = dict(state["offset"])
        if not tgt:
            return jsonify({"ok": False, "error": "No hay target actual"})
        rot_az, rot_el = read_rot_pos(rot_host, rot_port)
        az_err = wrap180(rot_az - tgt["az"])
        el_err = rot_el - tgt["el"]
        with lock:
            state["offset"]["az"] = wrap180(off["az"] + az_err)
            state["offset"]["el"] = off["el"] + el_err
        return jsonify({"ok": True, "offset": state["offset"], "measured": {"rot_az": rot_az, "rot_el": rot_el}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.post("/api/goto")
def api_goto():
    data = request.get_json(force=True)
    az = float(data.get("az")); el = float(data.get("el"))
    with lock:
        rot_host, rot_port = state["rot_host"], state["rot_port"]
    try:
        send_rotctld(rot_host, rot_port, az, el)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---- /metrics para Prometheus/Grafana ----
@app.get("/metrics")
def metrics():
    with lock:
        t = state["current_target"]
        s = state["settings"]
    lines = []
    lines.append("# HELP tracker_target_present 1 si hay target actual")
    lines.append("# TYPE tracker_target_present gauge")
    lines.append(f"tracker_target_present {1 if t else 0}")
    if t:
        lines.append("# TYPE tracker_target_az gauge")
        lines.append(f"tracker_target_az {t['az']:.3f}")
        lines.append("# TYPE tracker_target_el gauge")
        lines.append(f"tracker_target_el {t['el']:.3f}")
        lines.append("# TYPE tracker_target_gnd_km gauge")
        lines.append(f"tracker_target_gnd_km {t['gnd_km']:.3f}")
        lines.append("# TYPE tracker_target_radial_mps gauge")
        lines.append(f"tracker_target_radial_mps {t.get('radial_mps',0.0):.3f}")
    lines.append("# TYPE tracker_settings_hz gauge")
    lines.append(f"tracker_settings_hz {s['hz']}")
    return Response("\n".join(lines)+"\n", mimetype="text/plain; version=0.0.4")

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
    ap.add_argument("--hz", type=float, default=1.5)
    ap.add_argument("--min-el", type=float, default=5.0)
    ap.add_argument("--max-ground", type=float, default=10.0)
    ap.add_argument("--deadband", type=float, default=0.3)
    ap.add_argument("--alpha", type=float, default=0.6)
    ap.add_argument("--min-dwell-s", type=float, default=8.0)
    ap.add_argument("--switch-margin-km", type=float, default=3.0)
    ap.add_argument("--predict-hold-s", type=float, default=8.0)
    args = ap.parse_args()

    with lock:
        state["adsb_src"] = args.adsb
        state["rot_host"] = args.rot_host
        state["rot_port"] = args.rot_port
        state["site"] = {"lat": args.site_lat, "lon": args.site_lon, "alt": args.site_alt}
        state["settings"] = {
            "hz": args.hz, "min_el": args.min_el, "max_ground": args.max_ground,
            "deadband": args.deadband, "alpha": args.alpha,
            "min_dwell_s": args.min_dwell_s, "switch_margin_km": args.switch_margin_km,
            "predict_hold_s": args.predict_hold_s
        }

    t = threading.Thread(target=tracker_loop, daemon=True)
    t.start()
    app.run(host=args.bind, port=args.port, threaded=True)

if __name__ == "__main__":
    main()
