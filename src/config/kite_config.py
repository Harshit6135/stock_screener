import os
import sys


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from local_secrets import KITE_API_KEY, KITE_API_SECRET
except ImportError:
    KITE_API_KEY = "YOUR_API_KEY"
    KITE_API_SECRET = "YOUR_API_SECRET"

KITE_CONFIG = {
    "api_key": KITE_API_KEY,
    "api_secret": KITE_API_SECRET,
    "redirect_url": "http://127.0.0.1"
}
