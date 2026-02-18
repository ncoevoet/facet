from flask import Blueprint

scan_bp = Blueprint('scan', __name__)

from viewer.scan import routes  # noqa: E402, F401
