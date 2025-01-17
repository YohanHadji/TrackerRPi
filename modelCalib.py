import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

# Load the data
data = pd.read_csv('calibValuesColimator2.csv', delim_whitespace=True)
data.columns = ['servo1', 'servo2', 'x', 'y']

print(data)

# Prepare the input (X) and output (y) data for servo1
X = data[['x', 'y']]
y1 = data['servo1']
y2 = data['servo2']

print(X)

print(y1)
print(y2)

# Fit linear models for servo1 and servo2
model_servo1 = LinearRegression().fit(X, y1)
model_servo2 = LinearRegression().fit(X, y2)

# Output the parameters of the models
print("Model for servo1 as a function of x and y:")
print(f"Intercept: {model_servo1.intercept_}")
print(f"Coefficients: {model_servo1.coef_}")

print("\nModel for servo2 as a function of x and y:")
print(f"Intercept: {model_servo2.intercept_}")
print(f"Coefficients: {model_servo2.coef_}")
