import re
import os
import hmac
import hashlib
from functools import wraps
from flask import request, redirect, session, jsonify, abort
from viewer.config import _share_secret, VIEWER_CONFIG, is_multi_user_enabled, get_user_config


def generate_person_share_token(person_id):
    """Generate an HMAC token for sharing a person page."""
    return hmac.new(_share_secret.encode(), str(person_id).encode(), 'sha256').hexdigest()


def verify_person_share_token(person_id, token):
    """Verify an HMAC share token for a person page."""
    expected = generate_person_share_token(person_id)
    return hmac.compare_digest(token, expected)


# --- PASSWORD HASHING (multi-user) ---

def hash_password(password):
    """Hash a password using PBKDF2-HMAC-SHA256. Returns 'salt_hex:dk_hex'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password, stored_hash):
    """Verify a password against a stored 'salt_hex:dk_hex' hash."""
    try:
        salt_hex, dk_hex = stored_hash.split(':')
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        actual_dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(actual_dk, expected_dk)
    except (ValueError, AttributeError):
        return False


# --- PASSWORD AUTHENTICATION (legacy single-user) ---

def _get_viewer_password():
    """Get password from viewer config, returns empty string if not set."""
    return VIEWER_CONFIG.get('password', '')


def _is_authenticated():
    """Check if current session is authenticated (legacy or multi-user)."""
    if is_multi_user_enabled():
        return bool(session.get('user_id'))
    password = _get_viewer_password()
    if not password:
        return True  # No password required
    return session.get('authenticated', False)


def _get_edition_password():
    """Get edition password from config."""
    return VIEWER_CONFIG.get('edition_password', '')


def is_edition_enabled():
    """Check if edition mode is available.

    In multi-user mode, edition is available for admin/superadmin roles.
    In legacy mode, edition requires a configured edition_password.
    """
    if is_multi_user_enabled():
        return True  # Always available (role-gated)
    return bool(_get_edition_password())


def is_edition_authenticated():
    """Check if current session has edition-level access.

    In multi-user mode, admin and superadmin roles have edition access.
    In legacy mode, requires edition_password authentication.
    """
    if is_multi_user_enabled():
        return session.get('user_role') in ('admin', 'superadmin')
    edition_password = _get_edition_password()
    if not edition_password:
        return False  # No password = edition disabled
    return session.get('edition_authenticated', False)


def get_session_user_id():
    """Get the current user_id from session, or None in legacy mode."""
    if is_multi_user_enabled():
        return session.get('user_id')
    return None


def require_edition(f):
    """Decorator that returns 403 JSON if edition mode is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_edition_authenticated():
            return jsonify({'error': 'Edition disabled'}), 403
        return f(*args, **kwargs)
    return decorated


def require_auth(f):
    """Decorator that returns 401 JSON if user is not authenticated.

    In multi-user mode, any logged-in user passes. Used for rating/favorite actions.
    In legacy mode, checks edition authentication.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_multi_user_enabled():
            if not session.get('user_id'):
                return jsonify({'error': 'Authentication required'}), 401
        else:
            if not is_edition_authenticated():
                return jsonify({'error': 'Edition disabled'}), 403
        return f(*args, **kwargs)
    return decorated


def require_superadmin(f):
    """Decorator that returns 403 JSON if user is not superadmin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_multi_user_enabled():
            return jsonify({'error': 'Multi-user mode required'}), 403
        if session.get('user_role') != 'superadmin':
            return jsonify({'error': 'Superadmin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def register_auth_routes(app):
    """Register authentication routes and before_request hook on the app."""

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Handle login form display and submission."""
        from flask import render_template

        multi_user = is_multi_user_enabled()

        if not multi_user:
            # Legacy single-password mode
            password = _get_viewer_password()
            if not password:
                return redirect('/')

        next_url = request.args.get('next', '/')

        if request.method == 'POST':
            next_url = request.form.get('next', '/')

            if multi_user:
                username = request.form.get('username', '').strip()
                password = request.form.get('password', '')
                user = get_user_config(username)
                if user and verify_password(password, user.get('password_hash', '')):
                    session['user_id'] = username
                    session['user_role'] = user.get('role', 'user')
                    session['user_display_name'] = user.get('display_name', username)
                    session['authenticated'] = True
                    return redirect(next_url)
                from i18n import _ as translate
                return render_template('login.html', error=translate('login.invalid_credentials'),
                                       next_url=next_url, multi_user=True)
            else:
                if request.form.get('password') == _get_viewer_password():
                    session['authenticated'] = True
                    return redirect(next_url)
                from i18n import _ as translate
                return render_template('login.html', error=translate('login.invalid_password'),
                                       next_url=next_url, multi_user=False)

        return render_template('login.html', error=None, next_url=next_url, multi_user=multi_user)

    @app.route('/api/edition/login', methods=['POST'])
    def api_edition_login():
        """Authenticate for edition mode (legacy single-user only)."""
        if is_multi_user_enabled():
            return jsonify({'error': 'Use /login for multi-user auth'}), 400
        data = request.get_json() or {}
        password = data.get('password', '')
        edition_password = _get_edition_password()
        if edition_password and password == edition_password:
            session['edition_authenticated'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Invalid password'}), 401

    @app.route('/api/edition/logout', methods=['POST'])
    def api_edition_logout():
        """Log out of edition mode (legacy) or full logout (multi-user)."""
        if is_multi_user_enabled():
            session.clear()
            return jsonify({'success': True})
        session.pop('edition_authenticated', None)
        return jsonify({'success': True})

    @app.route('/logout', methods=['POST'])
    def logout():
        """Full logout for multi-user mode."""
        session.clear()
        return redirect('/login')

    @app.route('/api/person/<int:person_id>/share-token')
    def api_person_share_token(person_id):
        """Generate a share URL token for a person page. Only available to local (non-shared) users."""
        if session.get('shared_person_id') is not None:
            abort(403)
        token = generate_person_share_token(person_id)
        return jsonify({'token': token})

    @app.before_request
    def check_access():
        """Check authentication and gate shared visitors."""
        # Allow login/logout routes without authentication
        if request.path in ('/login', '/logout'):
            return None

        # Allow static assets without authentication
        if request.path.startswith('/static/'):
            return None

        # Check if incoming request has a share token on a person page
        match = re.match(r'^/person/(\d+)', request.path)
        if match and request.args.get('token'):
            person_id = int(match.group(1))
            token = request.args.get('token')
            if verify_person_share_token(person_id, token):
                session['shared_person_id'] = person_id
                # Redirect to strip the token from the URL
                from urllib.parse import urlencode
                args = {k: v for k, v in request.args.items() if k != 'token'}
                clean_url = request.path
                if args:
                    clean_url += '?' + urlencode(args)
                return redirect(clean_url)
            else:
                abort(403)

        # If session marks this visitor as a shared visitor, restrict routes
        shared_pid = session.get('shared_person_id')
        if shared_pid is not None:
            allowed_prefixes = [
                f'/person/{shared_pid}',
                '/thumbnail',
                f'/person_thumbnail/{shared_pid}',
                '/api/download-selected',
                '/api/download',
                '/static/',
            ]
            if not any(request.path.startswith(p) for p in allowed_prefixes):
                # Clear shared session and let normal auth flow handle it
                session.pop('shared_person_id', None)
                # Fall through to password authentication check below

        # Check authentication
        if not _is_authenticated():
            # For API routes, return 401
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            # For regular routes, redirect to login
            from urllib.parse import urlencode
            next_url = request.path
            if request.query_string:
                next_url += '?' + request.query_string.decode('utf-8')
            return redirect(f'/login?next={next_url}')
