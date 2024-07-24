import cv2
import numpy as np
import random
import string

all_light_points = []
# resolution = (1304, 976)
# resolution = (800, 606)
#resolution = (1304, 976)
currentlyLocked = False
lockedName = "ABCD"

lockRadius = 100
idRadius = 10
lightLifetime = 200
lightThreshold = 200


class LightPoint:
    def __init__(self, name, isVisible, x, y, age):
        self.name = str(name)
        self.isVisible = bool(isVisible)  # Ensure boolean type
        self.x = int(x)  # Ensure integer type
        self.y = int(y)  # Ensure integer type
        self.age = int(age)

# Create an array of structures without specifying values
LightPointArray = [LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0) for _ in range(10)]

def obtain_top_contours(b_frame, n=10):
    """
    Obtain the top n x and y coordinates of the brightest contours.
    When none is found, it returns a list of (-1, -1).
    """
    try:
        contours, _h = cv2.findContours(b_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    except ValueError:
        _, contours, _h = cv2.findContours(b_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return [(-1, -1)] * n

    contour_brightness = []

    for blob in contours:
        M = cv2.moments(blob)
        if M['m00'] != 0:
            cx, cy = int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
            contour_radius = cv2.minEnclosingCircle(blob)[1]
            if contour_radius > 5:
                contour_brightness.append(((cx, cy), cv2.contourArea(blob)))

    # Sort contours based on brightness
    sorted_contours = sorted(contour_brightness, key=lambda x: x[1], reverse=True)

    # Return the top n contours
    top_contours = [point for point, _ in sorted_contours[:n]]

    return top_contours


def is_point_close_with_motion_estimation(x1, y1, x2, y2, speed_x1, speed_y1, acceleration_x1, acceleration_y1, timestamp1, timestamp2, threshold):
    """
    Check if two points are close to each other based on the estimated position.
    """
    delta_t_nanosecond = timestamp2 - timestamp1
    delta_t = delta_t_nanosecond / 1e9

    # Estimate the next position based on the last known position, speed, and acceleration for both x and y
    estimated_x = x1 + speed_x1 * delta_t + 0.5 * acceleration_x1 * delta_t/1e9**2
    estimated_y = y1 + speed_y1 * delta_t + 0.5 * acceleration_y1 * delta_t/1e9**2

    # Check if the new position is close to the estimated position
    position_close = abs(x2 - estimated_x) <= threshold and abs(y2 - estimated_y) <= threshold

    return position_close

def map_range(x, in_min, in_max, out_min, out_max):
  return (x - in_min) * (out_max - out_min) // (in_max - in_min) + out_min

def constrain(val, min_val, max_val):
    return min(max_val, max(min_val, val))

def estimate_position(last_position, speed_x, speed_y, acceleration_x, acceleration_y, last_timestamp, current_timestamp):
    """
    Estimate the current position based on the last known position, speed, and acceleration for both x and y.
    """
    delta_t_nanosecond = current_timestamp - last_timestamp
    delta_t = delta_t_nanosecond / 1e9

    estimated_x = last_position[0] + speed_x * delta_t + 0.5 * acceleration_x * delta_t**2
    estimated_y = last_position[1] + speed_y * delta_t + 0.5 * acceleration_y * delta_t**2

    return estimated_x, estimated_y

def calculate_speed_and_acceleration(last_position, current_position, last_timestamp, current_timestamp):
    """
    Calculate speed and acceleration given the last and current positions and timestamps for each coordinate (x and y).
    """
    if last_position is None or last_timestamp is None:
        return 0, 0, 0, 0  # Initial values for speed and acceleration

    delta_t_nanosecond = current_timestamp - last_timestamp
    delta_t = delta_t_nanosecond / 1e9
    if delta_t == 0:
        return 0, 0, 0, 0  # Avoid division by zero

    delta_x = current_position[0] - last_position[0]
    delta_y = current_position[1] - last_position[1]

    # Calculate speed and acceleration for both x and y coordinates
    speed_x = delta_x / delta_t
    speed_y = delta_y / delta_t

    acceleration_x = speed_x / delta_t
    acceleration_y = speed_y / delta_t

    return speed_x, speed_y, acceleration_x, acceleration_y

def process_and_store_light_points(new_points, sensorTimeStamp):
    global all_light_points

    # Get the current timestamp
    current_time = sensorTimeStamp
    age = 0

    # Process new points
    for new_x, new_y in new_points:
        point_found = False

        for i, (existing_name, existing_firstSeen, existing_x, existing_y, age, existing_timestamp, existing_speed_x, existing_speed_y, existing_acceleration_x, existing_acceleration_Y)in enumerate(all_light_points):
            if is_point_close_with_motion_estimation(existing_x, existing_y, new_x, new_y, existing_speed_x, existing_speed_y, existing_acceleration_x, existing_acceleration_Y, existing_timestamp, current_time, idRadius):
                # Replace old point values with the most recent and compute new acceleration and speed
                speed_x, speed_y, acceleration_x, acceleration_y = calculate_speed_and_acceleration((existing_x, existing_y), (new_x, new_y), existing_timestamp, current_time)
                #  print("Point %d updated: (%d, %d, %f, %f, %f, %f)" % (i + 1, new_x, new_y, speed_x, speed_y, acceleration_x, acceleration_y))
                all_light_points[i] = (existing_name, existing_firstSeen, new_x, new_y, age, current_time, speed_x, speed_y, acceleration_x, acceleration_y)
                point_found = True
                break

        if not point_found:
            # Add new point to the list with acceleration and speed = 0 for both x and y
            name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            # Make sure the name doesn't already exist in the current list:
            while name in [existing_name for existing_name, _, _, _, _, _, _, _, _, _ in all_light_points]:
                name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))

            all_light_points.append((name, current_time, new_x, new_y, age, current_time, 0, 0, 0, 0))

    all_light_points = [(name, firstSeen, x, y, age, timestamp, speed_x, speed_y, acceleration_x, acceleration_y) for name, firstSeen, x, y, age, timestamp, speed_x, speed_y, acceleration_x, acceleration_y in all_light_points if current_time - timestamp <= lightLifetime*1e6]
    return all_light_points

def detect(frame, sensorTimeStamp):
    # Convert to grayscale and then to binary
    try: 
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Method 1: Apply a simple threshold
        _dummy, b_frame = cv2.threshold(gray_frame,lightThreshold, 255, cv2.THRESH_BINARY)

        # Method 2: Apply adaptive threshold
        # # Apply morphological dilation
        # kernel = np.ones((3, 3), np.uint8)
        # dilated = cv2.dilate(gray_frame, kernel)

        # # Compute the difference between the original and dilated image
        # diff = cv2.absdiff(dilated, gray_frame)

        # # Optionally, you can further threshold the difference image
        # _, b_frame = cv2.threshold(diff, lightThreshold, 255, cv2.THRESH_BINARY)

        # Method 3: Apply adaptive threshold
        # Compute the gradient magnitude using Sobel operators
        # gradient_x = cv2.Sobel(gray_frame, cv2.CV_64F, 1, 0, ksize=3)
        # gradient_y = cv2.Sobel(gray_frame, cv2.CV_64F, 0, 1, ksize=3)
        # gradient_magnitude = np.sqrt(gradient_x**2 + gradient_y**2)

        # # Normalize gradient magnitude to [0, 255]
        # gradient_magnitude_normalized = cv2.normalize(gradient_magnitude, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

        # # Threshold the gradient magnitude image
        # _, thresh = cv2.threshold(gradient_magnitude_normalized, lightThreshold, 255, cv2.THRESH_BINARY)

        # # Perform non-maximum suppression
        # b_frame = cv2.dilate(thresh, None)

        result = obtain_top_contours(b_frame, 10)
        all_light_points = process_and_store_light_points(result, sensorTimeStamp)
        return all_light_points
    
    except cv2.error:
        print("Error: Could not convert frame to grayscale")
        return []
    

def getLockedPoint(all_light_points, resolution, isButtonPressed=False,swLeft=False,swRight=False,swUp=False,swDown=False):
    global currentlyLocked, lockedName, lockRadius

    if (not currentlyLocked):
        for i, (name, firstSeen, x, y, _, _, _, _, _, _) in enumerate(all_light_points):
            if (abs(x - resolution[0]/2) <= lockRadius and abs(y - resolution[1]/2) <= lockRadius):
                lockedName = name
                currentlyLocked = True
                break
    else: 
        if (not lockedName in [name for name, firstSeen, _, _, _, _, _, _, _, _ in all_light_points]):
            currentlyLocked = False
            lockedName = "ABCD"


    if (isButtonPressed and currentlyLocked):
        currentlyLocked = False
        lockedName = "ABCD"

    # If one of the 4 button is pressed, we want to change the locked point
    # For example if the left button is pressed, we want to lock to the closest point on the left of the center of the picture
    # So we first have to find :
    # 1. The closest point on the left of the center of the picture
    # 2. The closest point on the right of the center of the picture
    # 3. The closest point on the top of the center of the picture
    # 4. The closest point on the bottom of the center of the picture
        
    nameLeft = ""
    nameRight = ""
    nameUp = ""
    nameDown = ""

    for i, (name, firstSeen, x, y, _, _, _, _, _, _) in enumerate(all_light_points):
        if (x < resolution[0]/2):
            if (nameLeft == ""):
                nameLeft = name
            elif (abs(x - resolution[0]/2) < abs(all_light_points[i-1][2] - resolution[0]/2)):
                nameLeft = name
        elif (x > resolution[0]/2):
            if (nameRight == ""):
                nameRight = name
            elif (abs(x - resolution[0]/2) < abs(all_light_points[i-1][2] - resolution[0]/2)):
                nameRight = name
        if (y < resolution[1]/2):
            if (nameUp == ""):
                nameUp = name
            elif (abs(y - resolution[1]/2) < abs(all_light_points[i-1][3] - resolution[1]/2)):
                nameUp = name
        elif (y > resolution[1]/2):
            if (nameDown == ""):
                nameDown = name
            elif (abs(y - resolution[1]/2) < abs(all_light_points[i-1][3] - resolution[1]/2)):
                nameDown = name

    # Now we have the name of the closest point on the left, right, top and bottom of the center of the picture
    # We can now check which button is pressed and lock to the corresponding point
    if (swLeft):
        lockedName = nameLeft
        currentlyLocked = True
    elif (swRight):
        lockedName = nameRight
        currentlyLocked = True
    elif (swUp):
        lockedName = nameUp
        currentlyLocked = True
    elif (swDown):
        lockedName = nameDown
        currentlyLocked = True
    
    lockedPoint = LightPoint(name="ABCD", isVisible=False, x=0, y=0, age=0)
        
    for i, (name, firstSeen, x, y, age, timestamp, _, _, _, _) in enumerate(all_light_points):
        if (name == lockedName):
            lockedPoint.name = name
            lockedPoint.x = x-resolution[0]/2
            lockedPoint.y = -(y-resolution[1]/2)
            lockedPoint.isVisible = (currentlyLocked and not isButtonPressed)

    return lockedPoint

def setDetectionSettings(idRadiusIn, lockRadiusIn, lightLifetimeIn, lightThresholdIn):
    global idRadius, lockRadius, lightLifetime, lightThreshold 
    idRadius = idRadiusIn
    lockRadius = lockRadiusIn
    lightLifetime = lightLifetimeIn
    lightThreshold = lightThresholdIn