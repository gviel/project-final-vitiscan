"""Préparation et chargement du dataset de feuilles de vigne malades.

Deux sources sont supportées (--dataset-name), sur le modèle des notebooks de référence
(notebooks/CNN_model_FT.ipynb pour inrae, notebooks/CNN_model.ipynb pour kaggle - archivé, plus
utilisé mais gardé fonctionnel) :

- "inrae" (par défaut, recommandé - cf. specs.md) : classes déséquilibrées (la classe "sain" est
  ramenée à 350 images max) puis split déterministe train/val/test (70/15/15, seed=42) à partir de
  data-inrae/raw_data_inrae/<classe>/*.jpg. Si data-inrae/organized_data_inrae/{train,val,test}
  existe déjà (généré précédemment, ou zip déjà extrait), il est réutilisé tel quel. Le zip peut
  aussi être téléchargé depuis s3://<TRAINING_S3_BUCKET>/data-inrae/dataset_inrae.zip si absent en
  local (cf. --s3-bucket / AWS_* dans .env).
- "kaggle" (archivé) : dataset téléchargé depuis --dataset-url, structure imbriquée
  (train/train/<classe>) à réorganiser après extraction.
"""
import os
import random
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional

import boto3
import requests
import torch
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder
from tqdm import tqdm

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


# ------------------------------------------------------------------ Kaggle dataset (archivé)

def _clean_kaggle_dirs(data_dir: str) -> None:
    for d in (f"{data_dir}/train", f"{data_dir}/test", f"{data_dir}/train__", f"{data_dir}/test__"):
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Deleted: {d}")


def _reorganize_kaggle_dataset(data_dir: str) -> List[str]:
    """Normalise les noms de classes et supprime la redondance train/train -> train."""
    labels = set()

    for split in ("train", "test"):
        data_root_path = Path(f"{data_dir}/{split}/{split}")
        if not data_root_path.is_dir():
            continue

        for dir_label in data_root_path.iterdir():
            new_label = (
                dir_label.name.replace("Grape ", "").replace(" leaf", "").replace("_leaf", "")
                .replace(" disease", "").replace(" ", "_").lower()
            )
            labels.add(new_label)
            new_dir_label = dir_label.parent / new_label
            if not new_dir_label.exists():
                shutil.move(str(dir_label), str(new_dir_label))

        tmp_dir = f"{data_dir}/{split}__"
        shutil.move(str(data_root_path), tmp_dir)
        shutil.rmtree(str(data_root_path.parent))
        shutil.move(tmp_dir, f"{data_dir}/{split}")

    return sorted(labels)


def _download_kaggle_zip(data_dir: str, url: str) -> str:
    data_zip_path = f"{data_dir}/kaggle_dataset.zip"
    if os.path.exists(data_zip_path):
        print(f"File already exists: {data_zip_path} - skipping download.")
        return data_zip_path

    print(f"Downloading dataset to {data_zip_path}...")
    response = requests.get(url, stream=True, allow_redirects=True)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))

    with open(data_zip_path, "wb") as f, tqdm(desc=data_zip_path, total=total_size, unit="B", unit_scale=True) as bar:
        for chunk in response.iter_content(chunk_size=8192):
            bar.update(f.write(chunk))

    return data_zip_path


def _prepare_kaggle_dataset(data_dir: str, dataset_url: str) -> List[str]:
    if os.path.exists(f"{data_dir}/train") and os.path.exists(f"{data_dir}/test"):
        print(f"{data_dir}: dataset already prepared, skipping.")
        return sorted(d.name for d in Path(f"{data_dir}/train").iterdir() if d.is_dir())

    data_zip_path = _download_kaggle_zip(data_dir, dataset_url)
    _clean_kaggle_dirs(data_dir)

    print(f"Extracting {data_zip_path}...")
    with zipfile.ZipFile(data_zip_path, "r") as zip_ref:
        zip_ref.extractall(data_dir)

    labels = _reorganize_kaggle_dataset(data_dir)
    print(f"Labels found: {labels}")
    return labels


# ------------------------------------------------------------------ Inrae dataset

def _rebalance_and_split_raw_inrae(
    raw_data_dir: Path, organized_dir: Path, healthy_class: str = "sain", healthy_target: int = 350,
    splits: dict = None, seed: int = 42,
) -> List[str]:
    """
    Reproduit exactement la préparation faite dans notebooks/CNN_model_FT.ipynb :
    - la classe "sain" (sur-représentée) est ramenée à `healthy_target` images (échantillonnage
      aléatoire, seed fixe) avant le split - modifie raw_data_dir en place, comme le notebook.
    - split déterministe train/val/test par classe (mêmes ratios/seed que le notebook).
    """
    splits = splits or {"train": 0.7, "val": 0.15, "test": 0.15}
    random.seed(seed)

    healthy_dir = raw_data_dir / healthy_class
    if healthy_dir.is_dir():
        images = list(healthy_dir.glob("*"))
        if len(images) > healthy_target:
            to_delete = random.sample(images, len(images) - healthy_target)
            for img in to_delete:
                img.unlink()
            print(f"{healthy_class}: {len(to_delete)} image(s) supprimée(s) (rééquilibrage à {healthy_target})")

    if organized_dir.exists():
        shutil.rmtree(organized_dir)
    for split in splits:
        for class_dir in raw_data_dir.iterdir():
            if class_dir.is_dir():
                (organized_dir / split / class_dir.name).mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    labels = []
    for class_dir in raw_data_dir.iterdir():
        if not class_dir.is_dir():
            continue
        labels.append(class_dir.name)

        images = [img for img in class_dir.iterdir() if img.suffix.lower() in IMAGE_SUFFIXES]
        random.shuffle(images)

        n_total = len(images)
        n_train = int(n_total * splits["train"])
        n_val = int(n_total * splits["val"])

        for img in images[:n_train]:
            shutil.copy(img, organized_dir / "train" / class_dir.name / img.name)
        for img in images[n_train:n_train + n_val]:
            shutil.copy(img, organized_dir / "val" / class_dir.name / img.name)
        for img in images[n_train + n_val:]:
            shutil.copy(img, organized_dir / "test" / class_dir.name / img.name)

    return sorted(labels)


def _download_inrae_zip_from_s3(dest_path: str, s3_bucket: str, s3_key: str) -> None:
    print(f"Téléchargement s3://{s3_bucket}/{s3_key} -> {dest_path} ...")
    s3 = boto3.client("s3")
    total = s3.head_object(Bucket=s3_bucket, Key=s3_key)["ContentLength"]
    with tqdm(total=total, unit="B", unit_scale=True, desc=dest_path) as bar:
        s3.download_file(s3_bucket, s3_key, dest_path, Callback=bar.update)


def _prepare_inrae_dataset(
    data_dir: str, dataset_zip_path: str, s3_bucket: str, s3_zip_key: str,
) -> List[str]:
    """
    Ordre de résolution :
    1. data_dir/organized_data_inrae/{train,val,test} déjà présent -> réutilisé tel quel.
    2. dataset_zip_path (local) présent -> extrait.
    3. absent en local -> téléchargé depuis s3://{s3_bucket}/{s3_zip_key} puis extrait.
    4. data_dir/raw_data_inrae présent -> reconstruit organized_data_inrae (rééquilibrage +
       split déterministe, identique à notebooks/CNN_model_FT.ipynb).
    """
    organized_dir = Path(data_dir) / "organized_data_inrae"

    if (organized_dir / "train").is_dir() and (organized_dir / "test").is_dir():
        print(f"{organized_dir}: dataset already prepared, skipping.")
        return sorted(d.name for d in (organized_dir / "train").iterdir() if d.is_dir())

    if not os.path.exists(dataset_zip_path):
        raw_dir = Path(data_dir) / "raw_data_inrae"
        if raw_dir.is_dir():
            print(f"{dataset_zip_path} absent, reconstruction depuis {raw_dir} (split déterministe)...")
            labels = _rebalance_and_split_raw_inrae(raw_dir, organized_dir)
            print(f"Labels found: {labels}")
            return sorted(d.name for d in (organized_dir / "train").iterdir() if d.is_dir())

        os.makedirs(os.path.dirname(dataset_zip_path) or ".", exist_ok=True)
        _download_inrae_zip_from_s3(dataset_zip_path, s3_bucket, s3_zip_key)

    # dataset_inrae.zip contient train/val/test directement à sa racine (pas de dossier
    # "organized_data_inrae/" wrapper à l'intérieur) - extraction directement dans organized_dir,
    # pas dans data_dir (bug trouvé en testant réellement le téléchargement S3 : jamais exercé
    # avant, le dataset était toujours déjà présent en local dans les sessions précédentes).
    print(f"Extracting {dataset_zip_path} to {organized_dir}...")
    with zipfile.ZipFile(dataset_zip_path, "r") as zip_ref:
        zip_ref.extractall(organized_dir)

    return sorted(d.name for d in (organized_dir / "train").iterdir() if d.is_dir())


# ------------------------------------------------------------------ Dispatch

def prepare_dataset(
    dataset_name: str, data_dir: str, dataset_url: str, dataset_zip_path: str,
    s3_bucket: str = "s3-vitiscan-data", s3_zip_key: str = "data-inrae/dataset_inrae.zip",
) -> List[str]:
    """Télécharge/extrait/organise le dataset choisi. Retourne la liste des classes trouvées."""
    os.makedirs(data_dir, exist_ok=True)

    if dataset_name == "inrae":
        return _prepare_inrae_dataset(data_dir, dataset_zip_path, s3_bucket, s3_zip_key)
    if dataset_name == "kaggle":
        return _prepare_kaggle_dataset(data_dir, dataset_url)

    raise ValueError(f"dataset_name inconnu: {dataset_name!r} (attendu: 'inrae' ou 'kaggle')")


def dataset_root_dir(dataset_name: str, data_dir: str) -> str:
    """Répertoire ImageFolder (train/val/test) selon le dataset - inrae ajoute organized_data_inrae/."""
    return f"{data_dir}/organized_data_inrae" if dataset_name == "inrae" else data_dir


# ------------------------------------------------------------------ Torch datasets/loaders

def create_transforms(dataset_name: str) -> transforms.Compose:
    """
    Augmentation d'entraînement propre à chaque dataset, fidèle aux notebooks de référence :
    - inrae (CNN_model_FT.ipynb) : flips + rotation aléatoire.
    - kaggle (CNN_model.ipynb, archivé) : ColorJitter.
    """
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

    if dataset_name == "inrae":
        return transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.RandomRotation(degrees=(-45, 45)),
            transforms.ToTensor(),
            normalize,
        ])

    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ColorJitter(brightness=0.5, contrast=0.5),
        transforms.ToTensor(),
        normalize,
    ])


def create_test_transforms() -> transforms.Compose:
    """Pipeline sans augmentation aléatoire, pour val/test (identique pour les deux datasets)."""
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


def prepare_datasets(data_dir: str, train_transform, test_transform, train_split: float = 0.8):
    """
    Prépare train/val/test. Si un dossier val/ existe déjà (dataset inrae : toujours vrai), il est
    utilisé directement ; sinon (dataset kaggle) le train/ est splitté en train/val (80/20, comme
    dans notebooks/CNN_model.ipynb).
    """
    train_root = Path(f"{data_dir}/train")
    full_train_dataset = ImageFolder(root=train_root, transform=train_transform)
    class_names = full_train_dataset.classes

    val_root = Path(f"{data_dir}/val")
    if val_root.is_dir():
        train_dataset = full_train_dataset
        val_dataset = ImageFolder(root=val_root, transform=test_transform)
    else:
        train_size = int(train_split * len(full_train_dataset))
        val_size = len(full_train_dataset) - train_size
        train_dataset, val_dataset = torch.utils.data.random_split(full_train_dataset, [train_size, val_size])

    test_dataset = ImageFolder(root=Path(f"{data_dir}/test"), transform=test_transform)

    print(f"Train dataset: {len(train_dataset)} images")
    print(f"Validation dataset: {len(val_dataset)} images")
    print(f"Test dataset: {len(test_dataset)} images")
    print(f"Classes: {class_names}")

    return train_dataset, val_dataset, test_dataset, class_names


def create_dataloaders(train_dataset, val_dataset, test_dataset, batch_size: int = 32):
    return (
        DataLoader(train_dataset, batch_size=batch_size, shuffle=True),
        DataLoader(val_dataset, batch_size=batch_size),
        DataLoader(test_dataset, batch_size=batch_size),
    )
