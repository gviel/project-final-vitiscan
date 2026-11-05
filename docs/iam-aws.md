# Accès AWS (IAM) — un user par rôle

Vitiscan lit et écrit dans S3 depuis plusieurs composants. Chacun a **sa propre clé AWS**, rattachée à
un user IAM dont les droits sont limités à ce que le composant fait réellement. Aucune clé n'est
partagée entre rôles, et aucun user n'a de policy managée du type `AmazonS3FullAccess`.

Pourquoi : `api/`, `ui/` et `labeling/` sont déployés en ligne (Render, Streamlit Community Cloud). Si
une de leurs clés fuit, l'attaquant ne doit pouvoir ni supprimer de photos, ni écrire dans les
datasets, ni remplacer un modèle. Ces risques ont déjà été rencontrés : une clé AWS a fuité dans
l'historique git (sortie d'un notebook qui affichait `os.environ`) et a dû être révoquée.

## Buckets

| Bucket | Contenu |
|---|---|
| `s3-vitiscan-data` | `knowledge/current/` (documents RAG), `user-photos/{incoming,accepted,rejected}/` (photos), `data-inrae/` et `data-kaggle/` (datasets + `disease-*.json`) |
| `aws-s3-mlflow` | `mlflow-artifacts/` : artefacts et modèles MLflow (serveur MLflow sur Hugging Face Spaces) |

## Qui utilise quelle clé

| User IAM | Composant | Fichier local | Déploiement en ligne | Ce que le code fait |
|---|---|---|---|---|
| `vitiscan-api` | `api/` | `~/.vitiscan/api/.env` | Render (`vitiscan-api`) | charge le modèle via MLflow : **lecture** et listing des artefacts |
| `vitiscan-ui` | `ui/` | `~/.vitiscan/ui/.env` | Streamlit Community Cloud | dépose la photo dans `user-photos/incoming/` (**écriture seule**) |
| `vitiscan-labeling` | `labeling/` | `~/.vitiscan/labeling/.env` | Streamlit Community Cloud | lit les photos (liens présignés) et les **déplace** (copie puis suppression) |
| `vitiscan-pipeline` | `airflow/`, `training/` | `~/.vitiscan/airflow/.env`, `~/.vitiscan/training/.env` | local | lit `knowledge/`, les photos et les datasets, écrit `disease-*.json`, lit/écrit les artefacts MLflow |
| *(aucun)* | `rag-llm/` | `~/.vitiscan/rag-llm/.env.*` | Render (`vitiscan-rag-llm`, `vitiscan-rag-llm-validation`) | n'accède pas à S3 : les clés AWS y restent vides |

Le serveur MLflow (Hugging Face Space) utilise une clé séparée, limitée à `aws-s3-mlflow`,
qui n'est pas gérée par ce dépôt.

`rag-llm/` a tout de même un secret : la clé de son fournisseur LLM, dans `HF_API_TOKEN`. Ce n'est
pas une clé AWS et elle n'est pas gérée par IAM. Le nom `HF_*` est historique : le service appelle
aujourd'hui une API compatible OpenAI (Groq, quota gratuit) via `HF_API_URL`, `HF_API_TOKEN` et
`HF_MODEL_ID` (voir `rag-llm/.env.template`). Elle se renouvelle chez le fournisseur et doit être
mise à jour sur **chacun** des services Render qui l'utilisent, en plus des `.env` locaux.

## Droits de chaque user

Résumé :

| User | Lecture | Écriture | Suppression |
|---|---|---|---|
| `vitiscan-api` | `aws-s3-mlflow/mlflow-artifacts/*` (+ listing) | non | non |
| `vitiscan-ui` | non | `s3-vitiscan-data/user-photos/incoming/*` | non |
| `vitiscan-labeling` | `s3-vitiscan-data/user-photos/*` | `s3-vitiscan-data/user-photos/*` | `s3-vitiscan-data/user-photos/*` |
| `vitiscan-pipeline` | `knowledge/*`, `user-photos/*`, `data-inrae/*`, `data-kaggle/*`, `mlflow-artifacts/*` (+ listing) | `data-inrae/*`, `data-kaggle/*`, `mlflow-artifacts/*` | non |

La suppression n'est accordée qu'à `vitiscan-labeling`, parce que déplacer une photo
(`incoming/` -> `accepted/` ou `rejected/`) est une copie suivie d'une suppression.

Policies inline (une par user, nommée `<user>-s3`) :

### vitiscan-api
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MlflowArtifactsRead",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::aws-s3-mlflow/mlflow-artifacts/*"
      ]
    },
    {
      "Sid": "MlflowArtifactsList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::aws-s3-mlflow",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "mlflow-artifacts/*",
            "mlflow-artifacts/"
          ]
        }
      }
    }
  ]
}
```

### vitiscan-ui
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PhotosIncomingWriteOnly",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::s3-vitiscan-data/user-photos/incoming/*"
      ]
    }
  ]
}
```

### vitiscan-labeling
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PhotosReadWriteMove",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::s3-vitiscan-data/user-photos/*"
      ]
    }
  ]
}
```

### vitiscan-pipeline
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DataRead",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::s3-vitiscan-data/knowledge/*",
        "arn:aws:s3:::s3-vitiscan-data/user-photos/*",
        "arn:aws:s3:::s3-vitiscan-data/data-inrae/*",
        "arn:aws:s3:::s3-vitiscan-data/data-kaggle/*"
      ]
    },
    {
      "Sid": "DatasetsWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::s3-vitiscan-data/data-inrae/*",
        "arn:aws:s3:::s3-vitiscan-data/data-kaggle/*"
      ]
    },
    {
      "Sid": "DataList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::s3-vitiscan-data",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "knowledge/*",
            "knowledge/",
            "user-photos/*",
            "user-photos/"
          ]
        }
      }
    },
    {
      "Sid": "MlflowArtifactsReadWrite",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::aws-s3-mlflow/mlflow-artifacts/*"
      ]
    },
    {
      "Sid": "MlflowArtifactsList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::aws-s3-mlflow",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "mlflow-artifacts/*",
            "mlflow-artifacts/"
          ]
        }
      }
    }
  ]
}
```

## Créer ou renouveler une clé

À faire avec un profil administrateur. La clé est écrite directement dans un fichier lisible par
vous seul : elle ne s'affiche ni dans le terminal ni dans l'historique du shell, et ne doit jamais
être collée dans un chat :

```bash
umask 077
aws iam create-access-key --user-name vitiscan-api \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text > vitiscan-api.key
```

Reporter ensuite l'identifiant et le secret dans le `.env` du composant (et dans les secrets de
Render / Streamlit Cloud pour les composants déployés), puis détruire le fichier
(`shred -u vitiscan-api.key`). Pour renouveler : créer la nouvelle clé, mettre à jour tous les
endroits qui l'utilisent, vérifier, puis supprimer l'ancienne (`aws iam delete-access-key`).

## Vérifier qu'une clé fonctionne (lecture seule)

```bash
set -a; source ~/.vitiscan/airflow/.env; set +a      # le .env du composant testé
aws sts get-caller-identity --query Arn --output text        # doit afficher le bon user
aws s3api list-objects-v2 --bucket s3-vitiscan-data --prefix knowledge/current/ --max-items 2
aws s3api list-objects-v2 --bucket s3-vitiscan-data --max-items 1   # doit être refusé (AccessDenied)
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN     # avant de repasser en admin
```

Sans clé, le simulateur IAM évalue une policy sans rien écrire :

```bash
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::<ID_COMPTE>:user/vitiscan-ui \
  --action-names s3:PutObject --resource-arns arn:aws:s3:::s3-vitiscan-data/user-photos/incoming/x.jpg
```

## Vérifier qu'un déploiement en ligne utilise la nouvelle clé

Les `.env` locaux ne prouvent rien sur Render ou Streamlit Cloud : leurs secrets sont séparés. Après
une rotation, faire une vraie action dans l'application, puis demander à IAM quand la clé a servi
(avec un profil administrateur) :

```bash
aws iam get-access-key-last-used --access-key-id <ID_DE_LA_CLE> \
  --query 'AccessKeyLastUsed.[LastUsedDate,ServiceName,Region]' --output text
```

Une date postérieure à l'action et le service `s3` confirment que le déploiement utilise bien cette
clé. Actions de test par composant :

| Composant | Action à faire dans l'application | Droits exercés |
|---|---|---|
| `api` | appeler `/health` : doit répondre `"model_loaded": true` | `GetObject` + `ListBucket` sur `mlflow-artifacts/` |
| `ui` | envoyer une photo : elle apparaît dans `user-photos/incoming/` | `PutObject` |
| `labeling` | accepter ou rejeter une photo | `GetObject`, `PutObject`, `DeleteObject` |

Ce parcours a été fait en conditions réelles (photo envoyée par `ui`, puis acceptée dans `labeling`)
le 2026-11-04 : aucun refus, les policies ci-dessus suffisent.

## Une erreur 403 / AccessDenied

Lire le message : il nomme l'**action** et la **ressource** refusées (`not authorized to perform:
s3:... on resource: ...`). Si l'accès est légitime, ajouter cette action sur cette ressource à la
policy du user concerné, au plus juste. Ne pas remplacer la clé par une clé plus puissante.
Cas déjà rencontrés :

- le chargement d'un modèle MLflow **liste** les artefacts avant de les lire : `s3:ListBucket` est
  nécessaire sur `aws-s3-mlflow` avec la condition `s3:prefix` = `mlflow-artifacts/*` ;
- `copy_object` exige `s3:GetObject` sur la source et `s3:PutObject` sur la destination ;
- `InvalidAccessKeyId` / `InvalidClientTokenId` (et non `AccessDenied`) : la clé n'existe plus dans
  IAM. Un déploiement garde l'ancienne clé dans ses secrets (Render, Streamlit Cloud) ou n'a pas été
  redémarré après leur modification. Ce n'est pas un problème de policy : mettre à jour le secret
  puis redémarrer le service.

## Règles

- Une clé par rôle, jamais de clé partagée entre un composant exposé et un composant interne.
- Pas de `AdministratorAccess` ni de `*FullAccess`, pas de `s3:*`, pas de ressource `*`.
- Aucun secret dans le code, dans un notebook ni dans une sortie de cellule : lire `os.environ` et ne
  jamais afficher son contenu. Utiliser `nbstripout` pour vider les sorties avant commit.
- Les `.env` réels restent en `600`, hors git (`.gitignore`).
- Activer le *secret scanning* et la *push protection* GitHub sur le dépôt.
