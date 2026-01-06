import pandas as pd

# Create a minimal DataFrame to trigger C-extension init
df = pd.DataFrame({'a': [1, 2, 3]})
print(f"pandas version: {pd.__version__}")