import os
import time
import cv2
import csv
import datetime
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from picamera2 import Picamera2
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

picam2 = Picamera2(1)
resolution = (1280, 720)
roi_top = 0.4
roi_height = 0.2
os.makedirs("datos", exist_ok=True)

root = tk.Tk()
root.title("Foto Espectro")

fig = Figure(figsize=(7, 4), dpi=100)
ax = fig.add_subplot(111)
linea, = ax.plot([], [], color='blue')
ax.set_title("Intensidad espectral")
ax.set_xlabel("Longitud de onda (nm)")
ax.set_ylabel("Intensidad")
for ref in [408, 531.8, 652]:
    ax.axvline(x=ref, color='gray', linestyle='--')
canvas = FigureCanvasTkAgg(fig, master=root)
canvas.draw()
canvas.get_tk_widget().pack()

frame_controls = tk.Frame(root)
frame_controls.pack()

def pixel_to_wavelength(x):
    return -0.0003603 * x**2 + 1.4657 * x - 255.63



exposure_slider = tk.Scale(frame_controls, from_=1, to=10000, orient="horizontal", label="Exposición (ms)", length=300)
exposure_slider.set(10)
exposure_slider.pack(side="left")

gain_slider = tk.Scale(frame_controls, from_=1, to=16, resolution=0.1, orient="horizontal", label="Ganancia")
gain_slider.set(1.0)
gain_slider.pack(side="left")

def capturar():
    picam2.stop()
    cfg = picam2.create_still_configuration(main={"size": resolution})
    picam2.configure(cfg)
    picam2.set_controls({
        "ExposureTime": exposure_slider.get() * 1000,
        "AnalogueGain": gain_slider.get()
    })
    picam2.start()
    time.sleep(0.5)

    frame = picam2.capture_array()
    h = frame.shape[0]
    y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
    frame_roi = frame[y1:y2, :]
    gray = cv2.cvtColor(frame_roi, cv2.COLOR_RGB2GRAY)
    profile = np.mean(gray, axis=0)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"foto_{timestamp}"
    cv2.imwrite(f"datos/{base}.jpg", cv2.cvtColor(frame_roi, cv2.COLOR_RGB2BGR))
    with open(f"datos/{base}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Longitud de onda (nm)", "Intensidad"])
        for i, val in enumerate(profile):
            writer.writerow([pixel_to_wavelength(i), val])

    x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
    linea.set_data(x_nm, profile)
    ax.set_xlim(min(x_nm), max(x_nm))
    ax.set_ylim(0, max(profile) * 1.1 if len(profile) > 0 else 1)
    canvas.draw()
    print(f"Foto y espectro guardados: {base}")

pic_button = tk.Button(root, text="Capturar foto", command=capturar)
pic_button.pack()

root.mainloop()
picam2.stop()
