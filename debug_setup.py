import sys
import os

# Ensure the current directory is in sys.path
sys.path.append(os.getcwd())

import tools

try:
    sc = tools.get_setup_code()
    print("--- SETUP CODE START (First 1000 chars) ---")
    print(sc[:1000])
    print("--- SETUP CODE END ---")
except Exception as e:
    import traceback
    traceback.print_exc()
