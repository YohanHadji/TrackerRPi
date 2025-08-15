import time
from threading import Condition, Thread
from picamera2 import Picamera2
from libcamera import Transform

# === Instancia global única ===
picam2 = Picamera2()


# === Clase para servir frames de forma asíncrona ===
class FrameServer:
    def __init__(self, picam2, stream='main'):
        self._picam2 = picam2
        self._stream = stream
        self._array = None
        self._timestamp = None
        self._condition = Condition()
        self._running = True
        self._count = 0
        self._thread = Thread(target=self._thread_func, daemon=True)

    @property
    def count(self):
        return self._count

    def start(self):
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join()

    def _thread_func(self):
        while self._running:
            request = self._picam2.capture_request()
            array = request.make_array(self._stream)
            metadata = request.get_metadata()
            request.release()

            self._count += 1
            with self._condition:
                self._array = array
                self._timestamp = metadata['SensorTimestamp']
                self._condition.notify_all()

    def wait_for_frame(self, previous=None):
        with self._condition:
            if previous is not None and self._array is not previous:
                return self._array, self._timestamp
            while True:
                self._condition.wait()
                if self._array is not previous:
                    return self._array, self._timestamp


# === Calculadora de promedio móvil para FPS ===
class MovingAverageCalculator:
    def __init__(self, window_size):
        self.window_size = window_size
        self.window = []
        self.cumulative_sum = 0

    def calculate_moving_average(self, new_value):
        self.window.append(new_value)
        self.cumulative_sum += new_value

        if len(self.window) == self.window_size:
            average = self.cumulative_sum / self.window_size
            self.cumulative_sum -= self.window[0]
            self.window.pop(0)
            return average
        return None


window_size = 50
fpsCalculator = MovingAverageCalculator(window_size)
fpsDeviationCalculator = MovingAverageCalculator(window_size)
fpsAverage = 0
fpsDeviation = 0
prev_time_sec = 0


# === Inicialización principal de cámara ===
def camInit(framerate, vFlipSet, hFlipSet):
    global picam2

    camera_config = picam2.create_video_configuration(
        main={"format": "BGR888", "size": (800, 606)},
        raw={"format": "SRGGB10", "size": (800, 606)},
        transform=Transform(hflip=hFlipSet, vflip=vFlipSet)
    )
    picam2.configure(camera_config)

    try:
        picam2.set_controls({"FrameRate": framerate})
    except RuntimeError as e:
        print(f"⚠️ No se pudo fijar FrameRate: {e}")

    picam2.set_controls({"AwbEnable": True})
    picam2.start()


# === Inicialización secundaria para 180° ===
def camInit180(framerate):
    global picam2

    camera_config = picam2.create_video_configuration(
        main={"format": "BGR888", "size": (2028, 1520)},
        raw={"format": "SRGGB12", "size": (2028, 1520)},
        lores={"size": (2028, 1520), "format": "YUV420"}
    )
    picam2.configure(camera_config)

    try:
        picam2.set_controls({"FrameRate": framerate})
    except RuntimeError as e:
        print(f"⚠️ No se pudo fijar FrameRate: {e}")

    picam2.start()


# === Obtener frame principal ===
def getFrame():
    request = picam2.capture_request()
    frame = request.make_array("main")
    metadata = request.get_metadata()
    request.release()
    return frame, metadata['SensorTimestamp']


# === Obtener frame de baja resolución ===
def getFrameLores():
    request = picam2.capture_request()
    frame = request.make_array("lores")
    metadata = request.get_metadata()
    request.release()
    return frame, metadata['SensorTimestamp']


# === Mostrar FPS calculado ===
def printFps():
    global prev_time_sec, fpsCalculator, fpsDeviationCalculator, fpsAverage, fpsDeviation

    current_time_sec = time.time()
    if prev_time_sec != 0:
        fps = 1 / (current_time_sec - prev_time_sec)
        fpsAverage = fpsCalculator.calculate_moving_average(fps)
        if fpsAverage is not None:
            fpsDeviation = fpsDeviationCalculator.calculate_moving_average(abs(fpsAverage - fps))
            if fpsDeviation is not None:
                print(f"FPS promedio: {round(fpsAverage)}, desviación: {round(fpsDeviation)}")

    prev_time_sec = current_time_sec


# === Ajustar parámetros manuales ===
def setCameraSettings(gain, exposureTime):
    awbAuto = True
    try:
        picam2.set_controls({
            "AnalogueGain": gain,
            "ExposureTime": exposureTime,
            "AwbEnable": awbAuto
        })
    except RuntimeError as e:
        print(f"⚠️ Error al aplicar ajustes de cámara: {e}")
