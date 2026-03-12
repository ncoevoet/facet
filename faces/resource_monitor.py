"""
Resource monitoring for face processing.
"""

import logging
import threading
import time

logger = logging.getLogger("facet.face_resources")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

class FaceResourceMonitor(threading.Thread):
    """
    Monitor resources and adjust batch size during face processing.

    Simplified version of ResourceMonitor from batch_processor.py.
    """

    def __init__(self, processor, config):
        """
        Initialize the resource monitor.

        Args:
            processor: FaceProcessor instance to monitor
            config: Config dict with auto_tuning settings
        """
        super().__init__(daemon=True)
        self.processor = processor
        self.stop_event = threading.Event()

        # Configuration with defaults
        auto_tuning = config.get('auto_tuning', {})
        self.enabled = auto_tuning.get('enabled', True)
        self.memory_limit = auto_tuning.get('memory_limit_percent', 80)
        self.min_batch = auto_tuning.get('min_batch_size', 8)
        self.interval = auto_tuning.get('monitor_interval_seconds', 5)

    def run(self):
        """Main monitoring loop."""
        if not HAS_PSUTIL or not self.enabled:
            return

        while not self.stop_event.is_set():
            time.sleep(self.interval)

            if self.stop_event.is_set():
                break

            try:
                mem = psutil.virtual_memory().percent
                if mem > self.memory_limit:
                    # Reduce batch size by 25%
                    with self.processor.config_lock:
                        old_batch = self.processor.batch_size
                        new_batch = max(self.min_batch, int(old_batch * 0.75))
                        if new_batch != old_batch:
                            self.processor.batch_size = new_batch
                            logger.warning("Memory at %.1f%%, reducing batch to %d", mem, new_batch)
            except Exception:
                pass  # Don't crash the monitor

    def stop(self):
        """Stop the monitoring thread."""
        self.stop_event.set()


