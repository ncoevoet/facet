"""
Entry point for the FastAPI API server.

Usage:
    python viewer.py                    # Development (auto-reload)
    python viewer.py --production       # Production mode

Or directly with uvicorn:
    uvicorn api:create_app --factory --reload --port 5000
"""

import json
import logging
import os
import sys
import argparse

# Ensure the script's directory is in Python path for local imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


def _configure_logging():
    """Set up structured logging. Level comes from (in priority order):
    1. FACET_LOG_LEVEL env var
    2. scoring_config.json log_level field
    3. Default: INFO

    The $FACET_CONFIG lookup is spelled out here rather than taken from
    :func:`config.default_config_path`, for the same reason this function reads
    the JSON by hand instead of building a ``ScoringConfig``: it runs before
    ``logging.basicConfig``, and ``config/__init__.py`` imports
    ``config.percentile_normalizer``, which imports ``db`` -- the whole
    database layer, pulled in to read one string. The duplication is three
    lines; the import is not.
    """
    level_name = os.environ.get("FACET_LOG_LEVEL")
    if not level_name:
        config_path = os.environ.get("FACET_CONFIG", "").strip() or os.path.join(_script_dir, "scoring_config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            level_name = cfg.get("log_level")
        except Exception:
            pass
    level_name = (level_name or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy third-party loggers
    for name in ("urllib3", "PIL", "matplotlib", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description='Facet API Server')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5000)),
                        help='Port to listen on (default: 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--production', action='store_true', help='Run in production mode')
    parser.add_argument('--workers', type=int, default=1, help='Number of workers (production)')
    args = parser.parse_args()

    _configure_logging()

    import uvicorn

    # Disable uvicorn's access log: its default format records the full request
    # line including the query string, which would leak share/frame/scan tokens
    # (passed as query params) into plaintext logs. The app's own
    # RequestLoggingMiddleware logs the path only.
    if args.production:
        uvicorn.run(
            "api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=args.workers,
            access_log=False,
        )
    else:
        uvicorn.run(
            "api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[_script_dir],
            access_log=False,
        )


if __name__ == '__main__':
    main()
