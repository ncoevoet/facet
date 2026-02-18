from datetime import datetime


def format_date(value):
    if not value: return ""
    try:
        dt = datetime.strptime(value[:19], '%Y:%m:%d %H:%M:%S')
        return dt.strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError):
        return value.split(' ')[0].replace(':', '/')


def cleanup(value, rnd):
    # Convert local absolute path to an SMB-friendly file URL
    if not rnd: return ""
    formatted_path = rnd[21:]
    return 'Z:' + formatted_path


def safe_float(value, decimals=2):
    """Safely format a value as float, handling None and bytes."""
    if value is None:
        return "0.00" if decimals == 2 else "0.0"
    if isinstance(value, bytes):
        return "N/A"
    try:
        fmt = f"%.{decimals}f"
        return fmt % float(value)
    except (ValueError, TypeError):
        return "N/A"


def format_shutter(value):
    """Format shutter speed as fraction (e.g., 0.01 -> 1/100)."""
    if not value or value == 0:
        return "?"
    try:
        val = float(value)
        if val >= 1:
            return f"{val:.1f}s"
        else:
            return f"1/{int(round(1/val))}"
    except (ValueError, TypeError, ZeroDivisionError):
        return "?"


def urlencode_without(params, keys):
    """Encode params excluding specific key(s). Accepts string or list."""
    from urllib.parse import urlencode
    if isinstance(keys, str):
        keys = [keys]
    keys_set = set(keys)
    filtered = {k: v for k, v in params.items() if k not in keys_set and v}
    return urlencode(filtered)


def urlencode_with(params, key, value):
    """Encode params with a specific key set."""
    from urllib.parse import urlencode
    updated = dict(params)
    updated[key] = value
    return urlencode({k: v for k, v in updated.items() if v or k == key})


def js_escape(s):
    """Escape a string for safe embedding inside a JavaScript string literal."""
    if s is None:
        return ''
    return s.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')


def urlencode_remove_person(params, person_id):
    """Encode params with one person ID removed from the comma-separated person list."""
    from urllib.parse import urlencode
    updated = dict(params)
    if 'person' in updated:
        ids = [p.strip() for p in updated['person'].split(',') if p.strip() != str(person_id)]
        updated['person'] = ','.join(ids)
    return urlencode({k: v for k, v in updated.items() if v and v != '0'})


def register_filters(app):
    """Register all template filters on the Flask app."""
    app.template_filter('format_date')(format_date)
    app.template_filter('cleanup')(cleanup)
    app.template_filter('safe_float')(safe_float)
    app.template_filter('format_shutter')(format_shutter)
    app.template_filter('urlencode_without')(urlencode_without)
    app.template_filter('urlencode_with')(urlencode_with)
    app.template_filter('js_escape')(js_escape)
    app.template_filter('urlencode_remove_person')(urlencode_remove_person)
