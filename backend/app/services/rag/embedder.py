import logging

from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger("app.services.rag.embedder")

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        from app.core.config import MODELS_DIR

        local_path = MODELS_DIR / "BAAI" / "bge-small-en-v1.5"
        if local_path.exists() and local_path.is_dir():
            model_to_load = str(local_path)
            logger.info(f"Loading local embedding model from: {model_to_load}...")
        else:
            model_to_load = settings.EMBEDDING_MODEL_PATH
            logger.info(f"Loading embedding model: {model_to_load}...")

        device = settings.torch_device
        logger.info(f"Using device for embeddings: {device}")
        _model = SentenceTransformer(model_to_load, device=device)
    return _model


def embed_text(text: str) -> list[float]:
    model = get_embedder()
    embedding = model.encode(text)
    # Ensure it returns a list of floats
    if hasattr(embedding, "tolist"):
        return embedding.tolist()
    return list(embedding)
