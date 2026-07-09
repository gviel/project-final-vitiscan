# JEDHA AIA Bloc 4 - Final Project : Vitiscan

Project de détection et reconnaissance de maladie de la vigne par photo des feuilles de vigne et modèle CNN + préconisation d'un plan de traitement de la maladie de la vigne avec un RAG-LLM

---

## Contexte 

Ce projet est un projet final qui vaut pour 2 formations :
    - la CDSD où l'objectif était de mener un projet IA de bout en bout
    - l'AIA où l'on demande un peu plus d'industrialisation comme pour le projet "Fraud Detection" dans `/data/JEDHA-DL-36/Project-03-Fraud_Detection` et où l'objectif est de présenter un pipeline en prod plus complet


- le projet CDSD a été réalisé et fonctionnait mais réparti dans plusieurs répertoires et dépots suivants
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/VitiScan_architecture.drawio :
        - un schéma de l'architecture pour la CDSD
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/Project_10_VitiScan_model :
        - Partie entrainement du modèle et notebook exploratoire permettant d'entrainer un modèle et le pousser sur MLFlow : notebooks/CNN_model_FT.ipynb étant le notebook de référence
        - le répertoire scripts était une tentative d'industrialiser le contenu du notebook pour pouvoir exécuter de façon plus automatisée l'entrainement du modèle
        - le dataset a prendre en compte est data-inrae (car data-kaggle n'est pas un bon dataset)
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/Project_10_VitiScan_MLFlow3 :
        - un serveur MLFlow 3.7.0
        - déjà déployé sur Hugging Face et fonctionne bien(donc rien à faire et modifier pour ce composant)
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/présentation :
        - contient la présentation du projet pour la formation CDSD
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/Project_10_VitiScan_WebUI :
        - contient l'UI Streamlit pour l'utilisateur permettant de soumettre une photo, avoir un prédiction, puis interroger un RAG-LLM pour avoir des recommandations sur les traitements à faire sur la vigne
        - déployé sous Hugging Face
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/vitiscan-diagno-api :
        - API de prédiction du modèle CNN (va chercher le modèle dans MLFlow) et qui renvoie un diagnostic : quel maladie de la vigne + probabilité
        - déployée sur Hugging Face
    - /home/gviel/data/JEDHA/Project_10_Vitiscan/vitiscan-rag-llm :
        - API RAG-LLM permettant de renvoyer un plan de traitement de la vigne selon un diagnostic donné + scripts permettant de chunk les documents et les charger dans weaviate
            - /home/gviel/data/JEDHA/Project_10_Vitiscan/vitiscan-rag-llm/data/knowledge : contient les documents de base \*.md pour le RAG (c'est très light!)
            - /home/gviel/data/JEDHA/Project_10_Vitiscan/vitiscan-rag-llm/app : contient l'API
        - base weaviate déployée chez weaviate en plan gratuit

- pour le projet AIA, seule une présentation et des schémas ont été faits, indiquant l'architecture cible très ambitieuse
  on ajoutera que quelques éléments par rapport à la CDSD et nous n'irons pas jusqu'à la cible proposée dans la présentation
    - /home/gviel/data/JEDHA-DL-36/Project_04_Final/LEAD_VITISCAN.odp
    - /home/gviel/data/JEDHA-DL-36/Project_04_Final/Vitiscan lead.svg
    - /home/gviel/data/JEDHA-DL-36/Project_04_Final/Vitiscan lead-2.pdf

---

## TODO

### Objectifs

#### 1. Refactorer le code CDSD pour arriver à

- le refaire fonctionner
- mettre tous les projets dans un seul dépot (ce répertoire) avec un déploiement un peu différent et plus simple qu'avec Hugging Face - s'inspirer de l'organisation du code qui a été faite pour le projet Fraud Detection
    - par composant : un répertoire (api/, airflow/, etc.), ses propres fichiers .env, son requirements.txt etc.
- pour les env python on utilisera : 
    - conda pour les notebooks
    - venv + requirements pour le reste
    - on conservera les versions pour rester le plus possible compatible avec mlflow==3.7.0 et/ou airflow==3.2.2
- Partie entrainement du modèle et Notebook :
    - le notebook a permis l'exploration mais pour l'industrialisation mais il faut essayer de faire comme ce qui a été tenté dans sripts/ c'est à dire pouvoir faire l'entrainement
      mais sous la forme d'un script train.py (+ autres scripts ?) paramétrable (ex: type de modèle, nombre d'epochs, etc.) et qui peuvent être exécutés localement ou intégrés dans 
     un process airflow (cf. méthode utilisée dans projet Fraud Detection)
    - la partie scripts/ a été faire par un developpeur débutant avec un LLM mais code inutilement complexe => le rendre compact et facile à maintenir tout en restant fonctionnel et plus paramétrable qu'un notebook
- API prédiction CNN :
    - doit pouvoir être testée en local sous Docker et déployée sous Render (comme le projet Fraud Detection)
- interface UI Streamlit -> déploiement en local sous Docker ou sous Streamlit community
- API RAG-LLM + scripts d'ingestion des données : plusieurs problèmes
    - la base de données weaviate en plan gratuit est régulièrement détruite et après chargement elle est indisponible plusieurs heures
      -> il faudrait trouver une autre solution de déploiement pour la prod => ex: weaviate en docker local + ngrok ? une autre bdd vectorielle?
      dans un premier temps sous image docker pour les tests
    - le code a été fait par un débutant + LLM : code éclaté, parfois complexe pour rien =>  il faut le rendre plus propre, plus compact et simple à maintenir sans retirer les fonctionnalités existantes
    - ne plus utiliser l'env conda -> pour cette partie
    - les documents et l'ingestion des données ne devraient pas être là mais dans un process airflow -> voir comment préparer un serveur airflow 3.2.2 pour ce projet avec au moins ce DAG simple
        - DAG d'ingestion des données pour le RAG : si on a des nouveaux docs dans S3 par rapport à la dernière execution, lancer l'ingestion en test puis si OK en prod
          - bucket dédié `s3-vitiscan-data` (plus le bucket MLflow, réutilisé par erreur au départ) : `data-inrae/` (dataset + disease-inrae.json), `data-kaggle/` (disease-kaggle.json), `knowledge/current/` (docs utilisés par le RAG en prod) et `knowledge/new/` (dépôt de nouveaux docs, pas encore de logique de promotion automatique vers `current/`)
    - je ne sais pas ce qu'a utilisé le développeur comme modèle: un modèle Hugging Face gratuit? à déterminer en analysant le code
    - quels tests en place? il faudrait un test de type "golden prompts" dans un fichier yaml avec jeux de prompts / réponses attendues
- créer une stack docker-compose locale permettant de tout tester de bout en bout rapidement (sauf MLFlow qui reste déployé sur HF)
    - (mineur, pas urgent) l'environnement de dev de référence n'a que `docker-compose` v1 (legacy, paquet Ubuntu `docker-compose`/`python3-compose`) car Docker a été installé via les paquets Ubuntu et non le dépôt officiel Docker Inc. (`download.docker.com`) - pour avoir le plugin `docker compose` v2, ajouter ce dépôt puis `apt install docker-compose-plugin` (peut coexister avec `docker-compose` v1)
- pouvoir déployer en prod sur Render et Streamlit (avoir une doc qui indiquer les étapes à suivre pour le premier déploiement ou l'update)


#### 2.Faire évoluer pour l'AIA

- il faut ensuite ajouter les features suivantes pour arriver à l'objectif comme indiqué dans le schéma d'architecture de l'AIA 
    - une autre interface Streamlit permettant de trier, éviter les doublons et labelliser toutes les nouvelles photos de vigne que les utilisateurs auront envoyés via l'UI Streamlit
        - l'UI streamlit pour le viticulteur doit collecter l'image, la position GPS si elle est fournie, le timestamp de l'image + le résultat de la prédiction de l'API de prédiction de maladié (% taux de confiance) ainsi que sa version de modèle, et sauver l'image dans un bucket S3 mais aussi les métadata citées dans une bdd pgsql Neon
	- l'UI de photo labeling (streamlit + bdd pgsql Neon + S3) doit permettre de labelliser les nouvelles photos et permettre de calculer l'écart avec la prod et la prédiction fournie par le modèle en prod => possibilité de calculer un drift
    - ajouter airflow :
        - détecter si nouvelles images labellisées -> les ajouter dans le dataset et déclencher un nouvel entrainement
        - process qui détecte si nouveau documents (ex: documents scientifiques en MD ou PDF sur le traitement des maladies des vignes) dans bucket S3
            - chunk les nouveaux docs et les injecte dans la vector db de type weaviate ou similaire de test
            - fait des tests pour vérifier que le RAG-LLM répond correctement avec un jeu de "golden prompts" (ex: dans un fichier yaml avec les maladies et les réponses attendues)
            - si les tests sont OK injecter dans la vector db de prod
    - 
    
#### NB Important :
    - il me reste très peu de temps pour restructurer ce projet
    - se contenter dans un premier temps à faire remarcher la CDSD en iso-fonctionnel
    - l'entrainement d'un modèle prends ~15 à 20 min voire plus -> il faudra donc
        - éviter de lancer des executions trop longues de la partie entrainement pour les tests
          pour cela on diminuera le nombre d'epochs
          ou on essayera de mettre une condition stop qui arrive plus rapidement
          ou de courcircuiter le modèle et utiliser un modèle valide existant dans le MLFlow déployé


