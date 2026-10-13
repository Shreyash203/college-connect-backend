import re
import logging
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobServiceClient
from app.core.config import settings

logger = logging.getLogger("uvicorn.error")

# Only blobs whose path matches this pattern may be deleted via the marketplace endpoint.
_MARKETPLACE_BLOB_RE = re.compile(
    r"^marketplace_images/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(jpg|jpeg|png|gif|webp|svg)$",
    re.IGNORECASE,
)

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


def delete_marketplace_blob(image_url: str) -> bool:
    """
    Deletes a marketplace image blob from Azure Blob Storage.

    Security guarantee: only blobs whose path starts with 'marketplace_images/'
    and whose filename is a UUID with an allowed image extension will be deleted.
    Any other URL — including profile_images/ or arbitrary external URLs — is
    rejected and returns False without touching storage.

    Returns True if deletion succeeded, False otherwise.
    Does not throw exceptions to avoid failing parent database transactions.
    """
    if not image_url or not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        return False

    try:
        parsed = urlparse(image_url)
        # Strip the leading slash and the container-name prefix so we get the blob path.
        path = unquote(parsed.path).lstrip('/')
        parts = path.split('/', 1)
        if len(parts) < 2:
            logger.warning(f"Marketplace blob deletion rejected — could not parse path from: {image_url}")
            return False

        container_name, blob_name = parts[0], parts[1]

        # Strip any SAS query string from blob_name before pattern matching.
        blob_name_clean = blob_name.split('?')[0]

        # Enforce that this blob lives under marketplace_images/ with a UUID filename.
        if not _MARKETPLACE_BLOB_RE.match(blob_name_clean):
            logger.warning(
                f"Marketplace blob deletion rejected — blob path '{blob_name_clean}' "
                f"does not match the expected marketplace_images/<uuid>.<ext> pattern."
            )
            return False

        blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service.get_container_client(container_name)
        container_client.delete_blob(blob_name_clean)
        logger.info(f"Deleted marketplace blob: {blob_name_clean} from {container_name}")
        return True
    except Exception as exc:
        logger.warning(f"Could not delete marketplace blob for URL {image_url}: {exc}")
        return False
