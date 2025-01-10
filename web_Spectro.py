from flask import Flask, jsonify
from seabreeze.spectrometers import Spectrometer, SeaBreezeError

app = Flask(__name__)

@app.route('/spectrum')
def get_spectrum():
    spec = None
    try:
        # Intentar conectar con el espectrómetro
        spec = Spectrometer.from_first_available()
        wavelengths = spec.wavelengths().tolist()
        intensities = spec.intensities().tolist()
        return jsonify({"wavelengths": wavelengths, "intensities": intensities})
    
    except SeaBreezeError as e:
        # Manejo específico de errores del espectrómetro
        return jsonify({"error": f"SeaBreezeError: {str(e)}"}), 500
    
    except Exception as e:
        # Manejo genérico de errores
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
    
    finally:
        # Cerrar conexión si el espectrómetro fue inicializado
        if spec is not None:
            try:
                spec.close()
            except SeaBreezeError as e:
                # Loggear errores de cierre, si ocurren
                print(f"Error closing spectrometer: {str(e)}")
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
