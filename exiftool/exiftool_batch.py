"""
ExifTool Batch Module

Provides batch EXIF extraction using ExifTool with chunked subprocess calls.
Processes files in chunks of 50 to avoid command-line limits and enable timeout handling.
"""

import atexit
import json
import logging
import math
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger("facet.exiftool")

STAY_OPEN_TIMEOUT_SECONDS = 30


class ExifToolBatch:
    """
    Persistent ExifTool process using -stay_open mode.

    Avoids subprocess spawn overhead per image by keeping ExifTool running.
    Commands are sent via stdin, results read from stdout.
    """

    def __init__(self):
        self.process = None
        self._lock = threading.Lock()
        self._start_process()
        atexit.register(self.close)

    def _start_process(self):
        """Start the persistent ExifTool process."""
        try:
            self.process = subprocess.Popen(
                ['exiftool', '-stay_open', 'True', '-@', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
        except FileNotFoundError:
            # ExifTool not installed
            self.process = None

    def close(self):
        """Terminate the ExifTool process."""
        if self.process is not None:
            try:
                self.process.stdin.write('-stay_open\nFalse\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    def _kill_process(self):
        """Kill the current persistent process (used as the read watchdog)."""
        proc = self.process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def _restart(self):
        """Kill and re-spawn the persistent process after a failed round-trip."""
        self._kill_process()
        self.process = None
        self._start_process()

    def get_metadata(self, image_path):
        """
        Get EXIF metadata for a single image.

        Serializes the stdin write and stdout read of the shared persistent
        process behind a lock so concurrent loader threads can never consume
        each other's response (cross-photo EXIF corruption). A watchdog timer
        kills a dead or stalled process so the response loop can never hang;
        on any failure an empty dict is returned so the caller falls back to a
        fresh subprocess.

        Args:
            image_path: Path to the image file

        Returns:
            Dict with EXIF fields, or empty dict on failure
        """
        if self.process is None:
            return {}

        with self._lock:
            timer = threading.Timer(STAY_OPEN_TIMEOUT_SECONDS, self._kill_process)
            try:
                self.process.stdin.write(f'-j\n-n\n{image_path}\n-execute\n')
                self.process.stdin.flush()
                timer.start()

                output_lines = []
                while True:
                    line = self.process.stdout.readline()
                    if line == '':
                        timer.cancel()
                        self._restart()
                        return {}
                    if line.strip() == '{ready}':
                        break
                    output_lines.append(line)

                timer.cancel()
                if output_lines:
                    data = json.loads(''.join(output_lines))
                    if data:
                        return data[0]
                return {}
            except json.JSONDecodeError:
                # More specific than the ValueError branch below (JSONDecodeError
                # subclasses ValueError) — must be listed first or it is
                # unreachable. The process answered, just with unparsable
                # output, so there is no need to restart it.
                timer.cancel()
                return {}
            except (BrokenPipeError, OSError, ValueError):
                timer.cancel()
                self._restart()
                return {}

    def get_metadata_batch(self, image_paths, chunk_size=50, timeout_per_chunk=30):
        """
        Get EXIF metadata for multiple images, processing in chunks.

        Uses subprocess.run() per chunk for reliability instead of persistent process.
        Includes retry logic for failed chunks with doubled timeout.

        Args:
            image_paths: List of paths to image files
            chunk_size: Number of files to process per ExifTool call
            timeout_per_chunk: Seconds to wait per chunk before giving up

        Returns:
            Dict mapping path -> EXIF dict
        """
        if not image_paths:
            return {}

        results = {}
        paths_list = [str(p) for p in image_paths]
        total_chunks = (len(paths_list) + chunk_size - 1) // chunk_size
        success_chunks = 0
        failed_chunks = 0

        # Process in chunks using subprocess.run() for reliability
        for i in range(0, len(paths_list), chunk_size):
            chunk = paths_list[i:i + chunk_size]
            chunk_idx = i // chunk_size + 1
            chunk_success = False

            # Try up to 2 times: first with normal timeout, then with doubled timeout
            for attempt in range(2):
                current_timeout = timeout_per_chunk if attempt == 0 else timeout_per_chunk * 2
                try:
                    # Run exiftool as a subprocess for this chunk
                    result = subprocess.run(
                        ['exiftool', '-j', '-n'] + chunk,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=current_timeout
                    )

                    if result.returncode == 0 and result.stdout:
                        data = json.loads(result.stdout)
                        for item in data:
                            source = item.get('SourceFile')
                            if source:
                                results[str(Path(source).resolve())] = item
                        chunk_success = True
                        break  # Success, no retry needed

                except subprocess.TimeoutExpired:
                    if attempt == 0:
                        logger.warning("EXIF chunk %d/%d timed out (%d files), retrying with %ds timeout...", chunk_idx, total_chunks, len(chunk), current_timeout * 2)
                    else:
                        logger.error("EXIF chunk %d/%d failed after retry (%d files)", chunk_idx, total_chunks, len(chunk))
                    continue
                except Exception as e:
                    if attempt == 1:
                        logger.error("EXIF chunk %d/%d error: %s", chunk_idx, total_chunks, e)
                    continue

            if chunk_success:
                success_chunks += 1
            else:
                failed_chunks += 1

        # Print summary if there were any failures
        if failed_chunks > 0:
            success_rate = (success_chunks / total_chunks) * 100 if total_chunks > 0 else 0
            logger.warning("EXIF batch complete: %d/%d chunks succeeded (%.0f%%)", success_chunks, total_chunks, success_rate)

        return results


# Module-level singleton instance
_exiftool_instance = None


def get_exiftool():
    """Get or create the singleton ExifToolBatch instance."""
    global _exiftool_instance
    if _exiftool_instance is None:
        _exiftool_instance = ExifToolBatch()
    return _exiftool_instance


def parse_exif_data(raw_data):
    """
    Parse raw ExifTool output into standardized format.

    Args:
        raw_data: Dict from ExifTool JSON output

    Returns:
        Dict with standardized EXIF fields
    """
    def _safe_numeric(val):
        """Convert EXIF value to float, handling strings and rejecting non-finite values.

        A lens without electronic contacts (e.g. on a Canon EOS 600D) reports
        FNumber as N/0, which ExifTool surfaces as 'inf'. Storing that poisons
        downstream MIN/MAX aggregates (np.histogram rejects a non-finite range),
        so non-finite parses are dropped to None here.
        """
        if val is None:
            return None
        if isinstance(val, (int, float)):
            f = float(val)
        elif isinstance(val, str):
            try:
                f = float(val)
            except ValueError:
                return None
        else:
            return None
        return f if math.isfinite(f) else None

    return {
        'date_taken': raw_data.get('DateTimeOriginal') or raw_data.get('CreateDate'),
        'camera_model': raw_data.get('Model'),
        'lens_model': raw_data.get('LensModel') or raw_data.get('LensID'),
        'iso': _safe_numeric(raw_data.get('ISO')),
        'f_stop': _safe_numeric(raw_data.get('Aperture')),
        'shutter_speed': str(raw_data.get('ExposureTime')) if raw_data.get('ExposureTime') else None,
        'focal_length': _safe_numeric(raw_data.get('FocalLength')),
        'focal_length_35mm': _safe_numeric(raw_data.get('FocalLengthIn35mmFilm')),
        'gps_latitude': _safe_numeric(raw_data.get('GPSLatitude')),
        'gps_longitude': _safe_numeric(raw_data.get('GPSLongitude')),
    }


def get_exif_batch(image_paths, chunk_size=50, timeout_per_chunk=30):
    """
    Get EXIF data for multiple images using batch ExifTool.

    Args:
        image_paths: List of image paths (strings or Paths)
        chunk_size: Number of files per ExifTool call (default 50, use 500 for NAS)
        timeout_per_chunk: Seconds to wait per chunk (default 30, use 120 for NAS)

    Returns:
        Dict mapping path (as resolved string) -> standardized EXIF dict
    """
    if not image_paths:
        return {}

    # Get raw metadata using chunked subprocess calls
    exiftool = get_exiftool()
    raw_results = exiftool.get_metadata_batch(image_paths, chunk_size=chunk_size, timeout_per_chunk=timeout_per_chunk)

    # Parse into standardized format
    results = {}
    for path, raw_data in raw_results.items():
        results[path] = parse_exif_data(raw_data)

    return results


def get_exif_single(image_path):
    """
    Get EXIF data for a single image using batch ExifTool.

    Args:
        image_path: Path to image file

    Returns:
        Dict with standardized EXIF fields
    """
    exiftool = get_exiftool()
    if exiftool.process is None:
        return {
            'date_taken': None, 'camera_model': None, 'lens_model': None,
            'iso': None, 'f_stop': None, 'shutter_speed': None, 'focal_length': None,
            'focal_length_35mm': None
        }

    raw_data = exiftool.get_metadata(str(image_path))
    return parse_exif_data(raw_data)
