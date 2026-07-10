# labeling/ — Vitiscan Labeling

Dashboard Streamlit interne pour revoir les photos de feuilles de vigne soumises par les
viticulteurs via `ui/` (cf. `ui/storage.py`) : liste/filtre les photos stockées sur S3 et en Neon
(`vitiscan_photos`, schéma dans `db/schema.sql`), signale les doublons (même photo envoyée
plusieurs fois), permet de trier chaque photo `incoming` en **acceptée** (label confirmé, entre
dans le dataset) ou **rejetée** (label optionnel), et affiche le taux d'accord (drift) entre la
prédiction du modèle en prod et le label humain, globalement et par `model_version`.

Le statut (`incoming` / `accepted` / `rejected`) est reflété physiquement dans S3 : chaque décision
déplace l'objet du préfixe `PHOTOS_S3_PREFIX/incoming/...` vers `PHOTOS_S3_PREFIX/accepted/...` ou
`PHOTOS_S3_PREFIX/rejected/...` (cf. `db.py::accept_photo`/`reject_photo`), même principe que
`knowledge/current/` vs `knowledge/new/` pour le RAG — prépare un futur DAG Airflow qui pourra
lister directement `accepted/` pour construire le dataset de ré-entraînement (cf. `specs.md`).

`db/schema.sql` est la **source unique** du schéma `vitiscan_photos`, également utilisée par
`ui/storage.py` (copiée à l'image au build de `ui/Dockerfile`, ou lue directement dans le dépôt
cloné sur Streamlit Community Cloud) — ne pas dupliquer ce fichier ailleurs.

## Local (sans Docker)

```bash
cp .env.template .env   # puis compléter (AWS_*, DATABASE_URL, API_DIAGNO)
pip install -r requirements.txt
streamlit run app.py
```

## Docker (depuis la racine du dépôt)

```bash
docker build -f labeling/Dockerfile -t vitiscan-labeling labeling
docker run --env-file labeling/.env -p 8503:8501 vitiscan-labeling
```

Voir le `docker-compose.yml` racine (service `labeling`) pour lancer l'ensemble de la stack.

## Limites connues

- **Pas d'authentification** (aucune dans ce projet) : le champ "labeled_by" est une saisie libre,
  non fiable pour l'intégrité/traçabilité des labels.
- **Pas de verrou de concurrence** sur accepter/rejeter : si deux personnes traitent la même photo
  `incoming` en même temps, la seconde décision écrase la première (dernier écrit gagnant) - pas de
  problème pratique pour un usage à une seule personne/petite équipe séquentielle.
- **Bug EXIF GPS hérité de `ui/app.py::get_exif_data`** : `GPSLatitudeRef`/`GPSLongitudeRef` sont
  ignorés (toujours traité comme Nord/Est), non corrigé dans ce composant.
- **Déploiement** : ce composant n'est pour l'instant testé qu'en local (docker-compose), pas
  encore ajouté à `render.yaml` ni à Streamlit Community Cloud — le `Dockerfile` autonome le rend
  ajoutable plus tard sans changement de code.
