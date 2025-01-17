import cv2
import numpy as np

# Function to detect the brightest spot in the frame
def detect_light_point(frame):
    # Convert to grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Use a GaussianBlur to reduce noise and improve the detection accuracy
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    
    # Find the brightest spot in the image
    (minVal, maxVal, minLoc, maxLoc) = cv2.minMaxLoc(blurred)
    
    # Draw a circle around the brightest spot
    cv2.circle(frame, maxLoc, 20, (0, 255, 255), 2)
    
    return frame, maxLoc

# Initialize the webcam (Elgato USB cam link)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open video stream")
    exit()

while True:
    # Read a frame from the webcam
    ret, frame = cap.read()
    
    if not ret:
        print("Error: Could not read frame")
        break
    
    # Detect the light point in the frame
    output_frame, light_point = detect_light_point(frame)
    
    # Print the frame resolution
    print(f"Frame Resolution: {frame.shape}")
    
    # Display the resulting frame
    # cv2.imshow('Light Point Detection', output_frame)
    
    # Print the coordinates of the light point
    print(f"Light Point Coordinates: {light_point}")
    
    # Press 'q' to quit the video stream
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release the webcam and close windows
cap.release()
cv2.destroyAllWindows()
