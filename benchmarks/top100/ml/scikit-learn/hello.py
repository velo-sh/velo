import sklearn
import sklearn.utils

# Verify native extension loading
print(f"scikit-learn version: {sklearn.__version__}")
# Minimal check
sklearn.utils.check_random_state(42)
