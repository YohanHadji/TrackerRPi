import picamera
from time import sleep

# Initialize the camera
camera = picamera.PiCamera()

try:
    # Set camera resolution (optional)
    camera.resolution = (640, 480)
    
    # Start preview (optional)
    camera.start_preview()
    
    # Capture frames continuously
    for i in range(10):  # Capture 10 frames
        # Capture a frame
        camera.capture(f'frame_{i}.jpg')
        
        # Wait for a moment (optional)
        sleep(1)
finally:
    # Clean up resources
    camera.stop_preview()
    camera.close()
