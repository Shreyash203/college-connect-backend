import re
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobServiceClient
from app.core.config import settings

logger = logging.getLogger("uvicorn.error")


def get_azure_storage_account_name() -> Optional[str]:
    """Extracts the AccountName from the configured Azure storage connection string."""
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    if not conn_str:
        return None
    for part in conn_str.split(';'):
        if part.strip().startswith('AccountName='):
            return part.strip().split('=', 1)[1].strip()
    return None


def verify_azure_host_and_container(image_url: str) -> Optional[Tuple[str, str]]:
    """
    Validates that image_url belongs to the configured Azure storage account
    and the configured container.
    Returns (configured_container, clean_blob_name) if valid, or None if validation fails.

    Security guarantees:
    - Rejects non-HTTPS schemes.
    - Strictly checks parsed host against <configured_account>.blob.core.windows.net.
    - Strictly matches the URL container against settings.AZURE_STORAGE_CONTAINER_NAME.
    - Never trusts arbitrary container names or external storage hosts.
    """
    if not image_url or not settings.AZURE_STORAGE_CONNECTION_STRING:
        return None

    configured_container = getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None)
    if not configured_container:
        return None

    account_name = get_azure_storage_account_name()
    if not account_name:
        return None

    try:
        parsed = urlparse(image_url)
        if (parsed.scheme or "").lower() != "https":
            logger.warning(f"Blob validation rejected — non-HTTPS URL: {image_url}")
            return None

        expected_host = f"{account_name.lower()}.blob.core.windows.net"
        if (parsed.hostname or "").lower() != expected_host:
            logger.warning(
                f"Blob validation rejected — host '{(parsed.hostname or '').lower()}' "
                f"does not match configured storage account '{expected_host}'"
            )
            return None

        path = unquote(parsed.path).lstrip('/')
        parts = path.split('/', 1)
        if len(parts) < 2:
            logger.warning(f"Blob validation rejected — missing blob path in: {image_url}")
            return None

        url_container, blob_name = parts[0], parts[1]
        if url_container != configured_container:
            logger.warning(
                f"Blob validation rejected — URL container '{url_container}' "
                f"does not match configured container '{configured_container}'"
            )
            return None

        blob_name_clean = blob_name.split('?')[0]
        return configured_container, blob_name_clean
    except Exception as exc:
        logger.warning(f"Failed to parse or validate blob URL {image_url}: {exc}")
        return None


def delete_blob_from_url(image_url: str) -> bool:
    """
    Safely deletes a blob from Azure Blob Storage given its image URL.
    Verifies that the URL host matches the configured storage account
    and strictly uses the configured container name.
    Returns True if deletion succeeded, False otherwise.
    Does not throw exceptions to avoid failing parent database transactions.
    """
    verification = verify_azure_host_and_container(image_url)
    if not verification:
        return False

    configured_container, blob_name_clean = verification

    try:
        blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service.get_container_client(configured_container)
        container_client.delete_blob(blob_name_clean)
        logger.info(f"Deleted blob: {blob_name_clean} from {configured_container}")
        return True
    except Exception as exc:
        logger.warning(f"Could not delete blob for URL {image_url}: {exc}")
        return False


def delete_marketplace_blob(image_url: str, owner_user_id: int) -> bool:
    """
    Deletes a marketplace image blob from Azure Blob Storage.

    Security guarantees:
    1. Binds deletion strictly to the configured Azure storage host and container.
       Never trusts the container name parsed from the supplied URL.
    2. Proves image ownership by enforcing that the blob lives under
       'marketplace_images/user_{owner_user_id}/<uuid>.<ext>'.
       Legacy unscoped paths are rejected because their ownership cannot be proven.
    3. Rejects deletion if path does not match expected patterns.
    """
    verification = verify_azure_host_and_container(image_url)
    if not verification:
        return False

    configured_container, blob_name_clean = verification

    user_scoped_pattern = (
        rf"^marketplace_images/user_{owner_user_id}/"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        r"\.(jpg|jpeg|png|gif|webp|svg)$"
    )
    if not re.match(user_scoped_pattern, blob_name_clean, re.IGNORECASE):
        logger.warning(
            f"Marketplace blob deletion rejected — blob '{blob_name_clean}' does not match "
            f"ownership for user {owner_user_id}."
        )
        return False

    try:
        blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service.get_container_client(configured_container)
        container_client.delete_blob(blob_name_clean)
        logger.info(f"Deleted marketplace blob: {blob_name_clean} from {configured_container}")
        return True
    except Exception as exc:
        logger.warning(f"Could not delete marketplace blob for URL {image_url}: {exc}")
        return False
