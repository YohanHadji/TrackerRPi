from picamera2 import Picamera2
import time

picam2 = Picamera2()

import time
from threading import Condition, Thread

from picamera2 import Picamera2


class FrameServer:
    def __init__(self, picam2, stream='main'):
        """A simple class that can serve up frames from one of the Picamera2's configured streams to multiple other threads.

        Pass in the Picamera2 object and the name of the stream for which you want
        to serve up frames.
        """
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
        """A count of the number of frames received."""
        return self._count

    def start(self):
        """To start the FrameServer, you will also need to start the Picamera2 object."""
        self._thread.start()

    def stop(self):
        """To stop the FrameServer

        First stop any client threads (that might be
        blocked in wait_for_frame), then call this stop method. Don't stop the
        Picamera2 object until the FrameServer has been stopped.
        """
        self._running = False
        self._thread.join()

    def _thread_func(self):
        while self._running:
            # array = self._picam2.capture_array(self._stream)
            request = self._picam2.capture_request()
            array = request.make_array("main")
            metadata = request.get_metadata()
            request.release()

            self._count += 1
            with self._condition:
                self._array = array
                self._timestamp = metadata['SensorTimestamp']
                self._condition.notify_all()

    def wait_for_frame(self, previous=None):
        """You may optionally pass in the previous frame that you got last time you called this function.

        This will guarantee that you don't get duplicate frames
        returned in the event of spurious wake-ups, and it may even return more
        quickly in the case where a new frame has already arrived.
        """
        with self._condition:
            if previous is not None and self._array is not previous:
                return self._array, self._timestamp
            while True:
                self._condition.wait()
                if self._array is not previous:
                    return self._array, self._timestamp


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

window_size = 50
fpsCalculator = MovingAverageCalculator(window_size)
fpsDeviationCalculator = MovingAverageCalculator(window_size)
fpsAverage = 0
fpsDeviation = 0
prev_time_sec = 0

def camInit(framerate):
    global picam2
    # Camera Init
    camera_config = picam2.create_video_configuration(main={"format": "BGR888", "size": (800, 606)}, raw={"format": "SRGGB10", "size": (800, 606)})
    # Rotate image by 90 deg left
    camera_config['rotation'] = 90
    # Flip image vertically
    camera_config['vflip'] = True
    # Flip image horizontally
    camera_config['hflip'] = True
    picam2.configure(camera_config)
    picam2.set_controls({"FrameRate": framerate})
    picam2.start()

def camInit180(framerate):
    global picam2
    #config = picam2.create_video_configuration(raw={'format': 'SRGGB10', 'size': (1332, 990)})
    camera_config = picam2.create_video_configuration(main={"format": "BGR888", "size": (2028, 1520)}, 
                                                      raw={"format": "SRGGB12", "size": (2028, 1520)},
                                                      lores={"size": (2028, 1520), "format": "YUV420"})
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

def getFrameLores():
    global picam2
    # Get a frame with metadata
    request = picam2.capture_request()
    frame = request.make_array("lores")
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
    picam2.set_controls({"AnalogueGain": gain, "ExposureTime": exposureTime})