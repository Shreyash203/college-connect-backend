import unittest
from unittest.mock import MagicMock, patch

from app.core.azure_storage import delete_marketplace_blob


class MarketplaceBlobDeletionSecurityTests(unittest.TestCase):
    connection_string = (
        "DefaultEndpointsProtocol=https;"
        "AccountName=testaccount;"
        "AccountKey=testkey;"
        "EndpointSuffix=core.windows.net"
    )
    image_id = "12345678-1234-1234-1234-123456789abc"

    def test_rejects_blobs_not_scoped_to_listing_owner(self):
        paths = (
            f"marketplace_images/user_8/{self.image_id}.jpg",
            f"marketplace_images/{self.image_id}.jpg",
        )

        with (
            patch("app.core.azure_storage.settings.AZURE_STORAGE_CONNECTION_STRING", self.connection_string),
            patch("app.core.azure_storage.settings.AZURE_STORAGE_CONTAINER_NAME", "images"),
            patch("app.core.azure_storage.BlobServiceClient.from_connection_string") as from_connection_string,
        ):
            for blob_path in paths:
                with self.subTest(blob_path=blob_path):
                    image_url = f"https://testaccount.blob.core.windows.net/images/{blob_path}"
                    self.assertFalse(delete_marketplace_blob(image_url, owner_user_id=7))

        from_connection_string.assert_not_called()

    def test_deletes_owner_scoped_blob_from_configured_container(self):
        blob_path = f"marketplace_images/user_7/{self.image_id}.jpg"
        image_url = f"https://testaccount.blob.core.windows.net/images/{blob_path}?sig=read-token"
        blob_service = MagicMock()
        container_client = blob_service.get_container_client.return_value

        with (
            patch("app.core.azure_storage.settings.AZURE_STORAGE_CONNECTION_STRING", self.connection_string),
            patch("app.core.azure_storage.settings.AZURE_STORAGE_CONTAINER_NAME", "images"),
            patch(
                "app.core.azure_storage.BlobServiceClient.from_connection_string",
                return_value=blob_service,
            ) as from_connection_string,
        ):
            self.assertTrue(delete_marketplace_blob(image_url, owner_user_id=7))

        from_connection_string.assert_called_once_with(self.connection_string)
        blob_service.get_container_client.assert_called_once_with("images")
        container_client.delete_blob.assert_called_once_with(blob_path)


if __name__ == "__main__":
    unittest.main()
