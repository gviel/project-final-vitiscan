import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_registry import SUPPORTED_MODELS, build_model, get_device


def test_get_device():
    device = get_device()
    assert str(device) in ("cpu", "cuda", "mps")


def test_build_model_resnet18():
    device = get_device()
    model = build_model("resnet18", num_classes=7, device=device, freeze_base=True, unfreeze_layer="layer4")
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    assert trainable > 0


def test_build_model_efficientnet():
    device = get_device()
    model = build_model("efficientnet_b0", num_classes=7, device=device, freeze_base=False)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    assert trainable == total  # fine-tuning complet : tout est trainable


def test_unsupported_model_raises():
    import pytest
    with pytest.raises(ValueError):
        build_model("not_a_real_model", num_classes=7, device=get_device())
