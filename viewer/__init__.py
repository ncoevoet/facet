import os
import sys

# Ensure the project root is in Python path for local imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask
from viewer.config import _share_secret, VIEWER_CONFIG, load_viewer_config, get_comparison_mode_settings
from viewer.auth import is_edition_enabled, is_edition_authenticated, register_auth_routes, _is_authenticated, get_session_user_id
from viewer.db_helpers import _add_tag_filter
from viewer.filters import register_filters


def create_app():
    """Flask application factory."""
    app = Flask(__name__, template_folder='templates')
    app.secret_key = _share_secret

    # Register auth routes and before_request hook
    register_auth_routes(app)

    # Initialize i18n support
    from i18n import init_i18n
    init_i18n(app)

    # Register template filters
    register_filters(app)

    # Register blueprints
    from viewer.gallery import gallery_bp
    from viewer.thumbnails import thumbnails_bp
    from viewer.filter_options import filter_options_bp
    from viewer.faces_api import faces_api_bp
    from viewer.persons import persons_bp
    from viewer.merge_suggestions import merge_suggestions_bp
    from viewer.comparison import comparison_bp
    from viewer.stats import stats_bp
    from person_viewer import person_bp
    from viewer.scan import scan_bp

    app.register_blueprint(gallery_bp)
    app.register_blueprint(thumbnails_bp)
    app.register_blueprint(filter_options_bp)
    app.register_blueprint(faces_api_bp)
    app.register_blueprint(persons_bp)
    app.register_blueprint(merge_suggestions_bp)
    app.register_blueprint(comparison_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(person_bp)
    app.register_blueprint(scan_bp)

    return app
