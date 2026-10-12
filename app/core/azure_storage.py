import logging
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobServiceClient
from app.core.config import settings

logger = logging.getLogger("uvicorn.error")

def delete_blob_from_url(image_url: str) -> bool:
    """
    Safely deletes a blob from Azure Blob Storage given its image URL.
    Returns True if deletion succeeded, False otherwise.
    Does not throw exceptions to avoid failing parent database transactions.
    """
    if not image_url or not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        return False

    try:
        parsed = urlparse(image_url)
        path = unquote(parsed.path).lstrip('/')
        parts = path.split('/', 1)
        if len(parts) < 2:
            return False

        container_name, blob_name = parts[0], parts[1]
        
        blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service.get_container_client(container_name)
        container_client.delete_blob(blob_name)
        logger.info(f"Deleted blob: {blob_name} from {container_name}")
        return True
    except Exception as exc:
        logger.warning(f"Could not delete blob for URL {image_url}: {exc}")
        return False
