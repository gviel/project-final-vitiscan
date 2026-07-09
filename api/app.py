import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager

import mlflow
import mlflow.pytorch
import torch
import torchvision.transforms as transforms
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from schemas import DiseasePrediction, DiseasesResponse, HealthResponse, PredictionResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

DEVICE = "cpu"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "https://gviel-mlflow37.hf.space")
# Logged Model id (MLflow 3.x), pas un run_id : cf. mlflow.get_logged_model()
MLFLOW_MODEL_ID = os.getenv("MLFLOW_MODEL_ID", "m-46e598be60f940849247fc01cf53dc3c")

DISEASE_FALLBACK = {"N/A": "N/A"}

TRANSFORM = transforms.Compose(
    [
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ]
)

MODEL = None
MODEL_NAME = None
DATASET_NAME = None
DISEASES = DISEASE_FALLBACK


def _load_diseases(artifact_location: str) -> dict:
    """Charge disease.json déposé à côté des artifacts du modèle (pas un artifact mlflow enregistré)."""
    disease_uri = f"{artifact_location}/extra_files/disease.json"
    try:
        local_path = mlflow.artifacts.download_artifacts(artifact_uri=disease_uri)
        with open(local_path, encoding="utf-8") as f:
            diseases = json.load(f)
        logger.info(f"Diseases loaded from {disease_uri}")
        return diseases
    except Exception as e:
        logger.warning(f"Impossible de charger disease.json depuis {disease_uri}: {e}")
        return DISEASE_FALLBACK


def _load_model() -> None:
    """Charge le modèle CNN et ses métadonnées depuis MLflow (Model Registry / Logged Model)."""
    global MODEL, MODEL_NAME, DATASET_NAME, DISEASES

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    logged_model = mlflow.get_logged_model(MLFLOW_MODEL_ID)
    MODEL_NAME = logged_model.name
    logger.info(f"Loading model {MODEL_NAME} ({MLFLOW_MODEL_ID}) from {MLFLOW_TRACKING_URI}")

    MODEL = mlflow.pytorch.load_model(f"models:/{MLFLOW_MODEL_ID}", map_location=DEVICE)
    MODEL.eval()

    run_params = mlflow.get_run(logged_model.source_run_id).data.params
    DATASET_NAME = run_params.get("dataset_name", "unknown")

    DISEASES = _load_diseases(logged_model.artifact_location)
    logger.info(f"Model {MODEL_NAME} loaded, dataset={DATASET_NAME}, {len(DISEASES)} diseases")


def _predict(input_tensor: torch.Tensor) -> list[tuple[str, float]]:
    with torch.no_grad():
        output = MODEL(input_tensor)
        probs = torch.nn.functional.softmax(output, dim=1)[0]
        disease_ids = list(DISEASES.keys())
        predictions = [(disease_ids[i], float(probs[i])) for i in range(len(disease_ids))]
        predictions.sort(key=lambda x: x[1], reverse=True)
    return predictions


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _load_model()
    except Exception:
        logger.exception("Erreur au chargement du modèle au démarrage de l'API")
    yield


app = FastAPI(lifespan=lifespan, title="VitiScan Diagno API")


@app.get("/")
def root():
    return {"message": "Vitiscan Diagno API is running"}


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok" if MODEL is not None else "model_not_loaded", model_loaded=MODEL is not None, model_version=MODEL_NAME)


@app.get("/diseases", response_model=DiseasesResponse)
def diseases():
    return DiseasesResponse(diseases=DISEASES, dataset_name=DATASET_NAME or "unknown")


@app.post("/diagno", response_model=PredictionResponse)
async def diagno(file: UploadFile = File(...)):
    if MODEL is None:
        return JSONResponse(status_code=503, content={"message": "Modèle non chargé"})
    if file is None:
        return JSONResponse(status_code=400, content={"message": "Aucun fichier reçu"})

    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
        tmp_file.write(contents)
        tmp_file_path = tmp_file.name

    try:
        image = Image.open(tmp_file_path).convert("RGB")
        tensor = TRANSFORM(image).unsqueeze(0).to(DEVICE)
        raw_predictions = _predict(tensor)
        predictions = [DiseasePrediction(disease=d, confidence=c) for d, c in raw_predictions]
    except Exception:
        logger.exception("Erreur pendant la prédiction")
        return JSONResponse(status_code=500, content={"message": "Predict error in API diagno"})
    finally:
        os.unlink(tmp_file_path)

    return PredictionResponse(predictions=predictions, model_version=MODEL_NAME)


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("API_SERVER_PORT", 4000)), reload=True)
