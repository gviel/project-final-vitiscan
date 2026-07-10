import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from app.rag_pipeline import generate_treatment_advice
from app.vector_store import get_embedder

logger = logging.getLogger(__name__)


class SolutionRequest(BaseModel):
    cnn_label: str = Field(..., description="Label de la maladie prédite par le CNN")
    mode: str = Field(..., description="Mode de conduite : 'bio' ou 'conventionnel'")
    severity: str = Field(..., description="Niveau de gravité : 'faible', 'moderee' ou 'forte'")
    area_m2: float = Field(..., ge=0, description="Surface concernée en m²")
    date_iso: Optional[str] = Field(None, description="Date ISO (YYYY-MM-DD) utilisée pour estimer la saison")
    location: Optional[str] = Field(None, description="Localisation texte (facultatif, pour info)")


class SolutionResponse(BaseModel):
    data: Dict[str, Any]


def _load_embedder_safe() -> None:
    try:
        get_embedder()
        logger.info("Modèle d'embedding chargé au démarrage")
    except Exception:
        logger.exception("Erreur au chargement du modèle d'embedding au démarrage")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chargement en arrière-plan (thread pool), pas bloquant : sinon /health ne répond pas tant
    # que sentence-transformers n'a pas fini de charger. Même pattern que api/app.py. Objectif :
    # que le pic mémoire torch ait lieu au démarrage (logs de déploiement Render) plutôt qu'en
    # pleine requête /solutions - où un OOM tuait tout le conteneur (constaté en prod, cf.
    # docs/refactoring.md).
    asyncio.get_event_loop().run_in_executor(None, _load_embedder_safe)
    yield


app = FastAPI(
    title="VitiScan Solutions API",
    description="API de recommandations de traitements basée sur un pipeline RAG.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/solutions", response_model=SolutionResponse)
def get_solutions(
    request: SolutionRequest,
    debug: bool = Query(False, description="Inclure aussi le raw_llm_output pour le debug"),
):
    """Prend une prédiction de maladie + contexte et renvoie un plan de traitement structuré."""
    payload = request.model_dump()
    advice = generate_treatment_advice(payload)

    if not debug:
        advice.pop("raw_llm_output", None)

    return {"data": advice}
