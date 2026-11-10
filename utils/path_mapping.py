"""Translate database paths with the same boundary rules in viewer and CLI."""
import os


def mapped_disk_path(db_path, path_mapping):
    for prefix_from, prefix_to in path_mapping.items():
        for path, prefix in ((db_path, prefix_from),
                             (db_path.replace('\\', '/'), prefix_from.replace('\\', '/'))):
            if path == prefix or path.startswith(prefix + '/') or path.startswith(prefix + '\\'):
                return (prefix_to + path[len(prefix):]).replace('\\', os.sep).replace('/', os.sep)
    return db_path.replace('\\', os.sep).replace('/', os.sep)
