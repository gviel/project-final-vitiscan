# Simuler un déploiement prod avec Weaviate local + ngrok

Objectif : déployer `api` et `rag-llm` sur Render (vraie prod), en pointant `rag-llm` vers votre
Weaviate **local** exposé publiquement via ngrok — le temps de simuler/tester sans payer
d'hébergement Weaviate. Complète `docs/deploiement-render-streamlit.md`.

ngrok tourne en conteneur Docker (`ngrok/ngrok`, image officielle), comme le reste de la stack —
pas de binaire à installer sur l'hôte.

## Pourquoi ce montage (et ses limites)

- **Gratuit**, contrairement à Weaviate Cloud (peu fiable en gratuit) ou Weaviate auto-hébergé sur
  Render (disque persistant payant uniquement, ~7-25 $/mois).
- **Dépend de votre machine** : `rag-llm` sur Render ne fonctionnera que tant que votre Weaviate
  local + le conteneur ngrok tournent. Ce n'est pas une vraie prod 24/7 — c'est une simulation/un test.
- **Le tunnel gRPC (TCP) n'a PAS d'adresse fixe en gratuit** : contrairement au tunnel HTTP (REST),
  qui a un domaine gratuit stable (`*.ngrok-free.dev`), le tunnel TCP change d'adresse à chaque
  redémarrage (adresse réservée = payant, ngrok Personal 8 $/mois). Concrètement : si vous
  redémarrez le conteneur ngrok, il faudra remettre à jour 2 variables d'environnement sur Render
  et redéployer `rag-llm`. Pour une session de test ponctuelle, démarrez ngrok une fois et gardez-le
  ouvert pendant toute la session.
- **Carte bancaire requise côté ngrok** : les tunnels TCP (nécessaires pour le gRPC) exigent une
  méthode de paiement enregistrée sur le compte ngrok, même en plan gratuit (pas de prélèvement,
  juste une vérification).
- **Sécurité** : Weaviate local est déjà passé en authentification par clé API (accès anonyme
  désactivé, cf. `docker-compose.yml`) — indispensable avant d'exposer quoi que ce soit
  publiquement via ngrok.

## Prérequis côté code (déjà fait dans ce dépôt)

- `rag-llm/app/weaviate_client.py` supporte un 3ᵉ mode de connexion `connect_to_custom()`
  (déclenché par `WEAVIATE_CUSTOM_HTTP_HOST`), pour un Weaviate auto-hébergé exposé via un nom
  d'hôte externe quelconque, REST et gRPC sur des tunnels/ports différents.
- Weaviate local (`docker-compose.yml` racine) tourne avec `AUTHENTICATION_APIKEY_ENABLED`, clé
  dans `.env` racine (`WEAVIATE_API_KEY`).
- Service `ngrok` déclaré dans `docker-compose.yml` racine (profile `ngrok`, ne démarre pas avec un
  `docker-compose up` normal) + config dans `ngrok/ngrok.yml`.

## Étape 1 — Récupérer votre authtoken et votre domaine fixe

Sur [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken) :
copiez votre authtoken.

Sur [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains) : récupérez votre **domaine
fixe gratuit** (dev domain, généré automatiquement, `xxxxx.ngrok-free.dev`).

Ajoutez une méthode de paiement sur votre compte ngrok (nécessaire pour les tunnels TCP, cf.
limites ci-dessus) : [dashboard.ngrok.com/billing](https://dashboard.ngrok.com/billing).

## Étape 2 — Configurer

```bash
cd /data/JEDHA-DL-36/Project_Vitiscan

# Dans .env racine (créé à partir de .env.template si pas déjà fait) :
#   NGROK_AUTHTOKEN=<votre authtoken>

# Dans ngrok/ngrok.yml : remplacer REPLACE-WITH-YOUR-DEV-DOMAIN par votre domaine fixe
```

## Étape 3 — Démarrer Weaviate + ngrok

```bash
docker-compose up -d weaviate
docker-compose --profile ngrok up -d ngrok
docker ps --filter name=vitiscan_ngrok --format "{{.Names}}: {{.Status}}"
```

## Étape 4 — Récupérer l'adresse gRPC attribuée (aléatoire)

Ouvrez l'interface web ngrok : [http://localhost:4040](http://localhost:4040) — les 2 endpoints
actifs y sont listés avec leurs adresses publiques. Notez l'adresse `tcp://X.tcp.ngrok.io:PORT` de
l'endpoint `weaviate-grpc`.

(Alternative sans navigateur : `docker logs vitiscan_ngrok` affiche aussi les adresses au démarrage.)

## Étape 5 — Vérifier les tunnels avant de toucher à Render

```bash
# REST via le tunnel HTTP (doit renvoyer 401 sans clé, 200 avec la clé de .env racine)
curl -s -o /dev/null -w "%{http_code}\n" https://xxxxx.ngrok-free.dev/v1/objects
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <WEAVIATE_API_KEY>" https://xxxxx.ngrok-free.dev/v1/objects
```

## Étape 6 — Configurer les variables d'environnement sur Render (service `vitiscan-rag-llm`)

Dans le dashboard Render, service `vitiscan-rag-llm` → Environment :

| Variable | Valeur |
|---|---|
| `WEAVIATE_URL` | laisser **vide** (mode "custom" prioritaire, cf. `weaviate_client.py`) |
| `WEAVIATE_CUSTOM_HTTP_HOST` | `xxxxx.ngrok-free.dev` (votre domaine fixe, sans `https://`) |
| `WEAVIATE_CUSTOM_HTTP_PORT` | `443` |
| `WEAVIATE_CUSTOM_HTTP_SECURE` | `true` |
| `WEAVIATE_CUSTOM_GRPC_HOST` | l'hôte noté à l'étape 4 (ex. `X.tcp.ngrok.io`) |
| `WEAVIATE_CUSTOM_GRPC_PORT` | le port noté à l'étape 4 |
| `WEAVIATE_CUSTOM_GRPC_SECURE` | `false` (tunnel TCP brut, pas de TLS applicatif côté Weaviate) |
| `WEAVIATE_API_KEY` | la même clé que `.env` racine |

Render redéploie automatiquement après un changement de variable d'environnement.

## Étape 7 — Vérifier de bout en bout

```bash
curl https://<votre-service-rag-llm>.onrender.com/health
curl -X POST https://<votre-service-rag-llm>.onrender.com/solutions \
  -H "Content-Type: application/json" \
  -d '{"cnn_label":"guignardia_bidwellii","mode":"conventionnel","severity":"forte","area_m2":5000}'
```

`treatment_plan` doit être non vide — preuve que Render (prod) atteint bien votre Weaviate local via
les 2 tunnels ngrok.

## Si le tunnel gRPC redémarre

```bash
docker-compose --profile ngrok restart ngrok
```
Rouvrez [http://localhost:4040](http://localhost:4040), notez la nouvelle adresse, mettez à jour
`WEAVIATE_CUSTOM_GRPC_HOST`/`WEAVIATE_CUSTOM_GRPC_PORT` sur Render. Le tunnel HTTP (REST), lui,
garde son adresse.

## Arrêter la simulation

```bash
docker-compose --profile ngrok stop ngrok
```
