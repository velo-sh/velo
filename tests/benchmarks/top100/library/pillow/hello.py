import PIL
from PIL import Image

img = Image.new("RGB", (60, 30), color="red")
print(f"Pillow version: {PIL.__version__}")
