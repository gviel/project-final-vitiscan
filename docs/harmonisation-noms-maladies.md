# Harmonisation des noms de maladies — audit du pipeline

Audit demandé pour retracer le nom d'une maladie à travers tout le pipeline (`training/` ->
`api/` -> `rag-llm/` -> `ui/`), détecter les incohérences, et servir de base à une passe
d'harmonisation. Complète `docs/refactoring.md`, qui avait déjà repéré le problème sans le
résoudre (cf. §3).

## ✅ Résolution appliquée

L'option **B** (§5) a été retenue et appliquée : les noms latins INRAE sont désormais
l'identifiant canonique unique (`id` == `cnn_label`) dans `rag-llm/data/knowledge/*.md`,
`app/diseases.py` et `app/dosage_rules.py` — le vocabulaire `Grape_*_leaf` a été entièrement
retiré. Décision produit complémentaire pour lever l'ambiguïté du §3 : la fiche
`Grape_Mites_leaf_disease.md` a été **supprimée** (agent pathogène identique à Erinose,
confirmé = `colomerus_vitis` par l'audit S3). Les 2 seules maladies sans équivalent INRAE
(`brown_spot`, `shot_hole`) gardent leur nom de classe Kaggle tel quel comme identifiant canonique.

Nouveau mapping (fichier = `id` = `cnn_label`, sauf mention contraire) :

| Ancien `Grape_*` | Nouveau canonique | Origine |
|---|---|---|
| `Grape_Anthracnose_leaf` | `elsinoe_ampelina` | INRAE (latin) |
| `Grape_Black_rot_leaf` | `guignardia_bidwellii` | INRAE (latin) |
| `Grape_Downy_mildew_leaf` | `plasmopara_viticola` | INRAE (latin) |
| `Grape_Erinose_leaf` | `colomerus_vitis` | INRAE (latin) |
| `Grape_Esca_leaf` | `phaeomoniella_chlamydospora` | INRAE (latin) |
| `Grape_Normal_leaf` | `sain` | INRAE (pas de latin pour "pas de maladie") |
| `Grape_Powdery_mildew_leaf` | `erysiphe_necator` | INRAE (latin) |
| `Grape_Brown_spot_leaf` | `brown_spot` | Kaggle (gardé tel quel) |
| `Grape_shot_hole_leaf_disease` | `shot_hole` | Kaggle (gardé tel quel) |
| `Grape_Mites_leaf_disease` | *(supprimé)* | redondant avec `colomerus_vitis` |

Conséquence : `search_treatment_chunks()` (`weaviate_client.py`) n'a plus besoin de deviner si
l'entrée est un `cnn_label` ou un `disease_id` (les deux valent désormais la même chose) — filtre
simplifié en `(cnn_label == key) OR (disease_id == key)` sans heuristique de préfixe.
`CNN_LABEL_ALIASES` ne sert plus qu'à la compat ascendante (anciens alias courts anglais tapés à
la main, ex. champ debug de l'UI).

Le reste de ce document est conservé tel quel comme trace de l'audit d'origine (état *avant*
résolution) — ses références à `Grape_*` décrivent cet état passé, pas le code actuel.

---

## TL;DR

Le projet utilise **3 nomenclatures différentes** pour désigner une maladie, et **aucune
traduction n'existe entre la nomenclature INRAE (latin) et celle utilisée par `rag-llm/`**.

Conséquence concrète avec le modèle réellement en prod (dataset **inrae**, cf. `specs.md` et
`training/.env`) : `POST /diagno` renvoie des labels latins (`colomerus_vitis`,
`guignardia_bidwellii`, `plasmopara_viticola`...). Ce label est transmis tel quel comme
`cnn_label` à `POST /solutions` (rag-llm). Or `rag-llm/app/diseases.py::CNN_LABEL_ALIASES` ne
connaît que des alias anglais courts (`erinose`, `black_rot`, `downy_mildew`...). Résultat :

1. `normalize_cnn_label("guignardia_bidwellii")` ne trouve rien dans `CNN_LABEL_ALIASES` -> renvoie
   le label latin **inchangé**.
2. `search_treatment_chunks()` (`rag-llm/app/weaviate_client.py`) ne reconnaît pas ce label comme
   `Grape_*` -> le traite comme un `disease_id` -> aucun document Weaviate n'a
   `disease_id="guignardia_bidwellii"` (les fiches utilisent `grape_black_rot`, etc.) -> **0 chunk
   trouvé**, même avec les 2 fallbacks (retry sans mode, puis `disease_id_guess = f"grape_{label}"`
   qui donnerait `grape_guignardia_bidwellii`, toujours aucune correspondance).
3. `generate_treatment_advice()` (`rag-llm/app/rag_pipeline.py:213-233`) part alors sur la réponse
   de repli générique : *"Les informations disponibles sur cette maladie sont insuffisantes...
   consultez un technicien viticole local."*
4. Même chose pour `compute_dosage()` (`dosage_rules.py`) : `cnn_label_norm` reste le label latin,
   absent de `DOSAGE_RULES` -> dict vide `{}`.

**En pratique, avec le modèle INRAE actuellement en prod, l'API `/solutions` ne peut jamais
produire de vrai plan de traitement RAG — elle tombe systématiquement sur le message de repli**,
sauf si quelqu'un teste avec un `cnn_label` anglais tapé à la main (ce que permet le champ
`cnn_label` de l'UI en mode debug, ce qui masque le problème en test manuel).

Ce trou avait déjà été identifié une fois, jamais comblé : `docs/refactoring.md` lignes 123-126 et
244 ("⚠️ pas de traduction automatique vers les labels métier utilisés par
`rag-llm/app/diseases.py`... à curer manuellement").

---

## 1. Les 3 nomenclatures en présence

### A. INRAE — dataset réellement utilisé en prod (latin)
Noms de dossiers du dataset = classes réelles du CNN déployé. Source : `training/disease_labels.py`
(confirmé identique à `s3://aws-s3-mlflow/vitiscan-data/disease-inrae.json`) :

| classe CNN (clé, = ce que renvoie `/diagno`) | traduction FR (valeur, dans `disease.json`) |
|---|---|
| `colomerus_vitis` | Erinose |
| `elsinoe_ampelina` | Anthracnose |
| `erysiphe_necator` | Oïdium |
| `guignardia_bidwellii` | Pourriture_noire |
| `phaeomoniella_chlamydospora` | Esca |
| `plasmopara_viticola` | Mildiou |
| `sain` | Pas de maladie |

### B. Kaggle — dataset archivé, 7 classes (anglais court)
Toujours fonctionnel via `--dataset-name kaggle` mais plus utilisé en prod (`specs.md` : "le dataset
kaggle n'est pas un bon dataset"). Source : `training/disease_labels.py` :

| classe CNN (clé) | traduction FR |
|---|---|
| `anthracnose` | Anthracnose |
| `brown_spot` | Tâche brune |
| `downy_mildew` | Mildiou |
| `mites` | Acariens |
| `normal` | Pas de maladie |
| `powdery_mildew` | Oïdium |
| `shot_hole` | Coryneum |

### C. rag-llm — alias anglais courts + label canonique `Grape_*_leaf`
Hérité du vocabulaire type PlantVillage/Kaggle. Source : `rag-llm/app/diseases.py::CNN_LABEL_ALIASES` :

| alias attendu en entrée | label canonique (clé Weaviate/dosage) |
|---|---|
| `anthracnose` | `Grape_Anthracnose_leaf` |
| `black_rot` | `Grape_Black_rot_leaf` |
| `brown_spot` | `Grape_Brown_spot_leaf` |
| `downy_mildew` | `Grape_Downy_mildew_leaf` |
| `erinose` | `Grape_Erinose_leaf` |
| `esca` | `Grape_Esca_leaf` |
| `mites` | `Grape_Mites_leaf_disease` |
| `normal` | `Grape_Normal_leaf` |
| `powdery_mildew` | `Grape_Powdery_mildew_leaf` |
| `shot_hole` | `Grape_shot_hole_leaf_disease` |

Ce label canonique sert à la fois de clé dans `dosage_rules.py::DOSAGE_RULES`/`TREATMENT_PRODUCTS`
et de valeur `cnn_label` dans le frontmatter des 10 fiches `rag-llm/data/knowledge/*.md` (indexées
dans Weaviate, propriété `cnn_label`), avec un `disease_id` associé (ex: `grape_black_rot`).

---

## 2. Parcours complet d'un nom de maladie, couche par couche

Exemple suivi : la maladie causée par *Guignardia bidwellii* ("black rot"), prédite par le modèle
INRAE en prod.

| # | Couche / fichier | Valeur du nom à cette étape |
|---|---|---|
| 1 | Dataset (dossier) | `guignardia_bidwellii` |
| 2 | `training/disease_labels.py::build_disease_json` | `{"guignardia_bidwellii": "Pourriture_noire"}` |
| 3 | `train.py` -> loggé comme `extra_files/disease.json` du modèle MLflow | idem |
| 4 | `api/app.py::_load_diseases` -> `DISEASES` (global) | `{"guignardia_bidwellii": "Pourriture_noire", ...}` |
| 5 | `POST /diagno` -> `PredictionResponse.predictions[i].disease` | **`"guignardia_bidwellii"`** (la clé brute — la traduction FR n'est jamais utilisée ici, cf. `api/app.py:82-84`) |
| 6 | `GET /diseases` -> `DiseasesResponse.diseases` | `{"guignardia_bidwellii": "Pourriture_noire", ...}` (sert à l'UI pour l'affichage FR) |
| 7 | `ui/app.py::get_diseases()` + affichage (`DISEASE_TRANSLATION.get(disease, disease)`) | Affiché "Pourriture_noire" — **correct**, car l'UI récupère sa table de traduction depuis la même source (`/diseases`) que celle qui a produit `disease` (étape 5) |
| 8 | `ui/app.py` -> `cnn_label` envoyé à `POST /solutions` | **`"guignardia_bidwellii"`** (valeur brute de l'étape 5, pas de traduction avant l'envoi) |
| 9 | `rag-llm/app/rag_pipeline.py::generate_treatment_advice` -> `normalize_cnn_label("guignardia_bidwellii")` | **`"guignardia_bidwellii"` inchangé** (absent de `CNN_LABEL_ALIASES`) ⚠️ |
| 10 | `search_treatment_chunks()` -> filtre Weaviate | `disease_id == "guignardia_bidwellii"` (traité comme un `disease_id`, car ne commence pas par `Grape_`) — **aucune fiche n'a cet id** (la fiche existe sous `disease_id: grape_black_rot`) ⚠️ |
| 11 | `compute_dosage()` -> `DOSAGE_RULES.get("guignardia_bidwellii")` | **absent** -> dict vide `{}` ⚠️ |
| 12 | Réponse finale `/solutions` | Message de repli générique, pas de vrai plan de traitement ⚠️ |

L'étape 7 (affichage FR dans l'UI) fonctionne bien car elle referme la boucle sur elle-même
(l'UI retraduit avec la table qu'elle vient de récupérer). Le problème est strictement dans le
passage **api -> rag-llm** (étapes 8 à 12), qui suppose implicitement un vocabulaire (B/C) que le
modèle en prod (A) ne produit jamais.

---

## 3. Correspondance conceptuelle manquante (à coder)

Les 7 classes INRAE correspondent en réalité, une à une, à 7 des 10 entrées de
`CNN_LABEL_ALIASES` — mais **ce mapping n'existe nulle part dans le code**, il n'a été
reconstitué que par lecture croisée des fiches `.md` (champ `agent_pathogene`) et de
`training/disease_labels.py` :

| INRAE (latin, sortie réelle de `/diagno`) | agent visé | alias rag-llm attendu | fiche RAG / clé dosage |
|---|---|---|---|
| `colomerus_vitis` | acarien *Colomerus vitis* | `erinose` | `Grape_Erinose_leaf` |
| `elsinoe_ampelina` | champignon *Elsinoë ampelina* | `anthracnose` | `Grape_Anthracnose_leaf` |
| `erysiphe_necator` | champignon *Erysiphe necator* | `powdery_mildew` | `Grape_Powdery_mildew_leaf` |
| `guignardia_bidwellii` | champignon *Guignardia bidwellii* | `black_rot` | `Grape_Black_rot_leaf` |
| `phaeomoniella_chlamydospora` | complexe esca | `esca` | `Grape_Esca_leaf` |
| `plasmopara_viticola` | champignon *Plasmopara viticola* | `downy_mildew` | `Grape_Downy_mildew_leaf` |
| `sain` | — | `normal` | `Grape_Normal_leaf` |

⚠️ **Ambiguïté à trancher** (déjà signalée dans `docs/refactoring.md:125` mais toujours ouverte) :
`rag-llm/data/knowledge/Grape_Mites_leaf_disease.md` cite lui aussi *Colomerus vitis* comme agent
pathogène ("Acariens ériophyides (*Colomerus vitis*)"). Le dataset INRAE n'a pourtant qu'**une
seule classe** pour cet acarien (`colomerus_vitis`), confirmée = **Erinose** par l'audit S3
(`docs/refactoring.md:244`). Tant que le modèle en prod reste INRAE, la fiche `Grape_Mites_leaf_disease.md`
et l'alias `mites` ne seront donc **jamais atteignables** — de même que `brown_spot` et
`shot_hole`, qui n'ont pas d'équivalent dans les 7 classes INRAE (ce sont des classes propres au
dataset Kaggle archivé).

---

## 4. Autres incohérences / points d'attention relevés

- **`rag_pipeline.py:236`** : `disease_name_fr = DISEASE_FR.get(cnn_label)` utilise le `cnn_label`
  brut (non passé par `normalize_cnn_label`), contrairement au reste du fichier — incohérent avec
  `search_treatment_chunks`/`compute_dosage`, qui eux acceptent aussi bien un alias court qu'un
  label `Grape_*_leaf`. Actuellement sans conséquence visible tant que le problème de fond (§3)
  n'est pas résolu, mais à corriger dans la même passe pour rester cohérent.
- **3 alias rag-llm morts avec le modèle INRAE en prod** : `brown_spot`, `mites`, `shot_hole` (+
  leurs fiches `.md` et règles de dosage associées) ne peuvent être déclenchés que par le modèle
  Kaggle archivé. À garder "au cas où" ou à retirer, à trancher selon si un retour au dataset
  Kaggle est envisagé.
- **`training/config.yml`** : fichier non lu par aucun code (`grep` sur tout le dépôt : seule
  référence = un commentaire dans `model_registry.py` et le `README.md` de `training/`, qui le
  documente explicitement comme "référence, non lu automatiquement"). Cf. point 2 de la demande
  initiale, traité séparément.
- **Fichiers résiduels** : `training/.env.swp` et `training/.config.yml.swp` (swap Vim, gitignorés
  donc sans risque, mais probablement à supprimer — confirmer avant suppression).

---

## 5. Pistes d'harmonisation (à trancher, pas encore décidé)

**A. Fix minimal (recommandé pour débloquer le pipeline rapidement)** : ajouter la table du §3
  (`colomerus_vitis` -> `erinose`, etc.) dans `rag-llm/app/diseases.py`, et l'utiliser en premier
  dans `normalize_cnn_label()` (et l'équivalent `dosage_rules._normalize_cnn_label()`) avant de
  chercher dans `CNN_LABEL_ALIASES`. Corrige aussi `rag_pipeline.py:236` pour utiliser
  `normalize_cnn_label` de façon cohérente. Impact limité, pas de renommage de fiches/documents déjà
  indexés dans Weaviate.

**B. Nommage canonique unique de bout en bout** : puisque `specs.md` est clair sur le fait
  qu'INRAE est LE dataset cible (Kaggle est archivé), on pourrait à terme adopter les noms latins
  INRAE comme identifiant canonique partout (fiches `.md`, `DOSAGE_RULES`, propriété Weaviate),
  et abandonner le vocabulaire `Grape_*_leaf`/anglais hérité de Kaggle/PlantVillage. Plus gros
  chantier (renommage de 10 fichiers + ré-ingestion Weaviate + mise à jour de 2 dicts), mais élimine
  la couche de traduction et la confusion "est-ce un nom kaggle ou inrae ?" une fois pour toutes.

**C. Décision produit** à prendre avec un avis viticole (déjà demandé dans `docs/refactoring.md`) :
  que faire de `mites`/`brown_spot`/`shot_hole`, non couverts par le modèle en prod ?

Recommandation : commencer par **A** (correctif ciblé, sans régression), et n'envisager **B** que
si vous voulez vraiment figer un nommage unique avant la soutenance/la mise en prod finale.
