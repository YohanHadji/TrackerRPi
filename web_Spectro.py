from flask import Flask, jsonify, request,  render_template
from seabreeze.spectrometers import Spectrometer

app = Flask(__name__)
@app.route("/")
def index():
    return render_template("spectro_index.html")

@app.route("/spectrum", methods=["GET"])
def get_spectrum():
    try:
        spec = Spectrometer.from_first_available()
        wavelengths = spec.wavelengths().tolist()
        intensities = spec.intensities().tolist()
        return jsonify({"wavelengths": wavelengths, "intensities": intensities})
    finally:
        spec.close()

@app.route("/set_integration_time", methods=["POST"])
def set_integration_time():
    try:
        data = request.json
        integration_time = int(data["integration_time"])
        spec = Spectrometer.from_first_available()
        spec.integration_time_micros(integration_time)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    finally:
        spec.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
