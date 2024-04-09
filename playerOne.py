import ctypes
import platform
import time
import numpy as np
import cv2

# Specify the full path to the shared library
lib_path = f'/home/pi/PlayerToPy/lib/arm64/libPlayerOneCamera.so.3.6.1'

# Load the shared library
libcamera = ctypes.CDLL(lib_path)

# Define necessary constants
POA_OK = 0

STATE_CLOSED = 0                
STATE_OPENED = 1                      
STATE_EXPOSING = 2

POA_FALSE = 0
POA_TRUE = 1

POA_BAYER_RG = 0
POA_BAYER_BG = 1
POA_BAYER_GR = 2
POA_BAYER_GB = 3
POA_BAYER_MONO = -1

POA_RAW8 = 0
POA_RAW16 = 1
POA_RGB24 = 2
POA_MONO8 = 3
POA_END = -1

POA_EXPOSURE = 0
POA_GAIN = 1
POA_HARDWARE_BIN = 2
POA_TEMPERATURE = 3
POA_WB_R = 4
POA_WB_G = 5
POA_WB_B = 6
POA_OFFSET = 7
POA_AUTOEXPO_MAX_GAIN = 8
POA_AUTOEXPO_MAX_EXPOSURE = 9
POA_AUTOEXPO_BRIGHTNESS = 10
POA_GUIDE_NORTH = 11
POA_GUIDE_SOUTH = 12
POA_GUIDE_EAST = 13
POA_GUIDE_WEST = 14
POA_EGAIN = 15
POA_COOLER_POWER = 16
POA_TARGET_TEMP = 17
POA_COOLER = 18
POA_HEATER = 19
POA_HEATER_POWER = 20
POA_FAN_POWER = 21
POA_FLIP_NONE = 22
POA_FLIP_HORI = 23
POA_FLIP_VERT = 24
POA_FLIP_BOTH = 25
POA_FRAME_LIMIT = 26
POA_HQI = 27
POA_USB_BANDWIDTH_LIMIT = 28
POA_PIXEL_BIN_SUM = 29
POA_MONO_BIN = 30

class POACameraProperties(ctypes.Structure):
    _fields_ = [
        ('cameraModelName', ctypes.c_char * 256),
        ('userCustomID', ctypes.c_char * 16),
        ('cameraID', ctypes.c_int),
        ('maxWidth', ctypes.c_int),
        ('maxHeight', ctypes.c_int),
        ('bitDepth', ctypes.c_int),
        ('isColorCamera', ctypes.c_int),
        ('isHasST4Port', ctypes.c_int),
        ('isHasCooler', ctypes.c_int),
        ('isUSB3Speed', ctypes.c_int),
        ('bayerPattern', ctypes.c_int),
        ('pixelSize', ctypes.c_double),
        ('SN', ctypes.c_char * 64),
        ('sensorModelName', ctypes.c_char * 32),
        ('localPath', ctypes.c_char * 256),
        ('bins', ctypes.c_int * 8),
        ('imgFormats', ctypes.c_int * 8),
        ('isSupportHardBin', ctypes.c_int),
        ('pID', ctypes.c_int)
    ]
    

class POAConfigAttributes(ctypes.Structure):
    _fields_ = [
        ('isSupportAuto', ctypes.c_int),  # Assuming POABool is backed by an integer
        ('isWritable', ctypes.c_int),     # Assuming POABool is backed by an integer
        ('isReadable', ctypes.c_int),     # Assuming POABool is backed by an integer
        ('configID', ctypes.c_int),       # Assuming POAConfig is backed by an integer
        ('valueType', ctypes.c_int),      # Assuming POAValueType is backed by an integer
        ('maxValue', ctypes.c_double),
        ('minValue', ctypes.c_double),
        ('defaultValue', ctypes.c_double),
        ('szConfName', ctypes.c_char * 64),
        ('szDescription', ctypes.c_char * 128),
        ('reserved', ctypes.c_char * 64)
    ]

exposureSetting = 1000
gainSetting = 75
widthSetting = 652
heightSetting = 488

def playerOneCamInit(): 
    global exposureSetting, gainSetting, widthSetting, heightSetting
    num_cameras = libcamera.POAGetCameraCount()
    if num_cameras < 0:
        print(f"Error: Failed to get the number of cameras. Error code: {num_cameras}")
        exit()

    print(f"Number of connected cameras: {num_cameras}")

    # Open and initialize each connected camera
    for i in range(num_cameras):

        camera_properties = POACameraProperties()
        ret = libcamera.POAGetCameraProperties(i, ctypes.byref(camera_properties))
        if ret != POA_OK:
            print(f"Error: Failed to get properties of camera {i}. Error code: {ret}")
            # Close the camera if retrieving properties fails
            libcamera.POACloseCamera(i)
            continue
        else: 
            print(f"Camera {i} got properties.")

        # print(f"Camera {i} properties:")
        # print(f"Camera Model Name: {camera_properties.cameraModelName}")
        # print(f"User Custom ID: {camera_properties.userCustomID}")
        # print(f"Camera ID: {camera_properties.cameraID}")
        # print(f"Max Width: {camera_properties.maxWidth}")
        # print(f"Max Height: {camera_properties.maxHeight}")
        # print(f"Bit Depth: {camera_properties.bitDepth}")
        # print(f"Is Color Camera: {camera_properties.isColorCamera}")
        # print(f"Is Has ST4 Port: {camera_properties.isHasST4Port}")
        # print(f"Is Has Cooler: {camera_properties.isHasCooler}")
        # print(f"Is USB3 Speed: {camera_properties.isUSB3Speed}")
        # print(f"Bayer Pattern: {camera_properties.bayerPattern}")
        # print(f"Pixel Size: {camera_properties.pixelSize}")
        # print(f"SN: {camera_properties.SN}")
        # print(f"Sensor Model Name: {camera_properties.sensorModelName}")
        # print(f"Local Path: {camera_properties.localPath}")

        # Open the camera
        ret = libcamera.POAOpenCamera(i)
        if ret != POA_OK:
            print(f"Error: Failed to open camera {i}. Error code: {ret}")
            continue
        else: 
            print(f"Camera {i} is successfully opened.")

        # Initialize the camera 
        ret = libcamera.POAInitCamera(i)
        if ret != POA_OK:
            print(f"Error: Failed to initialize camera {i}. Error code: {ret}")
            # Close the camera if initialization fails
            libcamera.POACloseCamera(i)
            continue
        else:
            print(f"Camera {i} is successfully initialized.")

        config_count = ctypes.c_int(0)
        # error = libcamera.POAGetConfigsCount(i, ctypes.byref(config_count))
        # if error != POA_OK:
        #     print("Get config count failed！, error code: {error}")
        #     continue
        # else:
        #     print(f"Camera {i} has {config_count} configs.")


        # ppConfAttr = (ctypes.POINTER(POAConfigAttributes) * np.int64(config_count))()
        # for j in range(np.int64(config_count)):
        #     ppConfAttr[j] = ctypes.pointer(POAConfigAttributes())

        #     error = libcamera.POAGetConfigAttributes(i, j, ppConfAttr[i])

        #     if error == POA_OK:
        #         print(f"config name: {ppConfAttr[i].contents.szConfName}, config description: {ppConfAttr[i].contents.szDescription}")
        #         print(f"is writable: {int(ppConfAttr[i].contents.isWritable)}")
        #         print(f"is readable: {int(ppConfAttr[i].contents.isReadable)}")
        
        # Set image parameters, if exposing, please stop exposure first
        camera_state = ctypes.c_int()
        libcamera.POAGetCameraState(i, ctypes.byref(camera_state))

        if camera_state.value == STATE_EXPOSING:
            libcamera.POAStopExposure(i)

        # Set bin, note: after setting bin, please get the image size and start position
        error = libcamera.POASetImageBin(i, camera_properties.bins[1])  # set bin to 2, default bin is 1

        if error != POA_OK:
            print(f"Set bin failed, error code: {libcamera.POAGetErrorString(error)}")

        # startX = ctypes.c_int(0)
        # startY = ctypes.c_int(0)
        # width = ctypes.c_int(0)
        # height = ctypes.c_int(0)

        # error = libcamera.POAGetImageStartPos(i, ctypes.byref(startX), ctypes.byref(startY))
        # if error != POA_OK:
        #     # if get image start position failed, set startX and startY to 0
        #     startX.value = 0
        #     startY.value = 0
        #     print(f"Get Image Start Pos failed, error code: {libcamera.POAGetErrorString(error)}")
        # else: 
        #     print(f"Start X: {startX.value}, Start Y: {startY.value}")

        # error = libcamera.POAGetImageSize(i, ctypes.byref(width), ctypes.byref(height))
        # if error != POA_OK:
        #     # if get image size failed, set width and height to the maximum value under current bin
        #     width.value = camera_properties.contents.maxWidth // camera_properties.contents.bins[1]  # Maximum width under current bin
        #     height.value = camera_properties.contents.maxHeight // camera_properties.contents.bins[1]  # Maximum height under current bin
        #     print(f"Get Image Size failed, error code: {libcamera.POAGetErrorString(error)}")
        # else:
        #     print(f"Width: {width.value}, Height: {height.value}")

        # Set image format, if exposing, please stop exposure first
        error = libcamera.POASetImageFormat(i, POA_MONO8)  # default image format is POA_RAW8
        if error != POA_OK:
            print(f"Set image format failed, error code: {libcamera.POAGetErrorString(error)}")
        else: 
            print("Set image format successfully.")

        # Set exposure
        exposure_us = ctypes.c_int(exposureSetting)  # 100ms
        error = libcamera.POASetConfig(i, POA_EXPOSURE, exposure_us, POA_FALSE)

        if error != POA_OK:
            print(f"Set exposure failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("Set exposure successfully.")

        # Set gain
        gain = ctypes.c_int(gainSetting)  # 100
        error = libcamera.POASetConfig(i, POA_GAIN, gain, POA_FALSE)

        if error != POA_OK:
            print(f"Set gain failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("Set gain successfully.")
    
        error = libcamera.POAStartExposure(i, POA_FALSE)  # continuously exposure
        if error != POA_OK:
            print(f"start exposure failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("start exposure successfully.")

def setPlayerOneCameraSettings(gainIn, exposureTimeIn):
    camera_state = ctypes.c_int()
    libcamera.POAGetCameraState(0, ctypes.byref(camera_state))

    if camera_state.value == STATE_EXPOSING:
        libcamera.POAStopExposure(0)

    # Set exposure
        exposure_us = ctypes.c_int(np.int32(exposureTimeIn))  # 100ms
        error = libcamera.POASetConfig(0, POA_EXPOSURE, exposure_us, POA_FALSE)

        if error != POA_OK:
            print(f"Set exposure failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("Set exposure successfully.")

        # Set gain
        gain = ctypes.c_int(np.int32(gainIn))  # 100
        error = libcamera.POASetConfig(0, POA_GAIN, gain, POA_FALSE)

        if error != POA_OK:
            print(f"Set gain failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("Set gain successfully.")

        error = libcamera.POAStartExposure(0, POA_FALSE)  # continuously exposure
        if error != POA_OK:
            print(f"start exposure failed, error code: {libcamera.POAGetErrorString(error)}")
        else:
            print("start exposure successfully.")

def getPlayerOneFrame(): 
    global exposureSetting, gainSetting, widthSetting, heightSetting
    # start exposure
    buffer_size = widthSetting * heightSetting * 2  # raw16
    data_buffer = (ctypes.c_uint8 * buffer_size)()

    pIsReady = ctypes.c_int(POA_FALSE)
    while np.int64(pIsReady) == POA_FALSE:
        # sleep(exposure_us / 1000 / 10)  # ms
        libcamera.POAImageReady(0, ctypes.byref(pIsReady))

    error = libcamera.POAGetImageData(0, data_buffer, ctypes.c_int(buffer_size), ctypes.c_int(exposureSetting // 1000 + 500))
    if error != POA_OK:
        print(f"Get image data failed, error code: {error}")

    # Convert binary image to jpg using OpenCV with only the first half of the buffer
    data_buffer_half = bytes(data_buffer[:buffer_size // 2])
    img = np.frombuffer(data_buffer_half, dtype=np.uint8).reshape((heightSetting, widthSetting))
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img = img.astype(np.uint8)
    return img

if __name__ == "__main__":

  playerOneCamInit()

  for i in range(10):
    img = getPlayerOneFrame()
    # Save image as png
    cv2.imwrite(f'img_{i}.png', img)
    # cv2.imshow('image', img)
    # cv2.waitKey(0)
