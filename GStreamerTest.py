import cv2
import gi
import http.server
import socketserver
import threading
from io import BytesIO
from picamera2.array import PiRGBArray
from picamera2 import PiCamera2

# Initialize GStreamer
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# Set up the PiCamera
camera = PiCamera2()
camera.resolution = (640, 480)
raw_capture = PiRGBArray(camera, size=(640, 480))
stream = camera.capture_continuous(raw_capture, format="bgr", use_video_port=True)

# GStreamer pipeline
pipeline_str = (
    'appsrc name=source ! videoconvert ! '
    'video/x-raw,format=(string)BGR ! '
    'jpegenc ! rtpjpegpay ! '
    'udpsink host=127.0.0.1 port=5000'
)
pipeline = Gst.parse_launch(pipeline_str)
appsrc = pipeline.get_by_name('source')

# Start the GStreamer pipeline
pipeline.set_state(Gst.State.PLAYING)

# HTTP server handler
class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(open('index.html', 'rb').read())
        else:
            super().do_GET()

# Start the HTTP server in a separate thread
http_thread = threading.Thread(target=lambda: socketserver.TCPServer(('0.0.0.0', 8000), MyHandler).serve_forever())
http_thread.daemon = True
http_thread.start()

try:
    for frame in stream:
        image = frame.array

        # Process the frame (you can add your processing logic here)

        # Convert the frame to GStreamer format
        data = image.tobytes()
        buffer = Gst.Buffer.new_wrapped(data)

        # Push the buffer to the GStreamer pipeline
        appsrc.emit("push-buffer", buffer)

        # Clear the stream in preparation for the next frame
        raw_capture.truncate(0)

except KeyboardInterrupt:
    pass

finally:
    # Stop the GStreamer pipeline
    pipeline.set_state(Gst.State.NULL)