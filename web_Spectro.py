from flask import Flask, jsonify, request, render_template
from seabreeze.spectrometers import Spectrometer

app = Flask(__name__)

# Inicializar el espectrómetro
spec = Spectrometer.from_first_available()
spec.integration_time_micros(200000)  # Tiempo de exposición inicial (200ms)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/spectrum", methods=["GET"])
def get_spectrum():
    wavelengths = spec.wavelengths().tolist()
    intensities = spec.intensities().tolist()
    return jsonify({"wavelengths": wavelengths, "intensities": intensities})

@app.route("/set_integration_time", methods=["POST"])
def set_integration_time():
    data = request.json
    try:
        integration_time = int(data["integration_time"])
        spec.integration_time_micros(integration_time)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
