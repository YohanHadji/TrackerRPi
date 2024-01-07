from picamera2 import Picamera2
import time

picam2 = Picamera2()

# Moving average calculator for fps measurement
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

            # Subtract the oldest value to prepare for the next iteration
            self.cumulative_sum -= self.window[0]
            self.window.pop(0)

            return average

        return None  # Return None until the window is filled

window_size = 500
fpsCalculator = MovingAverageCalculator(window_size)
fpsDeviationCalculator = MovingAverageCalculator(window_size)
fpsAverage = 0
fpsDeviation = 0
prev_time_sec = 0

def camInit(framerate):
    global picam2
    # Camera Init
    camera_config = picam2.create_video_configuration(main={"format": "BGR888", "size": (800, 606)}, raw={"format": "SRGGB10", "size": (1332, 990)})
    picam2.configure(camera_config)
    picam2.set_controls({"FrameRate": framerate})
    picam2.start()

def getFrame():
    global picam2
    # Get a frame with metadata
    request = picam2.capture_request()
    frame = request.make_array("main")
    metadata = request.get_metadata()
    request.release()
    sensorTimeStamp = metadata['SensorTimestamp']
    return frame, sensorTimeStamp

def printFps():
    global prev_time_sec, fpsCalculator, fpsDeviationCalculator, fpsAverage, fpsDeviation
    # Display the frame rate
    current_time_sec = time.time()
    if prev_time_sec != 0:
        fps = 1 / (current_time_sec - prev_time_sec)
        fpsAverage = fpsCalculator.calculate_moving_average(fps)
        if fpsAverage is not None:
            fpsDeviation = fpsDeviationCalculator.calculate_moving_average(abs(fpsAverage-fps))
            if fpsDeviation is not None:
                print(round(fpsAverage), round(fpsDeviation))

    prev_time_sec = current_time_sec

def setCameraSettings(gain, exposureTime):
    global picam2
    picam2.set_controls({"AnalogGain": gain, "ExposureTime": exposureTime})