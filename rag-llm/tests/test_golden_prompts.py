"""
Tests "golden prompts" pour rag-llm (specs.md, Partie 1 étape 8).

Pilote la vraie API /solutions en HTTP (RAG_LLM_URL, défaut http://localhost:9000) : nécessite la
stack rag-llm + postgres (pgvector) démarrée et ingérée (cf. app/ingestion.py). Un HF_API_TOKEN
valide est nécessaire pour obtenir un vrai diagnostic LLM ; sans lui, l'appel LLM tombe sur un
texte de repli technique et les cas avec `expect_keywords` sont *skip* plutôt que *fail* (cf.
app/golden_prompts.py::GoldenPromptSkipped).

La logique d'évaluation (app/golden_prompts.py) est partagée avec
dags/tasks/rag_ingestion.py::run_golden_prompts_gate, qui rejoue les mêmes cas directement en
process (sans HTTP) comme porte de qualité avant promotion vers la branche Neon de prod.
"""
import os
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.golden_prompts import GoldenPromptSkipped, build_payload, evaluate_case, load_cases  # noqa: E402

RAG_LLM_URL = os.getenv("RAG_LLM_URL", "http://localhost:9000")
CASES = load_cases()


@pytest.fixture(scope="module")
def api_available():
    try:
        resp = requests.get(f"{RAG_LLM_URL}/health", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        pytest.skip(f"rag-llm indisponible sur {RAG_LLM_URL} ({e}) — stack non démarrée ?")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_prompt(api_available, case):
    resp = requests.post(f"{RAG_LLM_URL}/solutions", json=build_payload(case), timeout=60)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    try:
        evaluate_case(data, case)
    except GoldenPromptSkipped as exc:
        pytest.skip(str(exc))
