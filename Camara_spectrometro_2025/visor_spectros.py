import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog
import os

def graficar_varios_espectros():
    root = tk.Tk()
    root.withdraw()  # Oculta la ventana principal
    
    espectros = []
    colores = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'cyan']
    color_index = 0

    continuar = True
    while continuar:
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not file_path:
            break
        
        nombre = os.path.basename(file_path)
        data = pd.read_csv(file_path)
        data_filtered = data[(data["Longitud de onda (nm)"] >= 350) & (data["Longitud de onda (nm)"] <= 850)]
        espectros.append((data_filtered, colores[color_index % len(colores)], nombre))
        color_index += 1

        continuar = tk.messagebox.askyesno("Agregar otro", "¿Desea agregar otro espectro?")

    if espectros:
        plt.figure(figsize=(10,5))
        for data, color, nombre in espectros:
            plt.plot(data["Longitud de onda (nm)"], data["Intensidad"], color=color, label=nombre)
        plt.title("Comparación de Espectros")
        plt.xlabel("Longitud de onda (nm)")
        plt.ylabel("Intensidad")
        plt.grid(True)
        plt.legend()
        plt.show()
    else:
        print("No se seleccionaron archivos.")

if __name__ == "__main__":
    graficar_varios_espectros()
