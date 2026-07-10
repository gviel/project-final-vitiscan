#!/usr/bin/env python3
"""
====================================================================================================
                            VITISCAN - Entraînement du modèle CNN
                  Classification de maladies de la vigne (transfer learning / fine-tuning)
====================================================================================================

Script paramétrable en ligne de commande, exécutable en local ou depuis un DAG Airflow
(cf. specs.md, section "Refactorer le code CDSD"). Fidèle à notebooks/CNN_model_FT.ipynb (dataset
inrae, notebook de référence utilisé pour entraîner le modèle actuellement en prod) et
notebooks/CNN_model.ipynb (dataset kaggle, archivé) : mêmes hyperparamètres par défaut, même
boucle d'entraînement (early stopping, métriques val+test, disease.json), mêmes conventions
MLflow (nom d'expérience, nom de modèle enregistré) - cf. docs/refactoring.md pour le détail des
écarts trouvés entre l'ancien scripts/ et les notebooks, corrigés ici.

Exemple (test rapide, peu d'epochs, peu de batches, pour valider que le pipeline tourne) :
    python train.py --epochs 1 --limit-batches 5 --dataset-name inrae

Exemple (entraînement complet, comme le notebook) :
    python train.py --model resnet18 --dataset-name inrae --epochs 25 --patience 5
"""
import argparse
import itertools
import json
import os
import tempfile
from pathlib import Path

import boto3
import matplotlib.pyplot as plt
import mlflow
import seaborn as sns
import torch
import torch.nn as nn
import torch.optim as optim
from dotenv import load_dotenv
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from data_utils import (
    create_dataloaders, create_test_transforms, create_transforms, dataset_root_dir,
    prepare_dataset, prepare_datasets,
)
from disease_labels import build_disease_json
from model_registry import SUPPORTED_MODELS, build_model, get_device

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entraînement du modèle CNN Vitiscan")

    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "resnet18"), choices=SUPPORTED_MODELS)
    parser.add_argument("--epochs", type=int, default=int(os.getenv("EPOCHS", "25")))
    parser.add_argument("--patience", type=int, default=int(os.getenv("PATIENCE", "5")), help="Early stopping (0 = désactivé)")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BATCH_SIZE", "32")))
    parser.add_argument("--learning-rate", type=float, default=float(os.getenv("LEARNING_RATE", "0.0001")))
    parser.add_argument("--weight-decay", type=float, default=float(os.getenv("WEIGHT_DECAY", "0.0001")))
    parser.add_argument("--train-split", type=float, default=float(os.getenv("TRAIN_SPLIT", "0.8")))
    parser.add_argument(
        "--freeze-base", type=lambda s: s.lower() != "false", default=os.getenv("FREEZE_BASE", "true"),
        help="true: gèle le réseau de base (+ unfreeze-layer) ; false: fine-tuning complet",
    )
    parser.add_argument(
        "--unfreeze-layer", default=os.getenv("UNFREEZE_LAYER", "layer4"),
        help="Bloc supplémentaire à dégeler quand --freeze-base=true (ex: layer4). "
             "Ajoute le suffixe _FINE_TUNING au nom d'expérience MLflow (comme le notebook).",
    )
    parser.add_argument(
        "--limit-batches", type=int, default=None,
        help="Limite le nombre de batches par epoch (tests rapides, cf. NB Important de specs.md)",
    )

    parser.add_argument("--dataset-name", default=os.getenv("DATASET_NAME", "inrae"), choices=("inrae", "kaggle"))
    parser.add_argument("--data-dir", default=os.getenv("DATA_DIR"), help="Défaut : ./data-<dataset-name>")
    parser.add_argument(
        "--dataset-url", default=os.getenv(
            "DATASET_URL", "https://www.kaggle.com/api/v1/datasets/download/codewithsk/grapes-leafs-disease-7-classes-plantcity-2025"
        ),
    )
    parser.add_argument("--dataset-zip-path", default=os.getenv("DATASET_ZIP_PATH"), help="Défaut : <data-dir>/dataset_inrae.zip")
    parser.add_argument(
        "--s3-bucket", default=os.getenv("TRAINING_S3_BUCKET", "s3-vitiscan-data"),
        help="Bucket données Vitiscan (dataset + disease.json) - distinct du bucket MLflow, implicite",
    )
    parser.add_argument(
        "--s3-inrae-zip-key", default=os.getenv("S3_INRAE_ZIP_KEY", "data-inrae/dataset_inrae.zip"),
        help="Utilisé en secours si le zip inrae est absent en local (cf. data_utils.prepare_dataset)",
    )

    parser.add_argument(
        "--experiment-name", default=os.getenv("EXPERIMENT_NAME", "Vitiscan_CNN_MLFlow"),
        help="Nom de base - le suffixe _FINE_TUNING est ajouté automatiquement (cf. --unfreeze-layer)",
    )
    parser.add_argument("--mlflow-uri", default=os.getenv("MLFLOW_URI", "https://gviel-mlflow37.hf.space/"))

    args = parser.parse_args()
    # `not args.x` (pas `is None`) : os.getenv("DATA_DIR") renvoie "" (chaîne vide, pas None) quand
    # la variable existe dans .env mais est laissée vide volontairement (cf. training/.env -
    # convention "vide = calculer le défaut ci-dessous"). Un simple `is None` ne le détecte pas,
    # laissant args.dataset_zip_path = "" (bug trouvé en testant réellement dag_train_model : ce
    # chemin vide fait échouer le téléchargement S3 avec une erreur trompeuse "Read-only file
    # system" - s3transfer résout le nom de fichier temporaire relatif à un dirname vide).
    if not args.data_dir:
        args.data_dir = f"./data-{args.dataset_name}"
    if not args.dataset_zip_path:
        args.dataset_zip_path = f"{args.data_dir}/dataset_inrae.zip"
    return args


def _limited(loader, limit_batches):
    return itertools.islice(loader, limit_batches) if limit_batches else loader


def _n_batches(loader, limit_batches):
    return min(limit_batches, len(loader)) if limit_batches else len(loader)


def run_epoch(model, loader, criterion, optimizer, device, train: bool, limit_batches=None):
    model.train() if train else model.eval()
    total_loss, correct, n_seen = 0.0, 0, 0

    context = torch.enable_grad() if train else torch.no_grad()
    with context:
        for images, labels in _limited(loader, limit_batches):
            images, labels = images.to(device), labels.to(device)

            if train:
                optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, labels)
            if train:
                loss.backward()
                optimizer.step()

            total_loss += loss.item()
            correct += (logits.argmax(dim=1) == labels).sum().item()
            n_seen += labels.size(0)

    return total_loss / max(1, _n_batches(loader, limit_batches)), correct / max(1, n_seen)


def evaluate_model_on_dataset(model, loader, device, limit_batches=None):
    model.eval()
    y_true, y_pred = [], []
    with torch.no_grad():
        for images, labels in _limited(loader, limit_batches):
            images, labels = images.to(device), labels.to(device)
            preds = model(images).argmax(dim=1)
            y_true.extend(labels.cpu().numpy())
            y_pred.extend(preds.cpu().numpy())
    accuracy = sum(int(t == p) for t, p in zip(y_true, y_pred)) / max(1, len(y_true))
    return accuracy, y_true, y_pred


def log_precision_recall_f1(dataset_type: str, y_true, y_pred) -> dict:
    results = {}
    for avg_mode in ("weighted", "macro"):
        results[avg_mode] = {}
        for name, fn in (("precision", precision_score), ("recall", recall_score), ("f1", f1_score)):
            value = fn(y_true, y_pred, average=avg_mode, zero_division=0)
            results[avg_mode][name] = value
            mlflow.log_metric(f"{dataset_type.capitalize()}_{name}_{avg_mode}", value)
    return results


def log_confusion_matrix(dataset_type: str, y_true, y_pred, class_names: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        cm = confusion_matrix(y_true, y_pred)
        plt.figure(figsize=(10, 8))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues")
        plt.xticks(ticks=range(len(class_names)), labels=class_names, rotation=45, ha="right")
        plt.yticks(ticks=range(len(class_names)), labels=class_names, rotation=0)
        plt.ylabel("True class")
        plt.xlabel("Predicted class")
        plt.title(f"Confusion matrix - {dataset_type}")
        plt.tight_layout()
        path = str(Path(tmp_dir, f"confusion_matrix_{dataset_type}.png"))
        plt.savefig(path, dpi=150)
        mlflow.log_artifact(path)
        plt.close()


def _upload_disease_json_to_s3(diseases: dict, dataset_name: str, s3_bucket: str) -> None:
    """Copie de référence indépendante d'un run précis, comme dans les notebooks (cellule dédiée)."""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir, f"disease-{dataset_name}.json")
            with path.open("w", encoding="utf-8") as f:
                json.dump(diseases, f, ensure_ascii=False)
            key = f"data-{dataset_name}/disease-{dataset_name}.json"
            boto3.client("s3").upload_file(Bucket=s3_bucket, Filename=str(path), Key=key)
            print(f"disease.json de référence uploadé sur s3://{s3_bucket}/{key}")
    except Exception as e:
        print(f"WARN: échec upload disease-{dataset_name}.json sur S3 (non bloquant): {e}")


def train_model(args: argparse.Namespace) -> dict:
    device = get_device()
    fine_tuning = args.freeze_base and bool(args.unfreeze_layer)
    experiment_name = f"{args.experiment_name}_FINE_TUNING" if fine_tuning else args.experiment_name

    print("=" * 80)
    print("VITISCAN - CNN MODEL TRAINING")
    print(f"model={args.model} dataset={args.dataset_name} epochs={args.epochs} patience={args.patience} "
          f"fine_tuning={fine_tuning} experiment={experiment_name}")
    print("=" * 80)

    print("\n[1/6] Dataset preparation...")
    prepare_dataset(args.dataset_name, args.data_dir, args.dataset_url, args.dataset_zip_path, args.s3_bucket, args.s3_inrae_zip_key)
    root_dir = dataset_root_dir(args.dataset_name, args.data_dir)

    print("\n[2/6] Data loading...")
    train_transform = create_transforms(args.dataset_name)
    test_transform = create_test_transforms()
    train_dataset, val_dataset, test_dataset, class_names = prepare_datasets(root_dir, train_transform, test_transform, args.train_split)
    train_loader, val_loader, test_loader = create_dataloaders(train_dataset, val_dataset, test_dataset, args.batch_size)

    diseases = build_disease_json(args.dataset_name, class_names)
    print(f"Diseases: {json.dumps(diseases, ensure_ascii=False)}")
    _upload_disease_json_to_s3(diseases, args.dataset_name, args.s3_bucket)

    print("\n[3/6] Model creation...")
    model = build_model(
        args.model, len(class_names), device,
        freeze_base=args.freeze_base, unfreeze_layer=args.unfreeze_layer if args.freeze_base else None,
    )
    criterion = nn.CrossEntropyLoss().to(device)
    optimizer = optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=args.learning_rate, weight_decay=args.weight_decay,
    )

    print("\n[4/6] MLflow tracking setup...")
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(experiment_name)
    experiment = mlflow.get_experiment_by_name(experiment_name)

    with mlflow.start_run(experiment_id=experiment.experiment_id):
        mlflow.pytorch.autolog()
        mlflow.log_params({
            "optimizer": type(optimizer).__name__,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "epochs": args.epochs,
            "criterion": type(criterion).__name__,
            "model_architecture": type(model).__name__,
            "training_device": str(device),
            "dataset_name": args.dataset_name,
        })

        print("\n[5/6] Training (early stopping, patience="
              f"{args.patience})...")
        history = {"loss": [], "val_loss": [], "accuracy": [], "val_accuracy": []}
        best_val_loss = float("inf")
        epochs_no_improve = 0
        best_model_state = None
        last_epoch = 0

        for epoch in range(args.epochs):
            last_epoch = epoch
            train_loss, train_acc = run_epoch(model, train_loader, criterion, optimizer, device, train=True, limit_batches=args.limit_batches)
            val_loss, val_acc = run_epoch(model, val_loader, criterion, optimizer, device, train=False, limit_batches=args.limit_batches)

            history["loss"].append(train_loss)
            history["val_loss"].append(val_loss)
            history["accuracy"].append(train_acc)
            history["val_accuracy"].append(val_acc)

            print(f"Epoch [{epoch+1}/{args.epochs}] - loss: {train_loss:.4f}, acc: {train_acc:.4f}, val_loss: {val_loss:.4f}, val_acc: {val_acc:.4f}")

            mlflow.log_metric("train_loss", train_loss, step=epoch)
            mlflow.log_metric("train_accuracy", train_acc, step=epoch)
            mlflow.log_metric("validation_loss", val_loss, step=epoch)
            mlflow.log_metric("validation_accuracy", val_acc, step=epoch)

            if args.patience > 0:
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    epochs_no_improve = 0
                    best_model_state = model.state_dict()
                else:
                    epochs_no_improve += 1
                    if epochs_no_improve >= args.patience:
                        print(f"Early stopping triggered after {epoch+1} epochs")
                        model.load_state_dict(best_model_state)
                        break

        mlflow.log_param("last_epoch", last_epoch)
        mlflow.log_metric("final_validation_accuracy", history["val_accuracy"][-1])
        mlflow.log_metric("final_train_loss", history["loss"][-1])

        print("\n[6/6] Évaluation finale (validation + test) & logging du modèle...")

        print("\n--- Évaluation finale sur le jeu de VALIDATION ---")
        _, y_true_val, y_pred_val = evaluate_model_on_dataset(model, val_loader, device, args.limit_batches)
        log_precision_recall_f1("validation", y_true_val, y_pred_val)
        log_confusion_matrix("VALIDATION", y_true_val, y_pred_val, class_names)

        print("\n--- Évaluation finale sur le jeu de TEST ---")
        test_acc, y_true_test, y_pred_test = evaluate_model_on_dataset(model, test_loader, device, args.limit_batches)
        log_precision_recall_f1("test", y_true_test, y_pred_test)
        mlflow.log_metric("Test_accuracy", test_acc)
        print(f"Test Accuracy: {test_acc:.4f}")
        log_confusion_matrix("TEST", y_true_test, y_pred_test, class_names)

        with tempfile.TemporaryDirectory() as tmp_dir:
            disease_json_path = os.path.join(tmp_dir, "disease.json")
            with open(disease_json_path, "w", encoding="utf-8") as f:
                json.dump(diseases, f, ensure_ascii=False, indent=2)

            model_display_name = args.model.lower().capitalize()
            registered_name = f"{model_display_name}_{args.dataset_name}_ep{args.epochs}"
            # Déplacement explicite sur CPU avant le logging : l'artifact sauvegardé est alors
            # directement portable, sans dépendre de map_location au chargement (déjà fait côté
            # api/app.py::_load_model, mais ceinture-bretelles - un modèle entraîné sur
            # CUDA/MPS ne doit jamais supposer la présence d'un GPU côté serveur d'inférence).
            model.to("cpu")
            model_info = mlflow.pytorch.log_model(
                pytorch_model=model,
                registered_model_name=registered_name,
                extra_files=[disease_json_path],
            )
            print(f"Modèle loggé : {model_info.model_id} (registered_model_name={registered_name})")

        print("\n--- Metrics and model logged into MLflow ---")

    return history


if __name__ == "__main__":
    train_model(parse_args())
