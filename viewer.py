"""
Entry point for the FastAPI API server.

Usage:
    python viewer.py                    # Development (auto-reload)
    python viewer.py --production       # Production mode

Or directly with uvicorn:
    uvicorn api:create_app --factory --reload --port 5000
"""

import os
import sys
import argparse

# Ensure the script's directory is in Python path for local imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


def main():
    parser = argparse.ArgumentParser(description='Facet API Server')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5000)),
                        help='Port to listen on (default: 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--production', action='store_true', help='Run in production mode')
    parser.add_argument('--workers', type=int, default=1, help='Number of workers (production)')
    args = parser.parse_args()

    import uvicorn

    if args.production:
        uvicorn.run(
            "api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=args.workers,
        )
    else:
        uvicorn.run(
            "api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[_script_dir],
        )


if __name__ == '__main__':
    main()
