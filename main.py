import sys; print("✅ Fast Loader Active" if any("velo_loader" in m for m in sys.modules) else "❌ Fast Loader Inactive")
