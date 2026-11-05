import os
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_MODES = ("conventionnel", "bio")
DEFAULT_MODE = "conventionnel"

DEFAULT_SEASON = "inconnue"

MIN_RECOMMANDED_VOLUME_L_HA = 200
MAX_RECOMMANDED_VOLUME_L_HA = 400

# Fournisseur LLM (API compatible OpenAI, Groq par défaut). Les noms HF_* sont historiques.
HF_API_URL = os.getenv("HF_API_URL", "https://api.groq.com/openai/v1/chat/completions")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_MODEL_ID = os.getenv("HF_MODEL_ID", "qwen/qwen3.8-27b")
