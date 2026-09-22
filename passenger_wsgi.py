"""Entry point for cPanel's "Setup Python App" (Phusion Passenger).

Passenger imports this file and looks for `application`. Point the app's
"Application startup file" at it in cPanel.

The sys.path line matters: Passenger runs with the application root as the
working directory, but the project's own package (`config`) is only importable
if that root is on the path explicitly.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
