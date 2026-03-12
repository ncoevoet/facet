"""
Metrics reporting for Facet batch processing.
"""

import logging
import time

logger = logging.getLogger("facet.metrics")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

class MetricsReporter:
    """
    Compact metrics reporting for batch processing progress.

    Prints periodic progress lines and final summary report.
    """

    def __init__(self, total_images, config=None):
        """
        Initialize metrics reporter.

        Args:
            total_images: Total number of images to process
            config: Optional config dict with print_interval setting
        """
        self.total_images = total_images
        self.start_time = time.time()
        self.last_print_time = self.start_time

        # Configuration
        if config is None:
            config = {}
        auto_tuning = config.get('auto_tuning', {})
        self.print_interval = auto_tuning.get('metrics_print_interval_seconds', 30)

        # Accumulated metrics
        self.metrics_history = []
        self.peak_memory_gb = 0.0
        self.peak_gpu_memory_gb = 0.0
        self.min_workers = float('inf')
        self.max_workers = 0
        self.min_batch_size = float('inf')
        self.max_batch_size = 0
        self.total_io_bytes = 0

    def update(self, processor_metrics, resource_metrics=None, num_workers=None, batch_size=None):
        """
        Update metrics and print progress if interval elapsed.

        Args:
            processor_metrics: Dict from BatchProcessor.get_metrics()
            resource_metrics: Optional dict from ResourceMonitor.get_metrics()
            num_workers: Current number of workers
            batch_size: Current batch size
        """
        current_time = time.time()

        # Track peaks and ranges
        if resource_metrics:
            mem_gb = resource_metrics.get('process_memory_gb', 0)
            gpu_gb = resource_metrics.get('gpu_memory_allocated_gb', 0)
            self.peak_memory_gb = max(self.peak_memory_gb, mem_gb)
            self.peak_gpu_memory_gb = max(self.peak_gpu_memory_gb, gpu_gb)

        if num_workers is not None:
            self.min_workers = min(self.min_workers, num_workers)
            self.max_workers = max(self.max_workers, num_workers)

        if batch_size is not None:
            self.min_batch_size = min(self.min_batch_size, batch_size)
            self.max_batch_size = max(self.max_batch_size, batch_size)

        # Track I/O
        self.total_io_bytes = processor_metrics.get('total_bytes_loaded', 0)

        # Print if interval elapsed
        if current_time - self.last_print_time >= self.print_interval:
            self._print_progress(processor_metrics, resource_metrics, num_workers, batch_size)
            self.last_print_time = current_time

    def _print_progress(self, processor_metrics, resource_metrics, num_workers, batch_size):
        """Print compact single-line progress."""
        elapsed = time.time() - self.start_time
        processed = processor_metrics.get('images_processed', 0)
        throughput = processed / elapsed if elapsed > 0 else 0

        # Build progress line
        # Format: [2000/5000] 4.2 img/s | I/O: 42 MB/s | Q: 8/32 | W: 6 | Mem: 12.3G | batch: 16
        parts = [f"[{processed}/{self.total_images}]", f"{throughput:.1f} img/s"]

        if resource_metrics:
            io_rate = resource_metrics.get('io_read_bytes_sec', 0) / (1024**2)
            parts.append(f"I/O: {io_rate:.0f} MB/s")

            mem_gb = resource_metrics.get('process_memory_gb', 0)
            parts.append(f"Mem: {mem_gb:.1f}G")

        queue_timeouts = processor_metrics.get('queue_timeouts', 0)
        parts.append(f"Q-stalls: {queue_timeouts}")

        if num_workers is not None:
            parts.append(f"W: {num_workers}")

        if batch_size is not None:
            parts.append(f"batch: {batch_size}")

        logger.info(" | ".join(parts))

    def print_summary(self, processor_metrics, resource_metrics=None):
        """Print final summary report."""
        elapsed = time.time() - self.start_time
        processed = processor_metrics.get('images_processed', 0)
        throughput = processed / elapsed if elapsed > 0 else 0

        # Format elapsed time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        if minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"

        logger.info("Batch Processing Complete")
        logger.info("Total: %d images in %s (%.1f img/s)", processed, time_str, throughput)

        # I/O stats
        io_gb = self.total_io_bytes / (1024**3)
        io_rate = self.total_io_bytes / elapsed / (1024**2) if elapsed > 0 else 0
        logger.info("I/O: %.0f MB/s avg | %.1f GB total", io_rate, io_gb)

        # Worker stats
        if self.min_workers != float('inf'):
            if self.min_workers == self.max_workers:
                logger.info("Workers: %d", self.min_workers)
            else:
                logger.info("Workers: min %d, max %d", self.min_workers, self.max_workers)

        # Batch size stats
        if self.min_batch_size != float('inf'):
            if self.min_batch_size == self.max_batch_size:
                logger.info("Batch size: %d", self.min_batch_size)
            else:
                logger.info("Batch size: min %d, max %d", self.min_batch_size, self.max_batch_size)

        # Queue timeouts
        queue_timeouts = processor_metrics.get('queue_timeouts', 0)
        timeout_pct = (queue_timeouts / max(1, processed)) * 100
        logger.info("Queue stalls: %d total (%.1f%%)", queue_timeouts, timeout_pct)

        # Memory peaks
        logger.info("Memory peak: %.1f GB | GPU peak: %.1f GB", self.peak_memory_gb, self.peak_gpu_memory_gb)


