from flask import Flask, jsonify, request, render_template
from seabreeze.spectrometers import Spectrometer, list_devices
import atexit

# Inicializa la aplicación Flask
app = Flask(__name__)

# Variable global para mantener una referencia al espectrómetro
spec = None

def initialize_spectrometer():
    """Inicializa el espectrómetro al arrancar el servidor."""
    global spec
    devices = list_devices()
    print(f"Dispositivos detectados: {devices}")  # Depuración
    if not devices:
        print("Intentando reconectar espectrómetro...")  # Depuración
        devices = list_devices()  # Segundo intento
        if not devices:
            raise Exception("No se encontraron espectrómetros conectados.")
    spec = Spectrometer.from_first_available()
    print(f"Espectrómetro inicializado: {spec.serial_number}")  # Depuración

# Cerrar el espectrómetro al salir
@atexit.register
def close_spectrometer():
    global spec
    if spec:
        spec.close()
        print("Espectrómetro cerrado correctamente al salir.")  # Depuración

@app.route("/")
def index():
    """Renderiza la página principal."""
    return render_template("spectro_index.html")

@app.route("/set_integration_time", methods=["POST"])
def set_integration_time_endpoint():
    """Establece el tiempo de integración del espectrómetro."""
    global spec
    try:
        if not spec:
            return jsonify({"error": "Espectrómetro no inicializado"}), 500

        data = request.json
        integration_time = int(data.get("integration_time", 0))
        print(f"Tiempo de integración recibido: {integration_time} µs")  # Depuración

        if integration_time <= 0:
            print("El tiempo de integración es inválido.")  # Depuración
            return jsonify({"error": "El tiempo de integración debe ser mayor que 0"}), 400

        spec.integration_time_micros(integration_time)
        print(f"Tiempo de integración establecido a {integration_time} µs.")  # Depuración
        return jsonify({"success": True, "integration_time": integration_time})
    except Exception as e:
        print(f"Error al establecer el tiempo de integración: {e}")  # Depuración
        return jsonify({"error": str(e)}), 500

@app.route("/spectrum", methods=["GET"])
def get_spectrum_endpoint():
    """Obtiene los datos de espectro (longitudes de onda e intensidades)."""
    global spec
    try:
        if not spec:
            return jsonify({"error": "Espectrómetro no inicializado"}), 500

        wavelengths = spec.wavelengths().tolist()
        intensities = spec.intensities().tolist()

        print(f"Datos recuperados: {len(wavelengths)} puntos")  # Depuración
        return jsonify({"wavelengths": wavelengths, "intensities": intensities})
    except Exception as e:
        print(f"Error al obtener los datos del espectro: {e}")  # Depuración
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    try:
        initialize_spectrometer()
        app.run(host="0.0.0.0", port=5000, debug=False)  # Cambiado a debug=False
    except Exception as e:
        print(f"Error crítico al iniciar el servidor: {e}")
