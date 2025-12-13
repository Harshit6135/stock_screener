import os
import sys

# Add project root to sys.path to allow importing local_secrets
# This config file is in project_root/config/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from local_secrets import KITE_API_KEY, KITE_API_SECRET
except ImportError:
    # Fallback or empty if file not found (e.g. in CI/CD without secrets)
    KITE_API_KEY = "YOUR_API_KEY"
    KITE_API_SECRET = "YOUR_API_SECRET"
    print("WARNING: local_secrets.py not found. Using placeholder API keys.")

KITE_CONFIG = {
    "api_key": KITE_API_KEY,
    "api_secret": KITE_API_SECRET,
    "redirect_url": "http://127.0.0.1"
}
