"""Tests for utils._lazy thread-safe lazy imports."""

import threading

from utils._lazy import ensure_cv2, ensure_pil


class TestEnsureCv2:
    def test_returns_cv2_module(self):
        cv2 = ensure_cv2()
        assert hasattr(cv2, "imread")

    def test_returns_same_instance(self):
        assert ensure_cv2() is ensure_cv2()

    def test_thread_safe(self):
        results = []

        def load():
            results.append(ensure_cv2())

        threads = [threading.Thread(target=load) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)


class TestEnsurePil:
    def test_returns_image_and_imageops(self):
        Image, ImageOps = ensure_pil()
        assert hasattr(Image, "open")
        assert hasattr(ImageOps, "exif_transpose")

    def test_returns_same_instances(self):
        a = ensure_pil()
        b = ensure_pil()
        assert a[0] is b[0]
        assert a[1] is b[1]

    def test_thread_safe(self):
        results = []

        def load():
            results.append(ensure_pil())

        threads = [threading.Thread(target=load) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r[0] is results[0][0] for r in results)
