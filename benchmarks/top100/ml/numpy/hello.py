import numpy as np

# Official usage: Create array
# We create a small array to trigger C-extension initialization
arr = np.array([1, 2, 3])

print(f"NumPy initialized: {arr}. Version: {np.__version__}")
