# training/ — Entraînement du modèle CNN Vitiscan

Script `train.py` paramétrable en ligne de commande, exécutable en local (venv) ou depuis un DAG
Airflow. Fidèle à `notebooks/CNN_model_FT.ipynb` (dataset inrae, notebook de référence réellement
utilisé pour entraîner le modèle actuellement en prod) et `notebooks/CNN_model.ipynb` (dataset
kaggle, archivé, plus utilisé mais gardé fonctionnel) — mêmes hyperparamètres par défaut, même
boucle d'entraînement (early stopping, métriques val+test, `disease.json`), mêmes conventions
MLflow. Voir `docs/refactoring.md` (racine du dépôt) pour le détail des écarts trouvés entre
l'ancien `scripts/` (calqué par erreur sur le notebook kaggle) et les notebooks, corrigés ici.

## Structure

- `train.py` — CLI (argparse) + boucle d'entraînement (early stopping) + logging MLflow
- `data_utils.py` — préparation des données (`--dataset-name inrae|kaggle`) + Dataset/DataLoader,
  transforms propres à chaque dataset
- `disease_labels.py` — table de traduction FR des classes par dataset (reprise des notebooks,
  confirmée identique au contenu réel de `s3://s3-vitiscan-data/data-{inrae,kaggle}/disease-*.json`)
- `model_registry.py` — factory générique de modèles (`SUPPORTED_MODELS` : resnet18/34/50,
  efficientnet_b0/b1/b2, mobilenet_v2), remplace les fonctions dédiées par architecture
- `config.yml` — candidats de modèles pour le sweep multi-modèles orchestré par Airflow (DAG
  `dag_train_model`, cf. `dags/dag_train_model.py` + `dags/tasks/train_model.py`) : **non lu par
  `train.py`**, qui reste volontairement un script "un seul modèle à la fois" piloté par ses
  propres `--model`/`--learning-rate`/`.env`. C'est le DAG qui lit ce fichier et lance un
  `train.py` par entrée de `models_to_run`.
- `notebooks/CNN_model_FT.ipynb` — notebook de référence (conda, cf. `notebooks/environment.yml`)
- `tests/` — tests unitaires (`pytest`)

## Dataset

Deux sources supportées via `--dataset-name` (par défaut : `inrae`) :
- `inrae` (recommandé - cf. `specs.md`) : ordre de résolution automatique dans
  `data_utils.prepare_dataset()` — dataset déjà organisé en local (`organized_data_inrae/`) → zip
  local (`--dataset-zip-path`) → **zip téléchargé depuis
  `s3://<TRAINING_S3_BUCKET>/data-inrae/dataset_inrae.zip` en secours** (~1.3 Go) → reconstruction
  depuis `raw_data_inrae/` (rééquilibrage de la classe "sain" à 350 images max + split
  déterministe 70/15/15, seed=42 — identique au notebook). `TRAINING_S3_BUCKET` (défaut
  `s3-vitiscan-data`) est un bucket dédié aux données Vitiscan, distinct du bucket MLflow
  (`aws-s3-mlflow`, implicite, utilisé par le SDK MLflow pour le modèle lui-même).
- `kaggle` (archivé) : téléchargé depuis `--dataset-url`, réorganisé automatiquement après
  extraction. Toujours fonctionnel mais plus utilisé (dataset kaggle jugé de moins bonne qualité,
  cf. `specs.md`).

### Répartition des classes (dataset `inrae`, `dataset_inrae.zip`)

Comptage réel des images par classe et par split (`train`/`val`/`test`), vérifié par inspection du
zip (`zipfile.namelist()`) :

| Classe | train | val | test | total |
|---|---|---|---|---|
| `sain` | 319 | 99 | 99 | 517 |
| `plasmopara_viticola` | 346 | 107 | 106 | 559 |
| `elsinoe_ampelina` | 263 | 82 | 84 | 429 |
| `guignardia_bidwellii` | 170 | 52 | 55 | 277 |
| `colomerus_vitis` | 120 | 35 | 39 | 194 |
| `erysiphe_necator` | 92 | 28 | 32 | 152 |
| `phaeomoniella_chlamydospora` | 83 | 26 | 26 | 135 |

`sain` n'est pas la classe la plus représentée (`plasmopara_viticola` l'est davantage) — cohérent
avec un dataset INRAE réel, pas de signe d'un ajout artificiel externe.

⚠️ **Provenance** : ni le notebook (`CNN_model_FT.ipynb`) ni `data_utils.py` ne copient d'images du
dataset Kaggle vers le dataset INRAE — le seul traitement appliqué à `raw_data_inrae/sain/` est un
**sous-échantillonnage** (suppression aléatoire, seed fixe, plafond 350 images, jamais un ajout).
Le contenu initial de `raw_data_inrae/` (avant tout script de ce dépôt) est fourni en amont et sa
provenance exacte n'est pas documentée dans le code.

## Local (venv)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.template .env   # puis compléter (AWS_* notamment)

# Test rapide (peu d'epochs, peu de batches) - cf. NB Important de specs.md :
python train.py --epochs 1 --limit-batches 5

# Entraînement complet (paramètres par défaut = ceux du notebook de référence) :
python train.py --dataset-name inrae
```

Toutes les options : `python train.py --help`.

## Sweep multi-modèles (Airflow)

Pour comparer plusieurs architectures (`config.yml::models_to_run`), pas besoin de lancer
`train.py` à la main plusieurs fois : le DAG `dag_train_model` (`airflow/`, cf.
`dags/dag_train_model.py` + `dags/tasks/train_model.py`) lit `config.yml` et lance un `train.py`
en subprocess par modèle (une tâche Airflow par modèle, séquentiel). Voir `airflow/README.md`
pour démarrer la stack Airflow. Déclenchement manuel uniquement pour l'instant (pas de détection
automatique de nouvelles images labellisées).

## Tests

```bash
pytest tests/
```

## Notebook (conda)

```bash
conda env create -f notebooks/environment.yml   # ou environment-gpu.yml
conda activate vitiscan_cnn
jupyter notebook notebooks/CNN_model_FT.ipynb
```

## Notes de refactor

- `EXPERIMENT_NAME` est un nom de **base** : `train.py` ajoute automatiquement le suffixe
  `_FINE_TUNING` quand `--freeze-base=true` et `--unfreeze-layer` est renseigné (comportement par
  défaut), comme le notebook. Expérience réelle : `Vitiscan_CNN_Resnet_INRAE_FINE_TUNING`.
- Early stopping (`--patience`, 5 par défaut) et `--weight-decay` (0.0001 par défaut) ajoutés —
  absents de l'ancien `scripts/`.
- Le modèle est loggé dans MLflow avec `dataset_name`/`last_epoch` en paramètres, un `disease.json`
  (`extra_files`, traductions FR réelles via `disease_labels.py`) et un `registered_model_name` au
  format `{Model}_{dataset}_ep{epochs}` (au lieu du générique `type(model).__name__` ambigu de
  l'ancien `scripts/`).
- Précision/rappel/F1 (weighted+macro) et matrices de confusion calculés sur validation ET test
  (l'ancien `scripts/` ne calculait qu'un F1 sur validation, jamais sur test).
- Bug corrigé : l'optimizer n'entraînait auparavant que la tête de classification même en mode
  fine-tuning (couche `layer4` dégelée mais jamais optimisée).
- `--limit-batches` (ajout, absent des notebooks) permet des runs de quelques secondes pour valider
  que le pipeline tourne, sans attendre un entraînement complet (15-20 min+, cf. NB Important de
  `specs.md`).
