"""Factory générique de modèles CNN pour le fine-tuning des maladies de la vigne.

Remplace les fonctions dédiées resnet18/resnet34 de l'ancien scripts/model.py par une
seule fonction générique s'appuyant sur torchvision.models.get_model(), ce qui permet de
couvrir tous les modèles déclarés dans config.yml (resnet18/34/50, efficientnet_b0/b1/b2,
mobilenet_v2) sans dupliquer de code par architecture.
"""
import torch
import torch.nn as nn
from torchvision import models

SUPPORTED_MODELS = (
    "resnet18", "resnet34", "resnet50",
    "efficientnet_b0", "efficientnet_b1", "efficientnet_b2",
    "mobilenet_v2",
)


def get_device() -> torch.device:
    """Sélectionne le meilleur device disponible (CUDA, MPS, ou CPU)."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
    print(f"Using {device} device")
    return device


def _replace_classifier_head(model: nn.Module, num_classes: int) -> None:
    """
    Remplace la dernière couche de classification par une nn.Linear(*, num_classes).

    Les architectures torchvision suivent en pratique deux conventions :
    - ResNet : attribut `.fc` (nn.Linear)
    - EfficientNet / MobileNet : attribut `.classifier` (nn.Sequential dont le dernier
      élément est un nn.Linear)
    """
    if hasattr(model, "fc"):
        model.fc = nn.Linear(model.fc.in_features, num_classes)
        return

    if hasattr(model, "classifier"):
        classifier = model.classifier
        if isinstance(classifier, nn.Sequential):
            last = classifier[-1]
            classifier[-1] = nn.Linear(last.in_features, num_classes)
        else:
            model.classifier = nn.Linear(classifier.in_features, num_classes)
        return

    raise NotImplementedError(f"Architecture non supportée pour le remplacement de la tête de classification: {type(model).__name__}")


def build_model(
    model_name: str,
    num_classes: int,
    device: torch.device,
    freeze_base: bool = True,
    unfreeze_layer: str | None = None,
) -> nn.Module:
    """
    Crée un modèle pré-entraîné (ImageNet) prêt pour le transfer learning / fine-tuning.

    Args:
        model_name: un des SUPPORTED_MODELS
        num_classes: nombre de classes à prédire
        device: device torch cible
        freeze_base: si True, gèle tout le réseau sauf la nouvelle tête (+ unfreeze_layer si fourni) ;
                     si False, fine-tuning complet (tous les paramètres entraînables)
        unfreeze_layer: sous-chaîne du nom d'un bloc à dégeler en plus de la tête (ex: "layer4"),
                        utilisé seulement si freeze_base=True

    Returns:
        model (déplacé sur `device`, prêt pour l'entraînement)
    """
    if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Modèle inconnu: {model_name}. Choix possibles: {SUPPORTED_MODELS}")

    model = models.get_model(model_name, weights="DEFAULT")
    _replace_classifier_head(model, num_classes)

    if freeze_base:
        for param in model.parameters():
            param.requires_grad = False
        for name, param in model.named_parameters():
            if (unfreeze_layer and unfreeze_layer in name) or "fc" in name or "classifier" in name:
                param.requires_grad = True
    # sinon (freeze_base=False) : fine-tuning complet, tous les params restent trainable

    model = model.to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Model: {model_name} | device={device} | trainable params: {trainable:,} / {total:,}")

    return model
