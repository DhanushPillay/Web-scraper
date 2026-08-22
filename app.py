import sys
import os

# Inject src into Python path so internal imports work without modifying Render settings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.app import app

if __name__ == "__main__":
    app.run()
