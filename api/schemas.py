from pydantic import BaseModel
from typing import List


class DiseasesResponse(BaseModel):
    diseases: dict
    dataset_name: str


class DiseasePrediction(BaseModel):
    disease: str
    confidence: float


class PredictionResponse(BaseModel):
    predictions: List[DiseasePrediction]
    model_version: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_version: str | None = None
