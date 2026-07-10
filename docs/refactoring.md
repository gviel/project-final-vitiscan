# Suivi du refactoring CDSD -> ce dépôt (TODO Objectif Partie 1)

Suivi de l'avancement de la Partie 1 du TODO de `specs.md` ("Refactorer le code CDSD"). Complète
`specs.md` (qui décrit l'objectif et les contraintes) sans le dupliquer : ce document ne contient
que l'état d'avancement et les décisions prises pendant l'exécution.

Ordre suivi (voir la discussion initiale) : squelette du dépôt -> API CNN -> UI Streamlit ->
API RAG-LLM -> docker-compose racine -> entraînement -> Airflow. La logique : obtenir le plus vite
possible un flux bout-en-bout fonctionnel (le modèle CNN est déjà entraîné et disponible dans
MLflow), et repousser le refactor de l'entraînement (le plus long à valider) après.

## État des étapes

| # | Étape | Statut |
|---|-------|--------|
| 1 | Squelette du dépôt | ✅ Fait |
| 2 | API de prédiction CNN (`api/`) | ✅ Fait, build + démarrage Docker testés |
| 3 | UI Streamlit (`ui/`) | ✅ Fait, build Docker testé |
| 4 | API RAG-LLM (`rag-llm/`) | ✅ Fait, testé de bout en bout en conditions réelles (`/diagno` -> `/solutions`, cf. note ci-dessous) |
| 5 | `docker-compose.yml` racine | ✅ Fait, config validée + 3 images buildées |
| 6 | Refactor de l'entraînement (`training/`) | ✅ Fait, exécuté réellement de bout en bout via `dag_train_model` (2 bugs trouvés et corrigés, cf. section 7bis-train) |
| 7 | Airflow 3.2.2 (`airflow/` + `dags/`) | ✅ Fait, build + `dag_rag_ingestion` testés réellement de bout en bout (cf. section 7bis) ; `dag_train_model` en cours de test |
| 8 | Tests "golden prompts" RAG-LLM | ✅ Fait, 11 cas exécutés réellement contre la stack (10 passed, 1 skipped pour quota HF épuisé) |
| 9 | Doc de déploiement Render / Streamlit Community | ✅ Fait (`docs/deploiement-render-streamlit.md` + `render.yaml`), déploiement réel non testé (pas de compte Render/Streamlit Cloud dans cette session) |
| 10 | DAG `dag_train_model` — sweep multi-modèles (`training/config.yml`) | ✅ Fait, config validée + build Docker réellement testé (bug fastapi pré-existant trouvé et corrigé) ; déclenchement réel du DAG non testé |

## Détail par étape

### 1. Squelette du dépôt
Arborescence par composant (`api/`, `ui/`, `rag-llm/`, `training/`, `airflow/`, `dags/`, `docs/`),
`.gitignore`, `README.md` racine, historique git neuf (pas de réutilisation des dépôts sources ni
de leur historique). **Aucun commit créé** à ce stade — dépôt initialisé mais pas encore committé.

### 2. `api/` — API de prédiction CNN
Migré depuis `vitiscan-diagno-api`. Changements :
- Chargement du modèle : `mlflow.pytorch.load_model()` au lieu du couple boto3 (download manuel) +
  `torch.load()` + parsing de l'URI S3 à la main.
- `disease.json` récupéré via `mlflow.artifacts.download_artifacts()` plutôt qu'un client S3
  maison (tempfile, `tqdm`, `head_object`...).
- Bug corrigé : `tensor.to(DEVICE)` dont le résultat n'était pas réassigné (sans conséquence tant
  que `DEVICE='cpu'`, mais faux).
- Ajout de `GET /health`.
- Dockerfile simplifié (retrait des paquets HF Spaces-only : `vim`, `nano`, `unzip`, `useradd`...).
- **Testé** : `docker build` puis `docker run` sans credentials AWS réels → l'API démarre, log
  l'erreur (`NoCredentialsError`) proprement et répond `{"status":"model_not_loaded"}` sur
  `/health` au lieu de planter.

### 3. `ui/` — Interface Streamlit
Migré depuis `Project_10_VitiScan_WebUI`. Changements :
- `verify=False` retiré des appels `requests` (désactivait la vérification TLS).
- Fichier `.README.md.swp` (committé par erreur dans la source) non repris.
- `requirements.txt` allégé (`numpy`, `pandas`, `plotly`, `glom`, `gunicorn` non utilisés par
  `app.py` retirés).
- Petit bug corrigé : en cas d'échec de `/solutions`, l'ancien code affichait silencieusement rien
  (pas de message d'erreur) — un message d'erreur explicite est maintenant affiché.
- Port par défaut changé de 7860 (spécifique HF Spaces) à 8501 (par défaut Streamlit).

### 4. `rag-llm/` — API RAG-LLM
Migré depuis `vitiscan-rag-llm`. Le plus gros nettoyage de cette passe :
- **Deux pipelines d'ingestion redondants** (`ingest_vitiscan.py` à la racine, naïf, un chunk par
  fichier, pas de frontmatter ; et `app/ingestion.py`, plus complet) → un seul conservé
  (`app/ingestion.py`), exposé via `run_ingestion(knowledge_dir=...)` réutilisable (CLI ou DAG
  Airflow).
- **Duplication de dictionnaires** : `CNN_LABEL_ALIASES` dupliqué à l'identique dans
  `dosage_rules.py` et `rag_pipeline.py`, plus deux dictionnaires de traduction FR quasi
  identiques (`CNN_LABEL_FR` / `DISEASE_TRANSLATION`) dans `rag_pipeline.py` → consolidés dans un
  seul module `app/diseases.py`.
- `weaviate_client.py` : host/port de connexion locale rendus configurables par variables d'env
  (`WEAVIATE_HOST/PORT/GRPC_PORT`) au lieu d'être en dur sur `localhost` — nécessaire pour
  fonctionner dans un réseau Docker (le service s'appelle `weaviate`, pas `localhost`).
- LLM confirmé : Hugging Face Inference router, `meta-llama/Meta-Llama-3-8B-Instruct` par défaut.
  Embeddings : `sentence-transformers/all-MiniLM-L6-v2`.
- `requirements.txt` allégé (`transformers`, `unidecode`, `markdown`, `huggingface_hub` non
  utilisés directement retirés).
- Weaviate local en Docker pour cette première phase (recommandation explicite du NB Important de
  `specs.md` — le plan gratuit Weaviate Cloud utilisé jusqu'ici n'est pas fiable).

**Harmonisation des noms de maladies appliquée** (cf. `docs/harmonisation-noms-maladies.md`,
option B) : noms latins INRAE + 2 classes Kaggle sans équivalent comme identifiant canonique
unique (`id` == `cnn_label`) dans les 9 fiches restantes de `data/knowledge/`, `diseases.py` et
`dosage_rules.py` (fiche `Grape_Mites_leaf_disease.md` supprimée, redondante avec Erinose).

**Testé de bout en bout en conditions réelles** (stack `weaviate`+`api`+`rag-llm` démarrée via
`docker-compose`, vraie photo de feuille, vrai modèle INRAE en prod) : `POST /diagno` ->
`guignardia_bidwellii` (98.9%) -> `POST /solutions` renvoie un vrai `treatment_plan` (dosage +
produit) au lieu du message de repli générique — le bug documenté dans l'audit est confirmé
résolu. Un bug de régression annexe a été trouvé et corrigé au passage :
`diseases.py::cnn_label_to_fr()` ne normalisait pas les alias courts hérités avant de chercher la
traduction FR (cassé uniquement pour ces alias, pas pour les labels réels du modèle en prod).

**Appel LLM réel confirmé** une fois `HF_API_TOKEN` renseigné dans `rag-llm/.env` : réponse JSON
structurée cohérente (diagnostic, actions curatives/préventives, avertissements) pour le cas
`guignardia_bidwellii`/conventionnel/forte testé — sert de base aux golden prompts (étape 8).

### 5. `docker-compose.yml` racine
Stack locale : `api` + `ui` + `rag-llm` + `weaviate` (MLflow reste externe, sur Hugging Face
Spaces, non géré ici). Noms de conteneurs préfixés `vitiscan_` et ports choisis pour ne pas entrer
en collision avec la stack Fraud Detection déjà en cours sur la machine (8080 pris par son
Airflow, 8501 par son dashboard) :

| Service | Port hôte | Port conteneur |
|---|---|---|
| api | 4000 | 4000 |
| ui | 8502 | 8501 |
| rag-llm | 9000 | 9000 |
| weaviate (REST) | 8081 | 8080 |
| weaviate (gRPC) | 50051 | 50051 |

**Testé** : `docker-compose config` valide (le `docker-compose` disponible ici est la v1 legacy,
qui ne supporte pas la clé `name:` top-level de la Compose Spec v2 — évitée), et les 3 images
(`api`, `rag-llm`, `ui`) buildent avec succès.

### 6. `training/` — Entraînement du modèle CNN
Migré depuis `Project_10_VitiScan_model`. `scripts/` (4 fichiers, plus `main.py` à la racine,
disjoint de `config.yml`) compacté en 3 fichiers : `train.py` (CLI + boucle d'entraînement),
`data_utils.py` (dataset), `model_registry.py` (factory de modèles). Changements notables :
- **`config.yml` déclarait 7 architectures** (resnet18/34/50, efficientnet_b0/b1/b2,
  mobilenet_v2) **mais le code n'en supportait réellement que 2** (resnet18/34, via deux fonctions
  dédiées) — remplacé par une factory générique (`torchvision.models.get_model()` +
  remplacement générique de la tête de classification `fc`/`classifier`), qui couvre bien les 7.
- **Bug corrigé** : l'optimizer n'entraînait que la tête de classification
  (`model.fc.parameters()`) même en mode "fine-tuning" où une couche supplémentaire
  (`layer4`) était dégelée (`requires_grad=True`) — ses gradients étaient calculés mais jamais
  appliqués. L'optimizer prend maintenant tous les paramètres réellement dégelés.
- **Gap comblé** : le run MLflow ne loggait ni `dataset_name` (lu par `api/app.py` au chargement
  du modèle) ni `disease.json` (déposé à la main sur S3 pour le modèle actuellement en prod) — le
  nouveau `train.py` logge les deux (le `disease.json` généré est un mapping identité par défaut,
  à curer manuellement si besoin, cf. note ci-dessous).
- `--dataset-name inrae|kaggle` : le dataset inrae (recommandé par `specs.md`) est déjà organisé en
  train/val/test — le code utilise maintenant le `val/` réel du dataset au lieu de re-splitter le
  train (perte d'information évitée), tout en gardant la compatibilité avec le flux Kaggle
  (téléchargement + réorganisation).
- `--limit-batches` ajouté pour des runs de quelques secondes (cf. NB Important de `specs.md` :
  éviter les exécutions longues pendant les tests).
- `visualisation.py` (Plotly, `.show()` — bloquant/inadapté en headless) retiré : MLflow logge déjà
  les courbes loss/accuracy par epoch, consultables dans son UI.
- **Non exécuté en réel** (pas d'environnement torch/mlflow disponible dans cette session, et
  entraînement complet volontairement évité — cf. NB Important) : seule une vérification syntaxique
  (`py_compile`) a été faite sur `train.py`, `data_utils.py`, `model_registry.py`.

⚠️ Le `disease.json` généré par le nouveau `train.py` est un mapping identité (nom de classe brut,
ex. `colomerus_vitis`) — ~~pas de traduction automatique vers les labels métier utilisés par
`rag-llm/app/diseases.py` (ambiguïté entre "erinose" et "mites" notamment, à trancher avec un
expert viticole)~~ **résolu** : depuis l'harmonisation des noms (cf. `docs/harmonisation-noms-maladies.md`),
`rag-llm/app/diseases.py` utilise directement les mêmes noms latins que `disease.json` comme
identifiant canonique — plus besoin de traduction, le mapping identité suffit désormais.

**Notebooks historiques conservés** dans `training/notebooks/` pour montrer aux examinateurs la
base de travail d'origine (exploration/mise au point avant industrialisation en `train.py`) :
`CNN_model_FT.ipynb` (fine-tuning sur le dataset `inrae`, déjà présent) et `CNN_model.ipynb`
(dataset `kaggle`, archive — copié depuis
`Project_10_VitiScan_model/notebooks/CNN_model.ipynb`). Ce sont des copies figées, non maintenues
en parallèle de `train.py`.

### 7. `airflow/` + `dags/`
Stack Airflow 3.2.2 dédiée à Vitiscan. **Isolation vérifiée vis-à-vis de la stack Airflow du projet
Fraud Detection, déjà en cours d'exécution sur la même machine** (confirmé par `docker ps` avant
et après : aucun conteneur Fraud Detection perturbé) :

| | Fraud Detection (existant) | Vitiscan (nouveau) |
|---|---|---|
| Nom de projet Compose | `airflow` (implicite, nom du dossier) | `vitiscan_airflow` (forcé dans `start.sh`) |
| Image Airflow | `fraud-detection-airflow:latest` | `vitiscan-airflow:latest` |
| Conteneurs | `airflow_airflow-*_1` | `vitiscan_airflow_*` |
| Port UI (hôte) | 8080 | 8090 |
| Secret JWT | `fraud-detection-dev-secret-key...` | `vitiscan-airflow-dev-secret-key...` |

DAG `dag_rag_ingestion` : détecte les nouveaux documents markdown dans
`s3://RAG_S3_BUCKET/RAG_S3_PREFIX`, les ingère dans un Weaviate de test dédié (`weaviate-test`,
propre à la stack Airflow), rejoue les golden prompts contre ce Weaviate de test (porte de
qualité, cf. section 7bis), et seulement si tout est OK, réingère dans le Weaviate de prod (celui
du `docker-compose.yml` racine, rejoint via `host.docker.internal:8081` — deux projets Compose
distincts, donc pas de résolution DNS par nom de service entre eux).

**Testé une première fois** (avant l'ajout de la porte de qualité) : `docker-compose config`
valide (avec `COMPOSE_PROJECT_NAME=vitiscan_airflow` exporté), noms de conteneurs vérifiés
distincts par `grep`. Build + test réel de bout en bout (avec la porte de qualité) : cf. section
7bis ci-dessous.

### 7bis. Porte de qualité golden prompts dans `dag_rag_ingestion`

Suite à une demande explicite de l'utilisateur : le DAG ne promouvait jusqu'ici les documents vers
le Weaviate de prod que sur la base du succès technique de l'ingestion test, jamais sur la base
d'un run golden prompts réussi — pourtant l'intention décrite dans `specs.md`.

Logique d'évaluation d'un cas (fallback générique / cross-check dosage via `compute_dosage()` /
mots-clés LLM) extraite de `rag-llm/tests/test_golden_prompts.py` vers un nouveau module
`rag-llm/app/golden_prompts.py` (`load_cases`, `evaluate_case`, exceptions
`GoldenPromptFailure`/`GoldenPromptSkipped`) — module de production, pas un fichier de test,
puisque désormais réutilisé par deux appelants : le test pytest (HTTP, boîte noire) et la nouvelle
tâche Airflow `run_golden_prompts_gate` (`dags/tasks/rag_ingestion.py`), qui appelle
`generate_treatment_advice()` **directement en process** contre `weaviate-test` (même pattern que
`_run_ingestion` pour l'ingestion elle-même — pas besoin d'un serveur HTTP rag-llm démarré dans le
conteneur Airflow).

Nouvelle chaîne du DAG : `branch_check_new_docs` -> `download_and_ingest_test` ->
**`golden_prompts_gate`** -> `ingest_prod`. Toute panne réelle (`GoldenPromptFailure`) fait
échouer la tâche Airflow, ce qui bloque `ingest_prod` par dépendance de tâche. Les pannes purement
dues à l'indisponibilité du LLM externe (`GoldenPromptSkipped` — hors de portée de cette porte, qui
vérifie la résolution du nommage/dosage, pas la disponibilité du LLM) ne bloquent pas la promotion.

`HF_API_TOKEN`/`HF_API_URL`/`HF_MODEL_ID` ajoutés en variables d'environnement optionnelles de
`airflow-common` (`airflow/docker-compose.yml`, `airflow/.env.template`) : sans eux, la porte
fonctionne quand même (résolution nommage + dosage vérifiés), seule la vérification des mots-clés
LLM est skip.

**Régression vérifiée** : suite golden prompts pytest rejouée après le refactor du module partagé
contre la stack `rag-llm` réelle qui tournait déjà — même résultat qu'avant (10 passed, 1 skipped
quota HF), donc extraction sans effet de bord.

**Testé réellement de bout en bout dans Airflow** : `dag_rag_ingestion` déclenché sur la vraie
stack (documents uploadés au préalable dans `s3://s3-vitiscan-data/knowledge/current/`) — chaîne
complète `branch_check_new_docs` -> `download_and_ingest_test` -> `golden_prompts_gate` ->
`ingest_prod`, toutes en `success`. Log de `golden_prompts_gate` : **10 OK, 1 skip (quota HF), 0
échec** sur 11 cas. `ingest_prod` a réellement réingéré 79 chunks dans le Weaviate de **prod**
(`host.docker.internal:8081`) — confirmé indépendamment via `POST /solutions` sur `rag-llm`
(`plasmopara_viticola` retrouvé, dosage configuré, diagnostic LLM cohérent généré).

⚠️ **Quota Hugging Face Inference Providers — à garder à l'esprit** : un compte Free dispose de
**0,10 $ de crédits par mois** seulement (confirmé sur `huggingface.co/docs/inference-providers/
pricing` — PRO à 9 $/mois donne 2,00 $/mois, soit les "20x" mentionnés dans le message d'erreur
`status 402` rencontré 2 fois cette session). C'est un **budget mensuel en dollars, pas une limite
de débit** : espacer les appels dans le temps n'aide pas, seul le nombre total de requêtes compte,
et le budget se réinitialise une fois par mois. Heureusement, `golden_prompts_gate` n'appelle le
LLM (11 cas) que lorsque `branch_check_new_docs` détecte réellement de nouveaux documents S3 — pas
à chaque tick du cron horaire — donc la consommation reste limitée aux vrais événements
d'ingestion en usage normal, pas un gaspillage continu. Le design déjà en place
(`GoldenPromptSkipped` plutôt qu'un échec dur quand le LLM est indisponible) absorbe cette
contrainte sans bloquer la promotion : la résolution nommage/dosage (le cœur de cette porte de
qualité) ne dépend pas du LLM et reste vérifiée même quota épuisé. Leviers si plus de marge
nécessaire : PRO (9 $/mois, 20x), crédits prépayés, ou une clé provider personnalisée (facturée
hors crédits HF, cf. doc officielle).

### 7bis-train. Répertoire de travail `work/` + `dag_train_model` testé réellement

**`work/`** (nouveau répertoire racine, gitignoré) : bind-mount unique (`../work:/opt/airflow/work`,
`WORK_DIR` dans `dags/config.py`) remplaçant le volume Docker nommé `vitiscan_training_data` —
fichiers de travail visibles/inspectables depuis l'hôte, persistants entre recréations de
conteneur :
- `work/training-data/` — cache du dataset CNN (`dataset_inrae.zip` + extraction), remplace
  `TRAINING_DATA_DIR=/opt/airflow/training-data` (volume nommé) par
  `/opt/airflow/work/training-data` (bind-mount).
- `work/rag-knowledge/` — cache de téléchargement des documents S3 pour `dag_rag_ingestion`
  (`RAG_KNOWLEDGE_WORK_DIR`), remplace le `tempfile.mkdtemp()` précédent : vidé (`shutil.rmtree`)
  et réécrit à chaque run plutôt qu'accumulé sans purge (cf. `dags/tasks/rag_ingestion.py`).

**`dag_train_model` testé réellement de bout en bout** (sweep `resnet18`+`resnet34`,
`limit_batches=2` pour un smoke test rapide) — **2 bugs pré-existants trouvés et corrigés**, jamais
exercés avant car le dataset était toujours déjà présent en local dans les sessions précédentes
(jamais un vrai téléchargement S3 + extraction) :

1. **`training/train.py` — défaut `--dataset-zip-path` silencieusement vide** :
   `training/.env` a `DATA_DIR=`/`DATASET_ZIP_PATH=` volontairement vides (convention "vide =
   calculer le défaut"), mais `train.py` tourne avec `cwd=training/` (mount read-only dans
   Airflow) où `load_dotenv()` charge ce `.env` — `os.getenv("DATASET_ZIP_PATH")` renvoie alors
   `""` (chaîne vide), pas `None`. Le test `if args.dataset_zip_path is None:` échouait
   silencieusement, laissant un chemin vide → `s3.download_file()` tentait d'écrire un fichier
   temporaire relatif à un `dirname` vide → erreur trompeuse `OSError: Read-only file system`
   (s3transfer résout le nom du fichier temporaire relatif au dossier de la destination). **Corrigé** :
   `if not args.data_dir:`/`if not args.dataset_zip_path:` (falsy check, pas `is None`).
2. **`training/data_utils.py::_prepare_inrae_dataset` — mauvais dossier d'extraction** :
   `dataset_inrae.zip` contient `train/`, `val/`, `test/` directement à sa racine (pas de dossier
   `organized_data_inrae/` wrapper à l'intérieur), mais le code faisait
   `zip_ref.extractall(data_dir)` au lieu de `zip_ref.extractall(organized_dir)` — confirmé en
   inspectant le zip réel (`zipfile.namelist()`). **Corrigé**.

**Résultat final** (`Vitiscan_CNN_Resnet_INRAE` experiment MLflow) :

| Modèle | Test Accuracy (2 batches/epoch, 25 epochs) | Registered model |
|---|---|---|
| `resnet18` | 0.7969 | `Resnet18_inrae_ep25` |
| `resnet34` | 0.8750 | `Resnet34_inrae_ep25` |

Chiffres attendus faibles/peu significatifs (smoke test à 2 batches/epoch, pas un vrai
entraînement) — l'objectif ici était de valider la mécanique bout en bout (téléchargement +
extraction + entraînement + évaluation + registration MLflow), pas la performance du modèle.

**Bug d'isolation trouvé et corrigé au passage** : `AIRFLOW__CORE__EXECUTION_API_SERVER_URL`
pointait vers `http://vitiscan-airflow-apiserver:8080/execution/` (tirets), qui ne correspond ni
au nom de service Compose (`airflow-apiserver`) ni au `container_name`
(`vitiscan_airflow_apiserver`, underscores) — DNS interne Docker Compose résout par nom de
**service**, pas par un nom inventé. Résultat avant correction : **toute** tâche `LocalExecutor`
échouait en `httpx.ConnectError: Temporary failure in name resolution` en tentant de rapporter son
statut. Bloquait `dag_rag_ingestion` autant que `dag_train_model`. **Corrigé** (`airflow-apiserver`,
cf. section 7bis).

### 8. Tests "golden prompts" RAG-LLM (`rag-llm/tests/`)

`golden_prompts.yaml` (11 cas) + `test_golden_prompts.py` (pytest, pilote `POST /solutions` en
HTTP réel — `RAG_LLM_URL`, défaut `http://localhost:9000`). Couvre les 9 fiches de
`data/knowledge/` (une par maladie), plus 2 cas ciblés : un alias court hérité
(`black_rot` -> doit résoudre vers `guignardia_bidwellii` et sa traduction FR), et la fiche
`mites` volontairement supprimée (doit tomber proprement sur le message de repli générique, pas
planter). Dépendances de test isolées dans `rag-llm/requirements-test.txt` (pytest, pyyaml — pas
nécessaires à l'API elle-même).

Chaque cas vérifie 3 choses : (1) pas de message de repli générique RAG (preuve que la fiche a été
retrouvée dans Weaviate — c'est le bug de nommage documenté dans
`docs/harmonisation-noms-maladies.md`), (2) le dosage renvoyé par l'API est identique à un appel
direct de `compute_dosage()` (détecte toute divergence de résolution du label entre le chemin HTTP
et la logique de dosage), (3) au moins un mot-clé attendu (nom de maladie/agent pathogène,
normalisé sans accents) apparaît dans le diagnostic généré par le LLM — sauf si l'appel LLM
lui-même a échoué (détecté via la signature du message de repli technique de `llm_client.py`),
auquel cas ce point précis est *skip* plutôt que *fail* (hors de portée de ce test : dépend de la
disponibilité/du quota de l'API HF externe, pas de la logique nommage/dosage vérifiée ici).

**Exécuté réellement** contre la stack `weaviate`+`api`+`rag-llm` (build + `docker-compose up`,
ingestion réelle, vrai token HF) : **10 passed, 1 skipped** (le cas `black_rot` a skip son
assertion mots-clés — quota mensuel HF gratuit épuisé pendant la session, cf. message d'erreur
`status 402` capturé). Aucun échec réel.

~~À faire plus tard : brancher ces tests comme porte de promotion dans
`dags/tasks/rag_ingestion.py`~~ — **fait** (cf. section 7bis ci-dessous,
`run_golden_prompts_gate`).

### 9. Doc de déploiement Render (`api`, `rag-llm`) + Streamlit Community Cloud (`ui`)

`docs/deploiement-render-streamlit.md` (nouveau) + `render.yaml` (racine, Blueprint Render
déclarant `vitiscan-api` et `vitiscan-rag-llm`). Deux vérifications faites (via WebFetch de la doc
officielle Render/Streamlit) avant rédaction plutôt que de deviner :
- Format exact du Blueprint (`dockerfilePath`, `dockerContext` par défaut = racine du repo,
  `healthCheckPath`, `envVars` avec `sync: false` pour les secrets demandés à la création).
- Secrets Streamlit Community Cloud : les clés TOML **au premier niveau** (pas dans une table)
  sont aussi exposées comme variables d'environnement classiques — confirme que `ui/app.py`
  (déjà en `os.getenv`, pas de `st.secrets`) fonctionne sans modification de code.

**Changement de code apporté** (pas seulement de la doc) : `api/Dockerfile` et `rag-llm/Dockerfile`
lisent désormais `$PORT` s'il est fourni (`CMD ... --port ${PORT:-4000}` /
`${PORT:-9000}`), avec fallback identique au port local si absent. Nécessaire car Render ne
garantit pas de détecter un port fixé en dur dans l'image (confirmé via la doc officielle) ; sans
ce changement, le déploiement Render risquait un health check en échec dès le premier essai.
**Testé réellement** : conteneur `api` lancé avec `-e PORT=5555` → `Uvicorn running on
http://0.0.0.0:5555`, healthcheck OK sur ce port ; puis re-testé **sans** `PORT` (comportement
`docker-compose` local) → toujours sur 4000/9000 comme avant, aucune régression.

Décision documentée mais non résolue (héritée de `rag-llm/README.md`, déjà connue avant cette
passe) : pas de Weaviate auto-hébergé sur Render (plan gratuit = disque éphémère + mise en veille,
pire que Weaviate Cloud gratuit) — `WEAVIATE_URL`/`WEAVIATE_API_KEY` doivent pointer vers une
instance externe persistante, à la charge de l'utilisateur.

~~**Non testé** : déploiement réel sur Render/Streamlit Cloud~~ — fait (session suivante, cf.
ci-dessous) : les 2 services Render et `ui` sur Streamlit Community Cloud ont été réellement créés
et testés.

### 9bis. Déploiement réel Render + Streamlit — bug de production trouvé et corrigé

**Déployé et testé réellement** : `vitiscan-api` et `vitiscan-rag-llm` créés via le Blueprint
`render.yaml` sur Render, `ui` sur Streamlit Community Cloud
(`share.streamlit.io`). `GET /health` et `POST /diagno` vérifiés en conditions réelles sur
`vitiscan-api` (photo réelle envoyée à travers Streamlit Cloud → Render).

**Bug de prod trouvé** : `vitiscan-api` tombait en échec de health check Render
(`HTTP health check failed (timed out after 5 seconds)`), avec redémarrages en boucle. Deux causes
cumulées, diagnostiquées en conditions réelles (pas en relisant le code) :
1. `api/app.py::lifespan` chargeait le modèle CNN **de façon bloquante** au démarrage (~150s
   mesuré : torch + téléchargement MLflow) — l'app ne répondait à *aucune* requête, y compris
   `/health`, pendant tout ce temps. Render redémarre une instance après 60s d'échecs consécutifs
   du health check → le chargement ne finissait jamais avant d'être interrompu.
2. `api/requirements.txt` épinglait `torch==2.5.0` sans préciser l'index CPU-only : pip installait
   par défaut la build **CUDA** (confirmé par un warning en prod :
   `Stored model version '2.5.1' does not match installed PyTorch version '2.5.0+cu124'`) alors que
   `DEVICE = "cpu"` partout dans le code — image plus lourde, import plus lent, aggrave le problème
   1 sans être la cause racine.

**Corrigé** :
- `api/app.py` : chargement du modèle déplacé dans un thread d'arrière-plan
  (`asyncio.get_event_loop().run_in_executor(...)`) au lieu de bloquer le `lifespan` — `/health`
  répond immédiatement (`model_loaded: false` puis `true` une fois prêt), satisfait le health check
  Render dès le premier appel.
- `api/requirements.txt` : `torch==2.5.0+cpu` / `torchvision==0.20.0+cpu` via
  `--extra-index-url https://download.pytorch.org/whl/cpu`.
- `training/train.py` : `model.to("cpu")` ajouté juste avant `mlflow.pytorch.log_model()` (défense
  en profondeur — l'artifact sauvegardé est directement portable, sans dépendre uniquement de
  `map_location` au chargement).

**Vérifié que le problème CUDA/CPU était déjà globalement bien géré par ailleurs** (question posée
en cours de session, méfiance justifiée par une mésaventure passée sur HF) :
`api/app.py::_load_model()` chargeait déjà avec `map_location=DEVICE` (`"cpu"`), et
`training/train.py` loggait déjà `training_device` (`str(device)`, cf. `get_device()` dans
`model_registry.py` : CUDA > MPS > CPU) comme paramètre MLflow visible dans l'UI — seul le nouveau
`model.to("cpu")` avant logging manquait, ajouté ci-dessus en bonus.

**Testé réellement après correctif** (local, avant redéploiement Render) : conteneur `api`
recréé → `/health` répond en ~1ms avec `model_loaded:false` dès le démarrage, bascule à `true` une
fois le chargement terminé en arrière-plan, `/diagno` renvoie toujours la même prédiction qu'avant
le fix (`guignardia_bidwellii`, 98.9% — aucune régression de précision liée au passage torch
CPU-only, cohérent puisque l'inférence tournait déjà sur CPU de toute façon).

## ⚠️ Sécurité

Les dépôts sources (`Project_10_VitiScan_model`, `vitiscan-diagno-api`) contenaient une paire de
clés AWS et un PAT GitHub **committés en clair** dans leur historique git. **Ni ces fichiers ni cet
historique n'ont été repris ici.** Recommandation : révoquer/régénérer ces credentials côté AWS et
GitHub dès que possible, indépendamment de ce refactor.

## ⚠️ Test réel avec les vraies credentials — bug de données découvert

Les secrets réels (AWS, `MLFLOW_MODEL_ID`, `EXPERIMENT_NAME`/`MODEL_NAME` d'entraînement) ont été
récupérés depuis les `.env` locaux des dépôts sources (`Project_10_VitiScan_model/.env`,
`vitiscan-diagno-api/.env` — mêmes clés dans les deux) et injectés dans `api/.env`,
`training/.env`, `airflow/.env`. **`HF_API_TOKEN` et `WEAVIATE_URL`/`WEAVIATE_API_KEY` restent
introuvables** : aucun `.env` n'existe dans `vitiscan-rag-llm/` source, et `HUGGINGFACE_TOKEN` est
vide dans `Project_10_VitiScan_WebUI/.env` — à fournir manuellement dans `rag-llm/.env`.

Test de `api/` avec les vraies credentials : le modèle se charge bien depuis MLflow
(`mlflow.pytorch.load_model()` fonctionne, `/health` renvoie `model_loaded:true`) — confirme que le
refactor de l'étape 2 est correct. **Mais `POST /diagno` sur une vraie image ne renvoie qu'une
seule prédiction mal étiquetée** (`"disease":"N/A"`) au lieu de la liste des maladies avec
confiances.

Cause racine (vérifiée directement en S3 via boto3, `head_object` + `list_objects_v2`) :
`extra_files/disease.json` **n'existe pas** dans S3 à l'emplacement attendu
(`s3://aws-s3-mlflow/mlflow-artifacts/3/models/m-46e598be.../artifacts/extra_files/disease.json`) —
seuls `MLmodel`, `conda.yaml`, `data/model.pth`, `data/pickle_module_info.txt`, `python_env.yaml`,
`requirements.txt` sont présents pour ce modèle. `dataset_name` est également absent des params du
run MLflow (cohérent avec le gap déjà documenté à l'étape 6 : `scripts/training.py` ne loggait ni
l'un ni l'autre). Sans `disease.json`, `DISEASES` retombe sur le fallback `{"N/A":"N/A"}`
(1 seule entrée), et `_predict()` ne zippe que le premier logit du modèle avec ce seul label.

**Ce n'est pas une régression du refactor** : le code source original avait exactement le même
dict de fallback et le même comportement de zip sur `len(DISEASES.keys())` en cas d'échec du
chargement. Mais ça signifie que **le modèle actuellement en prod dans MLflow ne peut pas
produire de prédictions exploitables tel quel**, avec l'ancien code comme avec le nouveau.

**RÉSOLU** (voir section suivante) : `m-46e598be...` n'était simplement pas le bon modèle à
utiliser. Un audit MLflow complet a permis de trouver un modèle valide et de corriger
`api/.env`/`api/.env.template` — `/diagno` fonctionne maintenant correctement de bout en bout.

## `training/` était désynchronisé du notebook réellement utilisé — corrigé

L'utilisateur a signalé que `scripts/` (base du refactor de l'étape 6) était probablement calqué
sur un **ancien notebook kaggle**, pas sur `notebooks/CNN_model_FT.ipynb` (le notebook de
référence, dataset inrae, réellement utilisé pour entraîner le modèle en prod). Vérification faite
en lisant intégralement les deux notebooks sources
(`Project_10_VitiScan_model/notebooks/CNN_model_FT.ipynb` et `CNN_model.ipynb`) — **hypothèse
confirmée**, et plusieurs écarts corrigés dans `training/`.

### Réponse à la question : quel `EXPERIMENT_NAME` utilisait le notebook ?

Le notebook FT (inrae) fait :
```python
EXPERIMENT_NAME = os.getenv('EXPERIMENT_NAME', "Vitiscan_CNN_MLFlow") + "_FINE_TUNING"
```
Le notebook kaggle (archivé), lui, n'ajoute **aucun suffixe**. Avec la valeur réellement présente
dans `Project_10_VitiScan_model/.env` (`EXPERIMENT_NAME="Vitiscan_CNN_Resnet_INRAE"`), l'expérience
MLflow réellement utilisée est donc **`Vitiscan_CNN_Resnet_INRAE_FINE_TUNING`** — confirmé présent
dans MLflow (cf. audit ci-dessous). `training/train.py` reproduit maintenant ce comportement : le
nom passé en `--experiment-name`/`EXPERIMENT_NAME` est une base, et `_FINE_TUNING` est ajouté
automatiquement quand `--freeze-base=true` et `--unfreeze-layer` est renseigné (le cas par défaut).

### `scripts/` calqué sur le notebook kaggle — confirmé, écarts corrigés

| | notebook kaggle (archivé) | notebook FT inrae (référence) | ancien `scripts/` |
|---|---|---|---|
| Transform train | `ColorJitter(0.5, 0.5)` | `RandomHorizontalFlip` + `RandomVerticalFlip` + `RandomRotation(±45°)` | `ColorJitter` (= kaggle) |
| Répertoire dataset | `../data-kaggle` (imbriqué, à réorganiser) | `../data-inrae/organized_data_inrae` (généré depuis `raw_data_inrae`) | logique de réorganisation kaggle uniquement |
| `learning_rate` | 0.0005 (transfer learning simple, chemin mort) | 0.0001 | 0.0005 (= kaggle) |
| `weight_decay` | — | 0.0001 | absent |
| Early stopping | oui (patience) | oui (patience) | **absent** |
| Métriques | precision/recall/f1 (val+test), matrices de confusion (val+test) | idem | F1 sur val uniquement, pas de test |
| `dataset_name` loggé | oui | oui | **non** |
| `disease.json` | oui (`extra_files` + upload S3 séparé) | oui (idem) | **non loggé du tout** |
| `registered_model_name` | `f"{MODEL_NAME}_{DATASET_NAME}_ep{epochs}"` | idem | `type(model).__name__` (générique, ambigu) |

`training/train.py`, `training/data_utils.py` ont été réécrits pour suivre fidèlement le notebook
FT (inrae, dataset par défaut) tout en gardant le dataset kaggle fonctionnel (archivé, sélectionnable
via `--dataset-name kaggle`) :
- `training/disease_labels.py` (nouveau) : table de traduction FR par dataset, reprise telle
  quelle des notebooks et **confirmée identique** au contenu réel de
  `s3://aws-s3-mlflow/vitiscan-data/disease-inrae.json` et `disease-kaggle.json` (cf. ci-dessous) —
  résout définitivement l'ambiguïté "erinose vs mites" notée précédemment :
  `colomerus_vitis` → **Erinose** (confirmé, pas "mites").
- Préparation du dataset inrae (`data_utils.py::prepare_dataset`) : ordre de résolution
  `organized_data_inrae/` déjà présent → zip local → **zip téléchargé depuis S3 en secours** → sinon
  reconstruction depuis `raw_data_inrae/` avec le même rééquilibrage (classe "sain" plafonnée à 350
  images, seed=42) et le même split déterministe (70/15/15, seed=42) que le notebook.
- Early stopping (patience configurable), `weight_decay`, précision/rappel/F1 + matrices de
  confusion sur validation ET test, `dataset_name` et `last_epoch` loggés, `registered_model_name`
  au format `{Model}_{dataset}_ep{epochs}`, upload du `disease.json` à la fois en `extra_files` du
  modèle et en copie de référence sur S3 (`vitiscan-data/disease-{dataset}.json`) — tout ceci
  reproduit exactement ce que fait le notebook.

### Découverte : `s3://aws-s3-mlflow/vitiscan-data/` contient déjà des artefacts réutilisables

Trouvé par l'utilisateur pendant cette session : trois fichiers existent déjà à cet emplacement S3
(déposés par les notebooks, indépendamment de tout run MLflow précis) :
- `dataset_inrae.zip` (~1.3 Go) — utilisé maintenant comme source de secours par
  `data_utils.py` si le dataset n'est pas déjà présent en local ;
- `disease-inrae.json` / `disease-kaggle.json` — confirmés **identiques** aux tables codées en dur
  dans `training/disease_labels.py`.

Le dataset kaggle, lui, reste téléchargeable directement depuis Kaggle (`--dataset-url`), pas besoin
de zip S3 dédié.

### Audit MLflow : experiments `Vitiscan_*` et artifacts réellement présents sur S3

Demande de l'utilisateur : identifier les runs dont le modèle n'a jamais été poussé sur S3 (à cause
d'un problème de configuration des credentials AWS à l'époque), pour pouvoir ensuite les purger.
Audit fait (lecture seule, `mlflow.tracking.MlflowClient.search_logged_models()` +
`boto3.list_objects_v2` pour vérifier la présence réelle d'un `.pth`/`.pkl` sur S3, pas seulement
la métadonnée MLflow) :

| Experiment (id) | Logged models | Avec `.pth`/`.pkl` réel sur S3 |
|---|---|---|
| `Vitiscan_CNN_MLFlow` (1) | 8 | **0 / 8** |
| `Vitiscan_CNN` (2) | 2 | **0 / 2** |
| `Vitiscan_CNN_Notebook_GPU` (3) | 10 | 10 / 10 |
| `Vitiscan_CNN_resnet_inraeFINE_TUNING` (4) | 6 | 6 / 6 |
| `Vitiscan_CNN_Notebook_GPUFINE_TUNING` (5) | 2 | 2 / 2 |
| `Vitiscan_CNN_Resnet_INRAE_FINE_TUNING` (6) | 2 | 2 / 2 |

**Les deux plus anciennes experiments (`Vitiscan_CNN_MLFlow` et `Vitiscan_CNN`, 10 logged models
au total) sont entièrement vides** — aucun `.pth`/`.pkl` réel, cohérent avec l'hypothèse de
l'utilisateur (échec d'upload S3 pour cause de credentials mal configurées à l'époque). Ces
2 experiments contiennent aussi la majorité des runs `status=FAILED` (le run a planté avant
d'atteindre `mlflow.pytorch.log_model()`, cohérent avec un échec d'upload).

Toutes les experiments plus récentes (3 à 6) ont, elles, 100% de logged models avec un artifact
réel confirmé sur S3 — aucun problème détecté sur celles-ci.

⚠️ **Purge faite par l'utilisateur** (pas par Claude) : les experiments 1 et 2 (`Vitiscan_CNN_MLFlow`,
`Vitiscan_CNN`, 10 logged models sans aucun artifact réel) ont été supprimées manuellement via l'UI
MLflow. Confirmé après coup : `search_experiments()` ne les liste plus.

### Audit metadata (dataset_name + disease.json) sur les 4 experiments restantes

Consigne de l'utilisateur : supprimer les anciennes versions **sans `dataset_name` NI
`disease.json`** (metadata incomplète). Audit fait sur les 4 experiments restantes (`Vitiscan_CNN_Notebook_GPU`
id=3, `Vitiscan_CNN_resnet_inraeFINE_TUNING` id=4, `Vitiscan_CNN_Notebook_GPUFINE_TUNING` id=5,
`Vitiscan_CNN_Resnet_INRAE_FINE_TUNING` id=6 — attention, 4 et 6 ont des noms très proches mais une
casse différente, ce sont deux experiments distinctes) :

| Statut | Nombre | Détail |
|---|---|---|
| Ni `dataset_name` ni `disease.json` | **15** | 7/10 de l'experiment 3, 6/6 de l'experiment 4 (en intégralité), 2/2 de l'experiment 5 (en intégralité) |
| Un des deux manquant seulement | 4 | 3 runs de l'experiment 3 avec `disease-kaggle.json` (entraînés sur kaggle, pas inrae) ; `calm-stag-792` (experiment 6) avec `disease-inrae.json` |
| Metadata complète | 1 | `polite-mole-465` (experiment 6, `m-da948d99...`) |

Les 15 runs "ni l'un ni l'autre" correspondent à la lecture stricte de la consigne (les deux
manquants à la fois). **Supprimés** à la demande explicite de l'utilisateur ("garde les 3 runs
kaggle, supprime le reste des 15") : `client.delete_run()` (soft delete, récupérable via l'UI
pendant la fenêtre de rétention) + `client.delete_logged_model()` pour chacun des 15 (nécessaire en
plus de `delete_run` — un run supprimé ne retire pas automatiquement son logged model associé des
résultats de `search_logged_models()`). État final vérifié : experiment 4
(`Vitiscan_CNN_resnet_inraeFINE_TUNING`) et 5 (`Vitiscan_CNN_Notebook_GPUFINE_TUNING`) entièrement
vidés (0 logged model restant) ; experiment 3 (`Vitiscan_CNN_Notebook_GPU`) réduit à ses 3 runs
kaggle (`skillful-gnat-43`, `salty-shark-629`, `charming-skink-310`) ; experiment 6
(`Vitiscan_CNN_Resnet_INRAE_FINE_TUNING`) intact avec ses 2 modèles (`polite-mole-465`,
`calm-stag-792`).

### `calm-stag-792` : meilleur modèle, renommé sur S3 pour être compatible

En comparant les métriques finales des runs restants, `calm-stag-792` (`m-e92c29bf6cf54a6aa096920f480201b9`,
experiment `Vitiscan_CNN_Resnet_INRAE_FINE_TUNING`, 30 epochs, `lr=0.0001`, `weight_decay=0.0001`)
a les **meilleures métriques de tous les runs "Vitiscan_*" audités** : `val_acc=0.988`,
`test_acc=0.989`, `f1_weighted` val/test ≈ 0.988 (contre 0.981/0.982 pour `polite-mole-465`,
utilisé jusque-là par défaut).

Son seul défaut : `disease.json` existait mais sous le nom `extra_files/disease-inrae.json` (pas
`disease.json`, le nom attendu par `api/app.py::_load_diseases()`) — probablement une itération du
notebook antérieure à la standardisation du nom de fichier. Contenu vérifié identique
(sept classes, mêmes traductions FR). À la demande de l'utilisateur, **renommé directement sur S3**
(`boto3 copy_object` puis `delete_object` sur
`s3://aws-s3-mlflow/mlflow-artifacts/6/models/m-e92c29bf6cf54a6aa096920f480201b9/artifacts/extra_files/`) —
action ciblée sur un seul petit fichier JSON (pas le `.pth` du modèle), à faible risque et
réversible (le contenu était connu et vérifié avant suppression de l'ancien nom).

`api/.env` et `api/.env.template` mis à jour avec `MLFLOW_MODEL_ID=m-e92c29bf6cf54a6aa096920f480201b9`
(remplace `polite-mole-465`, qui reste un modèle valide mais moins bon).

**Testé de bout en bout avec succès** (les deux modèles, `polite-mole-465` puis `calm-stag-792`) :
`GET /health` → `model_loaded:true` ; `GET /diseases` → les 7 classes avec traduction FR correcte ;
`POST /diagno` sur une vraie photo de test (classe `colomerus_vitis`/Erinose) → prédiction correcte
(99.9% puis 99.999% de confiance avec `calm-stag-792`), avec la liste complète des 7 maladies et
leurs probabilités (le bug de prédiction à une seule entrée mal étiquetée, décrit plus haut, est
résolu).

### Purge complémentaire par l'utilisateur + même correctif appliqué aux 3 modèles kaggle

L'utilisateur a supprimé manuellement les experiments désormais vides `Vitiscan_CNN_resnet_inraeFINE_TUNING`
et `Vitiscan_CNN_Notebook_GPUFINE_TUNING` (0 logged model restant après la purge précédente).

Question posée : les 3 runs kaggle conservés dans `Vitiscan_CNN_Notebook_GPU`
(`skillful-gnat-43`, `salty-shark-629`, `charming-skink-310`) ont le même problème que
`calm-stag-792` — `disease-kaggle.json` au lieu de `disease.json`. **Même correctif appliqué** :
renommage sur S3 (`copy_object` + `delete_object`) pour les 3, contenu vérifié avant/après (7
classes kaggle : anthracnose, brown_spot, downy_mildew, mites, normal, powdery_mildew, shot_hole).
Testé de bout en bout sur le meilleur des 3 (`skillful-gnat-43`, `m-60e1cad60ec94ad6ac73c1fd9947ce87`,
val_acc=0.858/test_acc=0.898) : `/health` et `/diseases` OK.

Deuxième question posée : le champ **"Dataset"** vide dans les attributs du modèle (UI MLflow).
Vérifié : ce champ correspond au mécanisme de lignage de dataset structuré de MLflow
(`mlflow.log_input()`, distinct du simple param `dataset_name`) — **jamais utilisé par aucun des
scripts d'entraînement**, y compris pour `polite-mole-465` qui a pourtant `dataset_name=inrae` en
param. Vide sur tous les modèles restants, pas spécifique à kaggle. **Décision de l'utilisateur :
laissé vide** (cosmétique, l'API ne s'en sert pas, pas de valeur ajoutée dans le temps disponible).

État final des modèles disponibles dans MLflow (post-purge) :

| Experiment | Modèles restants |
|---|---|
| `Vitiscan_CNN_Notebook_GPU` | `skillful-gnat-43`, `salty-shark-629`, `charming-skink-310` (kaggle, `disease.json` OK) |
| `Vitiscan_CNN_Resnet_INRAE_FINE_TUNING` | `polite-mole-465`, `calm-stag-792` (inrae, `disease.json` OK — **`calm-stag-792` configuré par défaut dans `api/.env`, meilleures métriques**) |

### Bugs trouvés et corrigés après le renommage des `disease*.json`

Deux problèmes soulevés par l'utilisateur après le renommage des fichiers `disease-{dataset}.json`
→ `disease.json` sur S3 (pour `calm-stag-792` et les 3 modèles kaggle, cf. ci-dessus) :

1. **Référence cassée dans `MLmodel`** : le fichier artefact `MLmodel` (métadonnées YAML du modèle)
   contient sa propre référence au nom du fichier `extra_files`
   (`flavors.pytorch.extra_files: [{path: extra_files/disease-inrae.json}]` ou `disease-kaggle.json`
   selon le modèle) — renommer le fichier JSON seul, sans mettre à jour cette référence, la rend
   caduque. Sans impact fonctionnel sur `api/app.py` (qui construit l'URI `extra_files/disease.json`
   directement, sans lire `MLmodel`), mais c'est une incohérence de métadonnée qu'il fallait corriger.
   **Corrigé** pour les 4 modèles renommés (`calm-stag-792`,
   `skillful-gnat-43`, `salty-shark-629`, `charming-skink-310`) : `MLmodel` retéléchargé, parsé en
   YAML, le `path` mis à jour vers `extra_files/disease.json`, ré-uploadé sur S3. Vérifié après coup
   que la référence dans `MLmodel` correspond bien au fichier réellement présent sur S3, pour les
   5 modèles restants.
2. **`dataset_name` totalement absent pour `charming-skink-310`** (`tasteful-asp-994` dans l'UI,
   `m-6ae4e0f...`) : ni param MLflow, ni dans le nom du registered model (`ResNet34_ep2`, contre
   `Resnet34_kaggle_ep5`/`Resnet34_kaggle_ep4` pour les deux autres runs kaggle, qui eux avaient déjà
   le dataset dans leur nom). Run visiblement issu d'une itération du notebook encore plus ancienne.
   Déduit du contenu de son `disease.json` (7 classes kaggle, vérifié) : dataset = kaggle. **Corrigé**
   pour ce run, et par cohérence pour les 3 autres runs ambigus (`skillful-gnat-43`, `salty-shark-629`,
   `calm-stag-792`) : ajout du param `dataset_name` sur le run (`MlflowClient.log_param()` — fonctionne
   sur un run déjà `FINISHED` tant que la clé n'existe pas encore) + tag `dataset_name` posé sur le
   registered model version correspondant (`MlflowClient.set_model_version_tag()`, visible directement
   dans la vue "Registered models" de l'UI).

Revalidé de bout en bout après ces deux corrections (`calm-stag-792` toujours configuré par défaut) :
`/health`, `/diseases`, `/diagno` — même prédiction qu'avant (99.9993% de confiance), rien de cassé.

### 10. `dag_train_model` — sweep multi-modèles CNN (Airflow)

L'utilisateur a signalé que `training/config.yml` (liste `models_to_run`, 7 architectures) n'était
lu par aucun code — vestige du gabarit copié sur le projet Fraud Detection, déjà noté comme tel
dans `training/README.md`. Décision : au lieu de le supprimer, le brancher sur un nouveau DAG
Airflow qui orchestre plusieurs lancements successifs de `train.py` (un run = un modèle), plutôt
que de faire boucler `train.py` lui-même sur plusieurs modèles (`train.py` reste volontairement
"un seul modèle à la fois").

Exploration du DAG `dag_train_model` du projet Fraud Detection
(`/data/JEDHA-DL-36/Project_03_Fraud_Detection`) pour s'aligner sur le même choix d'architecture :
lancement en **subprocess dans le conteneur Airflow lui-même** (deps ML installées directement
dans l'image, pas de conteneur Docker séparé — "trop complexe", décision documentée dans le
`specs.md` de Fraud Detection). Différence assumée avec Fraud Detection : là-bas, la boucle
multi-modèles est encapsulée **dans** `train.py` (Airflow ne voit qu'une seule tâche `train`) ;
ici, c'est **Airflow qui orchestre la boucle** via dynamic task mapping
(`PythonOperator.partial(...).expand(...)`) — une tâche Airflow par modèle, visible et rejouable
individuellement dans l'UI, cohérent avec la contrainte "un seul training à la fois" du script
Vitiscan.

Décisions utilisateur pour ce premier sweep :
- Seuls **`resnet18` et `resnet34`** actifs dans `config.yml::models_to_run` — `resnet50`,
  les 3 EfficientNet et MobileNetV2 commentés (pas supprimés).
- EfficientNet/MobileNetV2 commentés aussi pour une raison technique : `config.yml` prévoit un
  `input_size` différent par modèle (224/240/260) mais `data_utils.py` fait un
  `Resize((224, 224))` fixe, quel que soit le modèle — les entraîner tel quel serait sous-optimal.
  Pas de fix `--image-size` dans cette passe (périmètre volontairement réduit).
- Exécution **séquentielle** (`max_active_tis_per_dagrun=1`) — CPU-only, ~15-20 min/modèle déjà
  pour un seul run (`specs.md`, NB Important), pas de GPU dans le conteneur Airflow.

Fichiers ajoutés/modifiés :
- `training/config.yml` : nettoyé (retrait de `experiment_name`/`project_version`/`data.*`
  jamais lus par aucun code), `default_training` complété (`dataset_name`, `patience`,
  `weight_decay` — déjà supportés en CLI par `train.py`, juste absents du fichier).
- `dags/config.py` : nouvelles variables `TRAINING_DIR`, `TRAINING_CONFIG_PATH`,
  `TRAINING_DATA_DIR`, `MLFLOW_URI`, `EXPERIMENT_NAME`, `S3_BUCKET_NAME`.
- `dags/tasks/train_model.py` (nouveau) : `load_models_to_run()` (lit `config.yml`, fusionne
  chaque modèle avec `default_training`) + `train_one_model()` (`subprocess.run` vers
  `train.py`, stdout/stderr hérités → visibles dans les logs de tâche Airflow).
- `dags/dag_train_model.py` (nouveau) : DAG à déclenchement manuel (`schedule=None` — pas encore
  de détection automatique de nouvelles images labellisées, prévue Partie 2 AIA de `specs.md`),
  param `limit_batches` optionnel pour un sweep "smoke test" rapide.
- `airflow/Dockerfile` : installe aussi `training/requirements.txt` dans l'image (même pattern
  que `rag-llm/requirements.txt`) — à surveiller au build : conflit de pins possible entre torch/
  mlflow et sentence-transformers/weaviate-client déjà présents dans la même image.
- `airflow/docker-compose.yml` : montage `../training:/opt/airflow/training:ro` (code) + nouveau
  volume nommé **writable** `vitiscan_training_data:/opt/airflow/training-data` (cache du
  dataset téléchargé, séparé du montage code en lecture seule, persistant entre déclenchements du
  DAG — répond à la question initiale de l'utilisateur sur le cache du dataset, étendue au
  contexte Airflow).
- `airflow/.env.template`, `airflow/start.sh` : nouvelles variables `MLFLOW_URI`,
  `EXPERIMENT_NAME`, `S3_BUCKET_NAME`.

**Build réellement testé cette fois** (`docker build -f airflow/Dockerfile .`, contrairement aux
étapes 6/7 initiales) — a révélé un bug **pré-existant, sans rapport avec ce sweep** :
`rag-llm/requirements.txt` épinglait `fastapi==0.110.0`/`uvicorn==0.30.6` (pour
`sentence-transformers`/`weaviate-client`), ce qui **downgradait** le `fastapi` dont
`apache-airflow-core==3.2.2` a lui-même besoin (`>=0.129.0`, requis par `cadwyn`, utilisé par
`airflow.api_fastapi.execution_api`). Conséquence vérifiée concrètement (pas seulement le warning
pip) : `airflow.api_fastapi.app.create_app()` plantait avec
`ModuleNotFoundError: No module named 'fastapi._compat.v2'` — le conteneur `airflow-apiserver`
aurait planté au démarrage, **avec ou sans le DAG training** (le bug préexistait, juste jamais
détecté faute d'avoir construit l'image jusqu'ici). **Corrigé** : `rag-llm/requirements.txt`
désépinglé (`fastapi>=0.129.0,<1.0.0`, `uvicorn>=0.37.0,<1.0.0`) — laisse pip résoudre une version
compatible à la fois avec `rag-llm`/`sentence-transformers` et `airflow-core`. Revalidé après
correctif : `fastapi` reste à la version d'Airflow (`0.136.1`), `create_app()` fonctionne,
`rag-llm/app/main.py` s'importe toujours sans erreur (`FastAPI` 0.136 rétrocompatible), et
`torch`/`mlflow`/`weaviate-client`/`sentence-transformers` s'importent tous correctement dans la
même image. Reste un warning pip mineur, sans impact constaté (`grpcio-status` demande
`grpcio>=1.80.0`, résolu à `1.78.0` par `weaviate-client` — aucun des imports testés n'en a
souffert), non corrigé dans cette passe.

Images de test (`vitiscan-airflow:build-check*`) supprimées après vérification — seule
`vitiscan-airflow:latest` (buildée par `docker-compose`/`start.sh`) doit être utilisée en usage
réel.

### 11. Migration vers le bucket S3 dédié `s3-vitiscan-data`

L'utilisateur a signalé que `training/` réutilisait le bucket S3 de MLflow (`aws-s3-mlflow`)
comme zone de dépôt pour le dataset (`vitiscan-data/dataset_inrae.zip`) et les copies de
référence de `disease.json` — mauvaise pratique (mélange artefacts MLflow / données métier
Vitiscan). Un nouveau bucket dédié **`s3-vitiscan-data`** a été créé par l'utilisateur, avec la
structure suivante (déjà peuplée manuellement pour `data-inrae`/`data-kaggle`) :
- `data-inrae/` : `dataset_inrae.zip` + `disease-inrae.json`
- `data-kaggle/` : `disease-kaggle.json` seul (pas de zip, kaggle se télécharge directement depuis
  Kaggle)
- `knowledge/current/` (docs utilisés par le RAG en prod) et `knowledge/new/` (dépôt de nouveaux
  docs) — **vides pour l'instant**. Le nommage des maladies est désormais tranché (noms latins
  INRAE + 2 classes Kaggle sans équivalent, cf. `docs/harmonisation-noms-maladies.md`), mais
  l'upload réel du contenu de `rag-llm/data/knowledge/` vers `knowledge/current/` reste à faire
  (pas de credentials AWS actifs dans les sessions où ce renommage a été fait).

Le bucket MLflow (`aws-s3-mlflow`) reste utilisé, mais uniquement pour ce qu'il a toujours fait de
façon implicite : le SDK MLflow y pousse/sert le modèle lui-même (`mlflow.pytorch.log_model`, lu
par `api/app.py`), sans jamais être nommé explicitement par une variable dans ce projet.

Variables renommées pour clarifier lequel des deux buckets chaque variable désigne (les deux
anciennes variables `S3_BUCKET`/`S3_BUCKET_NAME` de `dags/config.py` étaient trop proches pour
être sans ambiguïté) :
- `dags/config.py` section RAG-LLM : `S3_BUCKET`/`S3_PREFIX` (env `VITISCAN_S3_BUCKET`/
  `VITISCAN_S3_PREFIX`) → `RAG_S3_BUCKET`/`RAG_S3_PREFIX`, défauts `s3-vitiscan-data` /
  `knowledge/current/`.
- `dags/config.py` section Training : `S3_BUCKET_NAME` → `TRAINING_S3_BUCKET`, défaut
  `s3-vitiscan-data` (cohérent avec les autres variables déjà préfixées `TRAINING_` dans cette
  section).
- Répercuté dans `dags/tasks/rag_ingestion.py`, `dags/tasks/train_model.py`, `training/train.py`
  (`--s3-bucket`, `--s3-inrae-zip-key` : `vitiscan-data/dataset_inrae.zip` →
  `data-inrae/dataset_inrae.zip`), `training/data_utils.py` (mêmes défauts), et la clé d'upload de
  référence du `disease.json` (`vitiscan-data/disease-{dataset}.json` →
  `data-{dataset}/disease-{dataset}.json`, cohérent avec la structure réellement déposée par
  l'utilisateur).
- `.env`/`.env.template` mis à jour partout (`training/`, `airflow/`) avec la nouvelle variable.
- `rag-llm/.env.template` : ajout de credentials AWS + `RAG_S3_BUCKET` en **préparation
  uniquement** (rien dans `rag-llm/app/` ne les consomme aujourd'hui — l'ingestion S3 reste gérée
  par le DAG Airflow `dag_rag_ingestion`, pas de nouveau code S3 ajouté à `rag-llm/app/` dans
  cette passe, décision explicite de l'utilisateur).

Note de nommage : la demande initiale suggérait un préfixe `MLFLOW_` pour la variable training.
Non retenu — cette variable ne pointe plus vers le bucket MLflow (c'est justement le but du
changement), l'appeler `MLFLOW_*` aurait été trompeur. `TRAINING_S3_BUCKET` a été préféré.

**Non exécuté en réel** : renommage/repointage relu et vérifié (syntaxe Python, `docker-compose
config`, simulation de l'argv généré par `train_one_model()`), mais pas de vrai téléchargement
depuis `s3-vitiscan-data` dans cette session (pas de credentials AWS réels utilisables ici).

## Pour faire tourner la stack réellement

Tous les `.env` présents dans le dépôt sont des copies vides de leur `.env.template` (aucun secret
réel) — à compléter avant utilisation :

- `api/.env`, `training/.env` : credentials AWS (lecture des artifacts MLflow + accès à
  `TRAINING_S3_BUCKET`, cf. section 11) + `MLFLOW_MODEL_ID` du modèle à servir.
- `rag-llm/.env` : `HF_API_TOKEN` (Hugging Face Inference router). Section AWS S3/`RAG_S3_BUCKET`
  présente mais optionnelle (préparée pour plus tard, rien ne la consomme encore, cf. section 11).
- `airflow/.env` : bucket S3 des documents de connaissance RAG (`RAG_S3_BUCKET`, cf. section 11 —
  le bucket existe mais `knowledge/current/` est vide pour l'instant, cf. même section) +
  credentials AWS + `MLFLOW_URI`/`EXPERIMENT_NAME`/`TRAINING_S3_BUCKET` (sweep `dag_train_model`,
  cf. section 10).
- Dataset d'entraînement `inrae` à déposer dans `training/data-inrae/` (zip `dataset_inrae.zip`,
  cf. `training/README.md`) pour un run local (venv) — via le DAG `dag_train_model`, il est
  téléchargé automatiquement dans le volume `vitiscan_training_data` au premier déclenchement.

## Migration Weaviate -> Postgres/pgvector (Neon) + mise en sommeil ngrok

Le plan gratuit Weaviate Cloud était peu fiable (base détruite après inactivité), et le montage de
repli (Weaviate local + tunnel ngrok pour simuler la prod sur Render, cf.
`docs/simulation-prod-ngrok.md`) s'est révélé non fonctionnel (tunnel TCP gRPC ne routant pas le
trafic, cf. ancienne section "Blocage ngrok TCP" de `docs/deploiement-render-streamlit.md`).

Remplacement par Neon (Postgres managé + extension `pgvector`) : persistant, gratuit, joignable
directement depuis Render via `DATABASE_URL`, sans tunnel. `rag-llm/app/weaviate_client.py` est
remplacé par `rag-llm/app/vector_store.py` (même signature `search_treatment_chunks()`, donc
aucun changement dans `rag_pipeline.py` au-delà du nom du context manager). La collection
`VitiScanKnowledge` devient la table `vitiscan_knowledge` (`rag-llm/db/schema.sql`), avec un index
HNSW en distance cosine — équivalent du comportement par défaut de Weaviate. Le garde-fou
test/prod du DAG `dag_rag_ingestion` (ingestion test -> golden prompts -> promotion prod) est
reproduit via le branching natif Neon (branche `test` / branche `prod`) plutôt que 2 instances
Weaviate distinctes.

Le composant ngrok (config `ngrok/ngrok.yml`, service Docker, variables `WEAVIATE_CUSTOM_*` /
`NGROK_AUTHTOKEN`) est mis en sommeil (code commenté, pas supprimé) plutôt que retiré, au cas où
il faille le réactiver pour un autre usage. Testé en conditions réelles sur une base Neon avant
implémentation (`CREATE EXTENSION vector`, index HNSW, opérateur `<=>` à la dimension réelle du
projet, `VECTOR(384)`) : fonctionne sans limitation particulière.

## Déploiement Render réel : 2 bugs trouvés et corrigés (rootDir + OOM rag-llm)

**`rootDir` casse `dockerfilePath`/`dockerContext`** — Le premier déploiement post-migration a
échoué (`invalid local: resolve : lstat /opt/render/project/src/api/api: no such file or
directory`). Cause : `render.yaml` définit `rootDir: api` (resp. `rag-llm`) pour scoper
l'auto-deploy par service, mais contrairement à ce qui était supposé au moment d'introduire ce
champ (commit `7ac921d`), la doc officielle Render est explicite : quand `rootDir` est défini,
`dockerfilePath`/`dockerContext` deviennent relatifs à `rootDir`, pas à la racine du repo.
`dockerfilePath: api/Dockerfile` faisait donc résoudre Render sur `api/api/Dockerfile`
(inexistant). Correctif : `dockerfilePath: Dockerfile` + `dockerContext: .` (relatifs à
`rootDir`), et les 2 `Dockerfile` + `docker-compose.yml` alignés pour utiliser le dossier du
service comme contexte de build partout (`COPY` sans préfixe `api/`/`rag-llm/`) plutôt que la
racine du repo - un seul `Dockerfile` par service, valable en local et sur Render.

**OOM `rag-llm` en prod (torch CUDA involontaire)** — Une fois le rootDir corrigé, `vitiscan-api`
tournait, mais `vitiscan-rag-llm` crashait (process tué, `/health` aussi en échec juste après,
avant de récupérer seul) systématiquement au premier appel `/solutions`. Fausse piste initiale :
quota de bande passante Render dépassé (écarté, l'utilisateur n'avait pas accès aux métriques
CPU/RAM sans plan payant). Cause réelle : **`rag-llm/requirements.txt` n'installait pas
explicitement torch** — `sentence-transformers` (utilisé dans `app/vector_store.py` pour encoder
les embeddings de la recherche RAG) est construit sur PyTorch, qui est donc une dépendance
transitive cachée, pas un ajout arbitraire. Sans contrainte, `pip` installait par défaut le build
PyPI complet avec support CUDA (~2 Go, tout un chapelet de paquets `nvidia-*`), totalement inutile
sur une instance Render CPU-only, et probablement la cause principale du dépassement des 512 Mo
de RAM du plan gratuit. Correctifs :
- `torch==2.5.0+cpu` (même convention que `api/requirements.txt`, qui le faisait déjà) — image
  5.48 Go -> 1.42 Go. `training/requirements.txt` installe séparément `torch==2.5.0` (build GPU
  normal) après celui-ci dans `airflow/Dockerfile`, donc ce pin n'affecte pas l'entraînement CNN.
- `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` / `OPENBLAS_NUM_THREADS=1` / `NUMEXPR_NUM_THREADS=1`
  dans le `Dockerfile` : évite que torch/numpy dimensionnent leurs pools de threads BLAS sur le
  nombre de CPU visibles, disproportionné par rapport au quota CPU réel d'une instance gratuite.
- Préchargement du modèle d'embedding au démarrage (`lifespan`, arrière-plan via
  `run_in_executor`, même pattern que `api/app.py` pour le modèle CNN) plutôt qu'au premier appel
  RAG (lazy loading) — objective le pic mémoire au déploiement plutôt qu'en pleine requête
  utilisateur.

Vérifié en local sous contrainte mémoire équivalente (`docker run --memory=512m`) : `/solutions`
répond 200 en ~3.5s avec un pic mémoire stable à ~354 Mo (69%), contre un crash systématique avant
ce correctif.

## Golden prompts contre la vraie API déployée (`vitiscan-rag-llm-test`)

`dags/tasks/rag_ingestion.py::run_golden_prompts_gate` appelait jusqu'ici `generate_treatment_advice()`
**directement en process** dans le conteneur Airflow (import Python de `app.rag_pipeline`, pas de
HTTP) - cette porte vérifiait donc que les données ingérées dans la branche Neon de test étaient
correctes, mais ne testait jamais le service `rag-llm` **réellement déployé** (Dockerfile,
variables d'environnement Render, limites du plan gratuit...). Or les 2 bugs de déploiement décrits
juste au-dessus (`rootDir` cassant `dockerfilePath`/`dockerContext`, OOM torch CUDA involontaire)
sont justement le genre de problème qu'un test en process ne peut pas détecter - ils ne sont
apparus qu'en conditions réelles sur Render.

Correctif : un 3ᵉ service Render `vitiscan-rag-llm-test` (cf. `render.yaml`), même image que
`vitiscan-rag-llm` mais branché sur la branche Neon **test** (`DATABASE_URL`). La porte de qualité
interroge désormais ce service en HTTP réel (`RAG_LLM_TEST_URL`, cf. `airflow/.env.template`) via
`POST /solutions`, avec une attente préalable sur `/health` (`_wait_for_rag_llm_test_ready`, jusqu'à
180s) pour absorber la mise en veille du plan gratuit Render (15 min d'inactivité, ~30-90s de
réveil, cf. `docs/deploiement-render-streamlit.md`). La logique d'évaluation des cas
(`app/golden_prompts.py`) est inchangée - déjà conçue pour être appelée aussi bien en HTTP (pytest
local, `tests/test_golden_prompts.py`) qu'en process, elle l'est maintenant en HTTP dans les deux
cas. Effet de bord : les identifiants `HF_API_TOKEN` n'ont plus besoin de vivre dans le conteneur
Airflow (retirés de `airflow/docker-compose.yml`/`airflow/.env.template`), puisque l'appel LLM se
fait désormais côté service Render `vitiscan-rag-llm-test`, qui a ses propres identifiants.

## Reste à faire (hors scope de cette passe)

- ~~Étape 8 : tests "golden prompts" (yaml maladies/réponses attendues) pour `rag-llm/`~~ — fait
  (cf. section 8 ci-dessus, `rag-llm/tests/`), exécuté réellement (10 passed, 1 skipped quota HF).
- ~~Brancher les tests golden prompts comme porte de promotion dans `dags/tasks/rag_ingestion.py`~~
  — fait, d'abord en process puis en HTTP réel contre `vitiscan-rag-llm-test` (cf. section "Golden
  prompts contre la vraie API déployée" ci-dessus). Reste à faire : créer le service Render
  `vitiscan-rag-llm-test` (pas de compte Render dans cette session, cf. étapes manuelles listées
  dans cette même section) et déclencher le DAG en conditions réelles pour valider de bout en bout.
- ~~Étape 9 : documentation de déploiement Render (api, rag-llm) et Streamlit Community (ui)~~ —
  fait (cf. section 9 ci-dessus, `docs/deploiement-render-streamlit.md` + `render.yaml`). Reste à
  faire : le déploiement réel (pas de compte Render/Streamlit Cloud dans cette session), et
  trancher l'hébergement Weaviate de prod (cf. section 9).
- ~~Build + test réel de l'image `airflow/Dockerfile` et du DAG `dag_rag_ingestion` de bout en
  bout~~ — fait (cf. section 7bis).
- ~~Déclenchement réel du DAG `dag_train_model`~~ — fait (cf. section 7bis-train ci-dessous).
- ~~Exécution réelle de `training/train.py`~~ — fait, via `dag_train_model` (smoke test
  `limit_batches=2`, cf. section 7bis-train).
- ~~Purge des experiments MLflow `Vitiscan_CNN_MLFlow` et `Vitiscan_CNN`~~ — fait par l'utilisateur.
- ~~Purge des 15 runs sans `dataset_name` ni `disease.json`~~ — fait (runs + logged models
  supprimés, cf. audit metadata ci-dessus). Ne restent dans MLflow que : les 3 runs kaggle de
  `Vitiscan_CNN_Notebook_GPU`, et `polite-mole-465`/`calm-stag-792` dans
  `Vitiscan_CNN_Resnet_INRAE_FINE_TUNING`.
- Partie 2 du TODO (`specs.md`) : UI de labellisation, DAGs de ré-entraînement et de détection de
  drift.
- ~~Vérifier que `training/notebooks/CNN_model_FT.ipynb` s'exécute bien en l'état~~ — fait : smoke
  test dans un conteneur `python:3.11-slim` jetable, sur une copie temporaire du notebook (jamais
  commitée) avec les cellules de rééquilibrage/split sautées (dataset `organized_data_inrae` déjà
  présent) et `epochs=1` (au lieu de 25, pour rester rapide/léger). Exécution complète sans erreur
  via `jupyter nbconvert --execute` : chargement du dataset, fine-tuning ResNet34, métriques,
  logging MLflow (run `nebulous-snail-730`, experiment
  `zzz_smoketest_notebook_verify_delete_me_FINE_TUNING`, à purger manuellement). Confirme que le
  notebook fonctionne de bout en bout, pas seulement par recoupement statique avec `train.py`.
