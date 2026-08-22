"""
Resource monitoring for Facet batch processing.
"""

import logging
import threading
import time

from utils.system_memory import effective_memory

logger = logging.getLogger("facet.resources")

import torch

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

class MultiPassResourceMonitor(threading.Thread):
    """
    Lightweight daemon thread that monitors effective RAM (host or cgroup
    limit, whichever binds -- see utils.system_memory.effective_memory) and
    auto-tunes the chunk size of ChunkedMultiPassProcessor.

    - High RAM (>85%): immediately reduces chunk size and evicts CPU-cached models
    - A chunk whose HIGH-WATER mark stayed under 65%: grows the next chunk
    - Tracks adjustments for summary reporting

    Growth is decided per chunk rather than per reading because a chunk is not
    one reading. Between two passes every model is unloaded, so usage drops
    almost to the floor, and a monitor that samples the trough concludes it has
    room the chunk never had. Measured in an 8 GiB container, the trough
    readings alone grew the chunk 10 -> 500 during the first chunk; the second
    then tried to decode every remaining photo at once and was OOM-killed.
    """

    ADJUSTMENT_VERBS = {'reduce': 'reduced', 'increase': 'increased'}

    def __init__(self, multi_pass_processor, config=None):
        super().__init__(daemon=True)
        self.processor = multi_pass_processor
        self.stop_event = threading.Event()

        if config is None:
            config = {}
        proc_config = config.get('processing', {})
        auto_tuning = proc_config.get('auto_tuning', {})

        self.interval = auto_tuning.get('monitor_interval_seconds', 5)
        self.high_threshold = auto_tuning.get('memory_limit_percent', 85)
        self.low_threshold = self.high_threshold - 20  # default 65

        # Tracking. The peak is the high-water mark since the last chunk
        # boundary -- what the chunk actually had to survive.
        self._peak_percent = 0.0
        self.adjustments = []  # list of (direction, old_size, new_size)

    def run(self):
        if not self.processor.auto_tuning_enabled:
            return

        while not self.stop_event.is_set():
            # Sleep in small increments for quick shutdown
            for _ in range(int(self.interval * 10)):
                if self.stop_event.is_set():
                    return
                time.sleep(0.1)

            if self.stop_event.is_set():
                break

            try:
                mem_percent = effective_memory().percent
                self._peak_percent = max(self._peak_percent, mem_percent)

                if mem_percent > self.high_threshold:
                    old = self.processor.chunk_size
                    if self.processor.reduce_chunk_size():
                        self._record('reduce', old, mem_percent)
                    # Evict CPU-cached models to free RAM
                    mm = getattr(self.processor, 'model_manager', None)
                    if mm is not None:
                        evict = getattr(mm, 'evict_cpu_cache', None)
                        if evict:
                            evict()

            except Exception:
                pass  # Don't crash the monitor

    def note_chunk_complete(self):
        """Decide from the finished chunk's peak whether the next may be larger.

        Called once per chunk by ``ChunkedMultiPassProcessor``, which is the
        only moment a size change is safe: the images the current chunk was
        sized for have been released, and nothing has been decoded for the
        next one yet.

        A peak of zero means no reading was taken -- a chunk shorter than the
        monitor's interval -- and the absence of a measurement is not a
        measurement of headroom, so it grows nothing.
        """
        peak, self._peak_percent = self._peak_percent, 0.0
        if not peak or peak >= self.low_threshold:
            return
        old = self.processor.chunk_size
        if self.processor.increase_chunk_size():
            self._record('increase', old, peak)

    def _record(self, direction, old_size, percent):
        """Log an adjustment and keep it for the run summary.

        These used to be recorded silently and printed only by
        ``_print_summary``, which never runs when the process is OOM-killed --
        so the tuning that caused the kill left no trace in the log at all.
        """
        new_size = self.processor.chunk_size
        self.adjustments.append((direction, old_size, new_size))
        logger.info("  Chunk size %s: %d -> %d (memory %.1f%% of the effective limit)",
                    self.ADJUSTMENT_VERBS[direction], old_size, new_size, percent)

    def stop(self):
        self.stop_event.set()


class ResourceMonitor:
    """
    Dedicated thread for monitoring system resources and triggering auto-tuning.

    Collects:
    - CPU usage (total + per-core) via psutil.cpu_percent()
    - Memory (available GB, process RSS) via utils.system_memory.effective_memory()
    - GPU memory (allocated GB) via torch.cuda.memory_allocated()
    - I/O rate (bytes/sec) via psutil.disk_io_counters()
    - Queue depths and processing throughput

    Auto-tuning capabilities:
    - GPU batch size: Reduced when VRAM exceeds limit
    """

    MAX_MEMORY_WAIT_SECONDS = 10
    MEMORY_RECOVERY_TARGET_PERCENT = 75

    def __init__(self, batch_processor, config=None):
        """
        Initialize the resource monitor.

        Args:
            batch_processor: BatchProcessor instance to monitor
            config: Optional config dict with auto_tuning settings
        """
        self.processor = batch_processor
        self.stop_event = threading.Event()
        self.thread = None

        # Configuration with defaults - support both old and new config format
        if config is None:
            config = {}

        # Try new 'processing' format first, fall back to old 'auto_tuning'
        proc_config = config.get('processing', {})
        auto_tuning = proc_config.get('auto_tuning', config.get('auto_tuning', {}))

        self.monitor_interval = auto_tuning.get('monitor_interval_seconds', 5)
        self.min_workers = auto_tuning.get('min_processing_workers', 1)
        self.max_workers = auto_tuning.get('max_processing_workers', 24)
        self.min_batch_size = auto_tuning.get('min_gpu_batch_size', 2)
        self.memory_limit_percent = auto_tuning.get('memory_limit_percent', 85)
        self.cpu_target_percent = auto_tuning.get('cpu_target_percent', 80)

        # Metrics storage (thread-safe)
        self._metrics_lock = threading.Lock()
        self.resource_metrics = {
            'cpu_percent': 0.0,
            'memory_percent': 0.0,
            'memory_available_gb': 0.0,
            'process_memory_gb': 0.0,
            'gpu_memory_allocated_gb': 0.0,
            'gpu_memory_total_gb': 0.0,
            'io_read_bytes_sec': 0.0,
            'io_write_bytes_sec': 0.0,
            'samples': [],  # Rolling window for averaging
        }

        # Last I/O counters for rate calculation
        self._last_io_counters = None
        self._last_io_time = None

    def start(self):
        """Start the monitoring thread."""
        if not HAS_PSUTIL:
            return

        self.stop_event.clear()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the monitoring thread."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)

    def get_metrics(self):
        """Get current resource metrics (thread-safe)."""
        with self._metrics_lock:
            return self.resource_metrics.copy()

    def _monitor_loop(self):
        """Main monitoring loop running in dedicated thread."""
        while not self.stop_event.is_set():
            try:
                self._collect_metrics()
                self._apply_tuning()
            except Exception:
                pass  # Don't crash the monitor on errors

            # Sleep in small increments to allow quick shutdown
            for _ in range(int(self.monitor_interval * 10)):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)

    def _collect_metrics(self):
        """Collect current system resource metrics."""
        metrics = {}

        # CPU usage
        metrics['cpu_percent'] = psutil.cpu_percent(interval=None)

        # Memory usage
        mem = effective_memory()
        metrics['memory_percent'] = mem.percent
        metrics['memory_available_gb'] = mem.available / (1024**3)

        # Process memory
        try:
            process = psutil.Process()
            metrics['process_memory_gb'] = process.memory_info().rss / (1024**3)
        except Exception:
            metrics['process_memory_gb'] = 0.0

        # GPU memory (if CUDA available)
        if torch.cuda.is_available():
            metrics['gpu_memory_allocated_gb'] = torch.cuda.memory_allocated() / (1024**3)
            try:
                total = torch.cuda.get_device_properties(0).total_memory
                metrics['gpu_memory_total_gb'] = total / (1024**3)
            except Exception:
                metrics['gpu_memory_total_gb'] = 0.0
        else:
            metrics['gpu_memory_allocated_gb'] = 0.0
            metrics['gpu_memory_total_gb'] = 0.0

        # I/O rate calculation
        try:
            io_counters = psutil.disk_io_counters()
            current_time = time.time()

            if self._last_io_counters is not None and self._last_io_time is not None:
                time_delta = current_time - self._last_io_time
                if time_delta > 0:
                    metrics['io_read_bytes_sec'] = (
                        io_counters.read_bytes - self._last_io_counters.read_bytes
                    ) / time_delta
                    metrics['io_write_bytes_sec'] = (
                        io_counters.write_bytes - self._last_io_counters.write_bytes
                    ) / time_delta

            self._last_io_counters = io_counters
            self._last_io_time = current_time
        except Exception:
            metrics['io_read_bytes_sec'] = 0.0
            metrics['io_write_bytes_sec'] = 0.0

        # Update stored metrics
        with self._metrics_lock:
            self.resource_metrics.update(metrics)
            # Keep rolling window of samples (last 12 = 1 minute at 5s interval)
            self.resource_metrics['samples'].append({
                'time': time.time(),
                **metrics
            })
            if len(self.resource_metrics['samples']) > 12:
                self.resource_metrics['samples'].pop(0)

    def _apply_tuning(self):
        """Apply auto-tuning based on current metrics.

        Reduces the GPU batch size when memory exceeds the configured limit.
        (Multi-pass RAM chunk tuning lives in MultiPassResourceMonitor.)
        """
        metrics = self.get_metrics()
        memory_usage = metrics.get('memory_percent', 0)

        # Memory limit check (graceful reduction)
        if memory_usage > self.memory_limit_percent:
            self._graceful_memory_reduction(memory_usage)

    def _graceful_memory_reduction(self, current_usage):
        """Handle memory limit exceeded by reducing batch size."""
        logger.warning("Memory usage at %.1f%%, reducing batch size...", current_usage)

        # Reduce batch size by 25%
        current_batch = self.processor.batch_size
        new_batch = max(self.min_batch_size, int(current_batch * 0.75))

        if new_batch != current_batch:
            self.processor.batch_size = new_batch
            logger.warning("Batch size reduced: %d -> %d", current_batch, new_batch)

        wait_count = 0
        while wait_count < self.MAX_MEMORY_WAIT_SECONDS:
            if self.stop_event.wait(1):
                return
            if effective_memory().percent < self.MEMORY_RECOVERY_TARGET_PERCENT:
                break
            wait_count += 1


