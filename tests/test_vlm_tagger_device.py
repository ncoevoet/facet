"""Device-release behaviour of VLMTagger on unload and OOM fallback.

Guards the mps memory-release fix (GitHub discussion #159): unload must route
through utils.device.clear_device_cache instead of torch.cuda.empty_cache, must
never call model.cpu() (a transient full second copy under unified memory), and
tag_batch's OOM fallback must recognise the RuntimeError MPS raises instead of
torch.cuda.OutOfMemoryError.
"""

from unittest import mock

import pytest

import PIL.Image

from models.vlm_tagger import VLMTagger


def _image():
    return PIL.Image.new("RGB", (4, 4), color=(1, 2, 3))


class _FakeModel:
    def __init__(self, device):
        self.device = device
        self.cpu_called = False

    def cpu(self):
        self.cpu_called = True
        return self


class _FakeProcessor:
    pass


class TestUnload:
    def test_clears_device_cache_with_model_device_and_skips_cpu_copy(self):
        tagger = VLMTagger({"family": "qwen2_5"}, None)
        tagger.model = _FakeModel(device="mps")
        tagger.processor = _FakeProcessor()

        with mock.patch("models.vlm_tagger.clear_device_cache") as fake_clear:
            fake_model = tagger.model
            tagger.unload()

        assert fake_model.cpu_called is False
        fake_clear.assert_called_once_with("mps")
        assert tagger.model is None
        assert tagger.processor is None


class TestTagBatchOomFallback:
    @pytest.fixture(autouse=True)
    def _torch(self):
        # tag_batch imports torch before it reaches the fallback under test.
        pytest.importorskip("torch")

    def test_mps_oom_falls_back_to_per_image_tagging(self):
        tagger = VLMTagger({"family": "qwen2_5"}, None)
        tagger.model = _FakeModel(device="mps")
        tagger.processor = _FakeProcessor()
        tagger.batch_size = 2

        images = [_image(), _image()]

        def _raise_oom(sub_batch, max_tags):
            raise RuntimeError("MPS backend out of memory (MPS allocated: 4.50 GB)")

        with mock.patch.object(tagger, "_tag_sub_batch", side_effect=_raise_oom), \
                mock.patch.object(tagger, "tag_image", return_value=["cat"]) as fake_tag_image, \
                mock.patch("models.vlm_tagger.clear_device_cache") as fake_clear:
            results = tagger.tag_batch(images, max_tags=5)

        assert results == [["cat"], ["cat"]]
        assert fake_tag_image.call_count == 2
        fake_clear.assert_called_with("mps")

    def test_non_oom_runtime_error_propagates(self):
        tagger = VLMTagger({"family": "qwen2_5"}, None)
        tagger.model = _FakeModel(device="mps")
        tagger.processor = _FakeProcessor()
        tagger.batch_size = 2

        def _raise_other(sub_batch, max_tags):
            raise RuntimeError("shape mismatch")

        with mock.patch.object(tagger, "_tag_sub_batch", side_effect=_raise_other):
            with pytest.raises(RuntimeError, match="shape mismatch"):
                tagger.tag_batch([_image(), _image()], max_tags=5)
