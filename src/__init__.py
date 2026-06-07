import os
import sys

# Add the src directory to sys.path if it's not already there
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Centralized pandas option — avoids repeating in every service module
import pandas as pd

pd.set_option("future.no_silent_downcasting", True)
