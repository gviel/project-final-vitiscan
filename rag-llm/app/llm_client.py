import time
from typing import Optional
import requests

from app.config import HF_API_URL, HF_API_TOKEN, HF_MODEL_ID


class LLMError(Exception):
    """Exception spécifique pour les erreurs liées aux appels LLM."""
    pass


def _build_headers() -> dict:
    if not HF_API_TOKEN:
        raise LLMError("HF_API_TOKEN manquant dans l'environnement (.env).")

    return {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json",
    }


def call_llm(
    prompt: str,
    max_new_tokens: int = 256,
    temperature: float = 0.4,
    top_p: float = 0.95,
    max_retries: int = 2,
    timeout: int = 30,
) -> str:
    """
    Appelle le modèle LLM via le router Hugging Face (API compatible OpenAI)
    et renvoie le texte généré.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt vide ou invalide transmis à call_llm().")

    headers = _build_headers()

    payload = {
        "model": HF_MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=timeout)

            if response.status_code != 200:
                raise LLMError(f"Erreur API HF (status {response.status_code}): {response.text}")

            data = response.json()

            # Format OpenAI-like: { "choices": [ { "message": { "content": "..." }, ... } ] }
            choices = data.get("choices", [])
            if not choices:
                raise LLMError("Réponse LLM sans 'choices'.")

            text = choices[0].get("message", {}).get("content", "")
            cleaned = text.strip()
            if not cleaned:
                raise LLMError("Réponse LLM vide ou uniquement composée d'espaces.")

            return cleaned

        except Exception as e:
            print(f"[LLM] Erreur tentative {attempt}/{max_retries}: {e}")
            last_error = e
            time.sleep(1)

    raise LLMError(f"Echec LLM après {max_retries} tentatives: {last_error}")
