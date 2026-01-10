import scipy
import scipy.special

# Verify sparse matrix or special func (heavy)
print(f"scipy version: {scipy.__version__}")
scipy.special.expit(0.5)
