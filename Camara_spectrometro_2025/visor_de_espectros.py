import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageTk
import csv

def pixel_to_wavelength(x):
    return -0.0003603 * x**2 + 1.4657 * x - 255.63

class VisorEspectro:
    def __init__(self, root):
        self.root = root
        self.root.title("Visor de Datos del Espectrómetro")
        
        self.video_path = None
        self.csv_path = None
        self.cap = None
        self.frames = []
        self.current_frame_idx = 0
        self.playing = False
        
        # --- Controles ---
        tk.Button(root, text="Cargar Video", command=self.cargar_video).pack(side="left", padx=5)
        tk.Button(root, text="Cargar CSV", command=self.cargar_csv).pack(side="left", padx=5)
        self.play_button = tk.Button(root, text="Play", command=self.toggle_play)
        self.play_button.pack(side="left", padx=5)
        
        # --- Canvas Video ---
        self.video_label = tk.Label(root)
        self.video_label.pack()
        
        # --- Grafico ---
        fig = Figure(figsize=(7, 3), dpi=100)
        self.ax = fig.add_subplot(111)
        self.linea, = self.ax.plot([], [], color='blue')
        self.ax.set_title("Intensidad espectral")
        self.ax.set_xlabel("Longitud de onda (nm)")
        self.ax.set_ylabel("Intensidad")
        for ref in [408, 531.8, 652]:
            self.ax.axvline(x=ref, color='gray', linestyle='--')
        self.canvas = FigureCanvasTkAgg(fig, master=root)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack()
        
        self.root.after(30, self.update_frame)
    
    def cargar_video(self):
        self.video_path = filedialog.askopenfilename(filetypes=[("Video AVI", "*.avi")])
        if self.video_path:
            self.cap = cv2.VideoCapture(self.video_path)
            self.frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    def cargar_csv(self):
        self.csv_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if self.csv_path:
            with open(self.csv_path, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # encabezado
                self.csv_data = [list(map(float, row)) for row in reader]
    
    def toggle_play(self):
        self.playing = not self.playing
        self.play_button.config(text="Pause" if self.playing else "Play")
    
    def update_frame(self):
        if self.cap and self.playing:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame_idx += 1
                # Procesar ROI del espectro
                h = frame.shape[0]
                y1, y2 = int(h * 0.4), int(h * 0.6)
                frame_roi = frame[y1:y2, :]
                gray = cv2.cvtColor(frame_roi, cv2.COLOR_BGR2GRAY)
                profile = np.mean(gray, axis=0)
                x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
                self.linea.set_data(x_nm, profile)
                self.ax.set_xlim(400, 780)
                self.ax.set_ylim(0, max(profile)*1.1 if len(profile) > 0 else 1)
                self.canvas.draw()
                # Mostrar frame
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                imgtk = ImageTk.PhotoImage(image=Image.fromarray(img))
                self.video_label.imgtk = imgtk
                self.video_label.config(image=imgtk)
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.current_frame_idx = 0
        self.root.after(30, self.update_frame)

if __name__ == "__main__":
    root = tk.Tk()
    app = VisorEspectro(root)
    root.mainloop()
