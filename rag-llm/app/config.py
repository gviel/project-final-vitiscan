import os
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_MODES = ("conventionnel", "bio")
DEFAULT_MODE = "conventionnel"

DEFAULT_SEASON = "inconnue"

MIN_RECOMMANDED_VOLUME_L_HA = 200
MAX_RECOMMANDED_VOLUME_L_HA = 400

# Hugging Face Inference (router)
HF_API_URL = os.getenv("HF_API_URL", "https://router.huggingface.co/v1/chat/completions")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_MODEL_ID = os.getenv("HF_MODEL_ID", "meta-llama/Llama-3.1-8B-Instruct")
