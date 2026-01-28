import os


def setup_django_heavy():
    print("[HIO] Setting up Django Heavyweight Skeleton...")

    # Generate logic for 200 models
    models_path = "examples/django-heavy/skeleton/heavy_app/models.py"
    if os.path.exists(models_path):
        print("[HIO] Models already exist, skipping generation (Idempotent).")
        return

    with open(models_path, "w") as f:
        f.write("from django.db import models\n\n")
        for i in range(200):
            f.write(f"class HeavyModel{i}(models.Model):\n")
            f.write("    field1 = models.CharField(max_length=100)\n")
            f.write("    field2 = models.IntegerField()\n")
            f.write("    field3 = models.DateTimeField(auto_now_add=True)\n\n")

    print(f"[HIO] Generated 200 models in {models_path}")


if __name__ == "__main__":
    setup_django_heavy()
