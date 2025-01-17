import logging
from flask import Flask, jsonify, request, render_template
from seabreeze.spectrometers import Spectrometer, list_devices
import atexit
import threading
import time
import os
from datetime import datetime

# Configuración de logging
logging.basicConfig(
    filename="web_spectro.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s]: %(message)s",
)

# Inicializa la aplicación Flask
app = Flask(__name__)

# Variables globales
spec = None
capture_thread = None
capture_running = False
output_dir = "/home/pi/spectrometer_data"
file_lock = threading.Lock()
current_integration_time = 100000  # Tiempo de integración inicial en µs

# Verifica y crea el directorio de salida si no existe
if not os.path.exists(output_dir):
    try:
        os.makedirs(output_dir)
        logging.info(f"Directorio creado: {output_dir}")
    except Exception as e:
        logging.error(f"Error al crear el directorio {output_dir}: {e}")

def initialize_spectrometer(retries=5, delay=2):
    """Intenta inicializar el espectrómetro con múltiples reintentos."""
    global spec, current_integration_time
    logging.info("Inicializando espectrómetro...")
    for attempt in range(retries):
        try:
            devices = list_devices()
            if not devices:
                logging.warning(f"No se encontraron espectrómetros conectados (intento {attempt + 1}/{retries}).")
                time.sleep(delay)
                continue
            spec = Spectrometer.from_first_available()
            spec.integration_time_micros(current_integration_time)  # Configura el tiempo de integración inicial
            logging.info(f"Espectrómetro inicializado: {spec.serial_number} con tiempo de integración predeterminado: {current_integration_time} µs")
            return
        except Exception as e:
            logging.error(f"Error al inicializar el espectrómetro (intento {attempt + 1}/{retries}): {e}")
            time.sleep(delay)
    logging.critical("No se pudo inicializar el espectrómetro tras múltiples intentos.")
    raise Exception("No se encontraron espectrómetros conectados tras varios intentos.")

@atexit.register
def close_spectrometer():
    """Cierra el espectrómetro al salir."""
    global spec
    if spec:
        spec.close()
        logging.info("Espectrómetro cerrado correctamente al salir.")

@app.route("/set_integration_time", methods=["POST"])
def set_integration_time_endpoint():
    """Establece el tiempo de integración dinámicamente."""
    global spec, current_integration_time
    try:
        if not spec:
            return jsonify({"error": "Espectrómetro no inicializado"}), 500

        data = request.json
        integration_time = int(data.get("integration_time", 0))
        if integration_time <= 0:
            return jsonify({"error": "El tiempo de integración debe ser mayor que 0"}), 400

        # Actualiza el tiempo de integración en el espectrómetro
        spec.integration_time_micros(integration_time)
        current_integration_time = integration_time  # Actualiza la variable global
        logging.info(f"Tiempo de integración actualizado dinámicamente: {integration_time} µs")
        return jsonify({"success": True, "integration_time": integration_time})
    except Exception as e:
        logging.error(f"Error al establecer el tiempo de integración: {e}")
        return jsonify({"error": str(e)}), 500

def save_spectrum_to_file():
    """Guarda datos del espectrómetro en un archivo."""
    global spec, capture_running, output_dir, current_integration_time
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = os.path.join(output_dir, f"spectrum_data_{timestamp}.txt")
    logging.info(f"Intentando guardar datos en el archivo: {output_file}")

    try:
        # Verifica permisos de escritura
        if not os.access(output_dir, os.W_OK):
            raise PermissionError(f"No se puede escribir en el directorio: {output_dir}")

        # Escribe encabezados en el archivo
        with open(output_file, "w") as file:
            file.write(f"Modelo: {spec.model}\n")
            file.write(f"Número de Serie: {spec.serial_number}\n")
            file.write(f"Tiempo de Integración Actual: {current_integration_time} µs\n")
            file.write("Longitud de Onda (nm), Intensidad\n")
        logging.info(f"Archivo creado exitosamente: {output_file}")

        # Bucle de captura
        while capture_running:
            try:
                wavelengths = spec.wavelengths()
                intensities = spec.intensities()

                with file_lock, open(output_file, "a") as file:
                    for w, i in zip(wavelengths, intensities):
                        file.write(f"{w},{i}\n")
                    file.write("\n")
                logging.info(f"Datos escritos en {output_file}: {len(wavelengths)} puntos")
                time.sleep(1)  # Intervalo de captura
            except Exception as e:
                logging.error(f"Error durante la captura de datos: {e}")
    except Exception as e:
        logging.error(f"Error al iniciar la escritura de datos: {e}")

@app.route("/start_capture", methods=["POST"])
def start_capture():
    """Inicia la captura automática de datos."""
    global capture_thread, capture_running
    logging.info("Solicitud recibida: Iniciar Captura Automática")
    try:
        if capture_running:
            logging.warning("La captura ya está en ejecución.")
            return jsonify({"error": "La captura ya está en ejecución."}), 400

        logging.info("Iniciando captura automática...")
        capture_running = True
        capture_thread = threading.Thread(target=save_spectrum_to_file)
        capture_thread.start()
        logging.info("Hilo de captura iniciado.")
        return jsonify({"success": True, "message": "Captura automática iniciada."})
    except Exception as e:
        logging.error(f"Error al iniciar la captura: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/stop_capture", methods=["POST"])
def stop_capture():
    """Detiene la captura automática de datos."""
    global capture_running
    logging.info("Solicitud recibida: Detener Captura Automática")
    try:
        if not capture_running:
            logging.warning("La captura no está en ejecución.")
            return jsonify({"error": "La captura no está en ejecución."}), 400

        logging.info("Deteniendo captura automática...")
        capture_running = False
        capture_thread.join()
        logging.info("Hilo de captura detenido.")
        return jsonify({"success": True, "message": "Captura automática detenida."})
    except Exception as e:
        logging.error(f"Error al detener la captura: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return render_template("spectro_index.html")

@app.route("/spectrum", methods=["GET"])
def get_spectrum_endpoint():
    """Obtiene el espectro en tiempo real."""
    global spec
    try:
        if not spec:
            return jsonify({"error": "Espectrómetro no inicializado"}), 500

        wavelengths = spec.wavelengths()
        intensities = spec.intensities()

        return jsonify({
            "wavelengths": wavelengths.tolist(),
            "intensities": intensities.tolist(),
        })
    except Exception as e:
        logging.error(f"Error al obtener el espectro: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    try:
        logging.info(f"Usuario actual: {os.getlogin()}")
        initialize_spectrometer()
        app.run(host="0.0.0.0", port=5000, debug=False)
    except Exception as e:
        logging.critical(f"Error crítico al iniciar el servidor: {e}")
