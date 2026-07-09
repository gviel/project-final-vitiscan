# Simuler un déploiement prod avec Weaviate local + ngrok

Objectif : déployer `api` et `rag-llm` sur Render (vraie prod), en pointant `rag-llm` vers votre
Weaviate **local** exposé publiquement via ngrok — le temps de simuler/tester sans payer
d'hébergement Weaviate. Complète `docs/deploiement-render-streamlit.md`.

## Pourquoi ce montage (et ses limites)

- **Gratuit**, contrairement à Weaviate Cloud (peu fiable en gratuit) ou Weaviate auto-hébergé sur
  Render (disque persistant payant uniquement, ~7-25 $/mois).
- **Dépend de votre machine** : `rag-llm` sur Render ne fonctionnera que tant que votre Weaviate
  local + le tunnel ngrok tournent. Ce n'est pas une vraie prod 24/7 — c'est une simulation/un test.
- **Le tunnel gRPC (TCP) n'a PAS d'adresse fixe en gratuit** : contrairement au tunnel HTTP (REST),
  qui a un domaine gratuit stable (`*.ngrok-free.dev`), le tunnel TCP change d'adresse à chaque
  redémarrage (adresse réservée = payant, ngrok Personal 8 $/mois). Concrètement : si vous
  redémarrez ngrok, il faudra remettre à jour 2 variables d'environnement sur Render et redéployer
  `rag-llm`. Pour une session de test ponctuelle, démarrez ngrok une fois et gardez-le ouvert
  pendant toute la session.
- **Sécurité** : Weaviate local est déjà passé en authentification par clé API (accès anonyme
  désactivé, cf. `docker-compose.yml`) — indispensable avant d'exposer quoi que ce soit
  publiquement via ngrok.

## Prérequis côté code (déjà fait dans ce dépôt)

- `rag-llm/app/weaviate_client.py` supporte un 3ᵉ mode de connexion `connect_to_custom()`
  (déclenché par `WEAVIATE_CUSTOM_HTTP_HOST`), pour un Weaviate auto-hébergé exposé via un nom
  d'hôte externe quelconque, REST et gRPC sur des tunnels/ports différents.
- Weaviate local (`docker-compose.yml` racine) tourne avec `AUTHENTICATION_APIKEY_ENABLED`, clé
  dans `.env` racine (`WEAVIATE_API_KEY`).

## Étape 1 — Installer ngrok et récupérer votre domaine fixe

```bash
# Installation (si pas déjà fait) - voir https://ngrok.com/download pour votre OS
ngrok config add-authtoken <votre-authtoken>   # trouvé sur https://dashboard.ngrok.com/get-started/your-authtoken
```

Récupérez votre **domaine fixe gratuit** (dev domain) sur
[dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains) (généré automatiquement,
`xxxxx.ngrok-free.dev`) — c'est celui du tunnel HTTP (REST), il ne changera pas.

## Étape 2 — Vérifier que la stack locale tourne

```bash
cd /data/JEDHA-DL-36/Project_Vitiscan
docker-compose up -d weaviate
docker ps --filter name=vitiscan_weaviate --format "{{.Names}}: {{.Status}}"   # doit être "healthy"
```

## Étape 3 — Lancer les 2 tunnels ngrok (à garder ouverts pendant toute la session)

Dans 2 terminaux séparés (ou `ngrok start` avec un fichier de config listant les 2 tunnels) :

```bash
# Terminal 1 : tunnel HTTP pour le REST (port 8081 côté hôte -> domaine fixe)
ngrok http 8081 --domain=xxxxx.ngrok-free.dev

# Terminal 2 : tunnel TCP pour le gRPC (port 50051 côté hôte -> adresse aléatoire, notez-la)
ngrok tcp 50051
```

Le terminal 2 affiche une ligne du type `Forwarding tcp://0.tcp.ngrok.io:XXXXX -> localhost:50051`
— notez l'hôte (`0.tcp.ngrok.io`) et le port (`XXXXX`), ils changeront au prochain redémarrage.

## Étape 4 — Vérifier les tunnels avant de toucher à Render

```bash
# REST via le tunnel HTTP (doit renvoyer 401 sans clé, 200 avec la clé - cf. .env racine)
curl -s -o /dev/null -w "%{http_code}\n" https://xxxxx.ngrok-free.dev/v1/objects
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <WEAVIATE_API_KEY>" https://xxxxx.ngrok-free.dev/v1/objects
```

## Étape 5 — Configurer les variables d'environnement sur Render (service `vitiscan-rag-llm`)

Dans le dashboard Render, service `vitiscan-rag-llm` → Environment :

| Variable | Valeur |
|---|---|
| `WEAVIATE_CUSTOM_HTTP_HOST` | `xxxxx.ngrok-free.dev` (sans `https://`) |
| `WEAVIATE_CUSTOM_HTTP_PORT` | `443` |
| `WEAVIATE_CUSTOM_HTTP_SECURE` | `true` |
| `WEAVIATE_CUSTOM_GRPC_HOST` | `0.tcp.ngrok.io` (noté à l'étape 3, terminal 2) |
| `WEAVIATE_CUSTOM_GRPC_PORT` | le port noté à l'étape 3 (ex. `XXXXX`) |
| `WEAVIATE_CUSTOM_GRPC_SECURE` | `false` (tunnel TCP brut, pas de TLS applicatif côté Weaviate) |
| `WEAVIATE_API_KEY` | la même clé que `.env` racine |

Render redéploie automatiquement après un changement de variable d'environnement.

## Étape 6 — Vérifier de bout en bout

```bash
curl https://<votre-service-rag-llm>.onrender.com/health
curl -X POST https://<votre-service-rag-llm>.onrender.com/solutions \
  -H "Content-Type: application/json" \
  -d '{"cnn_label":"guignardia_bidwellii","mode":"conventionnel","severity":"forte","area_m2":5000}'
```

`treatment_plan` doit être non vide — preuve que Render (prod) atteint bien votre Weaviate local via
les 2 tunnels ngrok.

## Si le tunnel gRPC redémarre

Relancez `ngrok tcp 50051`, notez la nouvelle adresse, mettez à jour `WEAVIATE_CUSTOM_GRPC_HOST` /
`WEAVIATE_CUSTOM_GRPC_PORT` sur Render. Le tunnel HTTP (REST), lui, garde son adresse.
