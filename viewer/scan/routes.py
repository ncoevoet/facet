import os
import subprocess
import sys
import threading
import time
from flask import request, jsonify
from viewer.scan import scan_bp
from viewer.auth import require_superadmin
from viewer.config import VIEWER_CONFIG, get_all_scan_directories, get_user_directories

_PHOTOS_SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'photos.py')

# Global scan state (only one scan at a time)
_scan_lock = threading.Lock()
_scan_state = {
    'running': False,
    'process': None,
    'output_lines': [],
    'started_at': None,
    'directories': [],
    'exit_code': None,
}


def _read_scan_output(proc):
    """Background thread to read subprocess output."""
    for line in proc.stdout:
        _scan_state['output_lines'].append(line.rstrip('\n'))
        # Keep last 500 lines to prevent unbounded memory growth
        if len(_scan_state['output_lines']) > 500:
            _scan_state['output_lines'] = _scan_state['output_lines'][-500:]
    proc.wait()
    _scan_state['exit_code'] = proc.returncode
    _scan_state['running'] = False


@scan_bp.route('/api/scan/start', methods=['POST'])
@require_superadmin
def api_start_scan():
    """Trigger a photo scan as a background subprocess.

    Only available to superadmin users. Only one scan at a time.
    The scan button must also be enabled in config: viewer.features.show_scan_button.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        return jsonify({'error': 'Scan feature not enabled'}), 403

    if not _scan_lock.acquire(blocking=False):
        return jsonify({'error': 'A scan is already running'}), 409

    try:
        if _scan_state['running']:
            _scan_lock.release()
            return jsonify({'error': 'A scan is already running'}), 409

        data = request.get_json() or {}
        directories = data.get('directories', [])

        # Validate directories are in configured set
        all_configured = set(get_all_scan_directories())
        for d in directories:
            if d not in all_configured:
                _scan_lock.release()
                return jsonify({'error': f'Directory not configured: {d}'}), 400

        if not directories:
            _scan_lock.release()
            return jsonify({'error': 'No directories specified'}), 400

        # Build command
        cmd = [sys.executable, _PHOTOS_SCRIPT] + directories

        # Start subprocess
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Update state
        _scan_state['running'] = True
        _scan_state['process'] = proc
        _scan_state['output_lines'] = []
        _scan_state['started_at'] = time.time()
        _scan_state['directories'] = directories
        _scan_state['exit_code'] = None

        # Start background reader thread
        reader = threading.Thread(target=_read_scan_output, args=(proc,), daemon=True)
        reader.start()

        _scan_lock.release()
        return jsonify({
            'success': True,
            'message': 'Scan started',
            'directories': directories,
            'pid': proc.pid,
        })

    except Exception as e:
        _scan_state['running'] = False
        _scan_lock.release()
        return jsonify({'error': str(e)}), 500


@scan_bp.route('/api/scan/status')
@require_superadmin
def api_scan_status():
    """Poll scan progress. Returns last N lines of output."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        return jsonify({'error': 'Scan feature not enabled'}), 403

    last_n = request.args.get('lines', 20, type=int)
    lines = _scan_state['output_lines'][-last_n:]

    elapsed = None
    if _scan_state['started_at']:
        elapsed = round(time.time() - _scan_state['started_at'], 1)

    return jsonify({
        'running': _scan_state['running'],
        'directories': _scan_state['directories'],
        'output': lines,
        'elapsed_seconds': elapsed,
        'exit_code': _scan_state['exit_code'],
    })


@scan_bp.route('/api/scan/directories')
@require_superadmin
def api_scan_directories():
    """List all configured directories available for scanning."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        return jsonify({'error': 'Scan feature not enabled'}), 403

    from flask import session
    user_id = session.get('user_id')
    all_dirs = get_all_scan_directories()
    user_dirs = get_user_directories(user_id) if user_id else []

    return jsonify({
        'directories': [
            {'path': d, 'owner': 'shared' if d not in user_dirs else user_id}
            for d in all_dirs
        ]
    })
