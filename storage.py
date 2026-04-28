"""
storage.py - Azure Blob Storage backend for uploaded documents.
Preserves the original storage interface: get_storage(), save_pending(),
finalize(), cleanup_stale_pending(), plus get_download_url() for SAS links.
"""

import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas,
)

logger = logging.getLogger(__name__)

PENDING_PREFIX = "_pending"

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


class AzureBlobStorage:
    """Azure Blob Storage backend for uploaded documents."""

    def __init__(self, connection_string=None, container_name=None):
        conn_str = connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not set")

        self.container_name = container_name or os.environ.get("BLOB_CONTAINER_NAME", "uploads")
        self._service_client = BlobServiceClient.from_connection_string(conn_str)
        self._container_client = self._service_client.get_container_client(self.container_name)

        try:
            self._container_client.create_container()
            logger.info(f"Created blob container: {self.container_name}")
        except Exception:
            # Container already exists
            pass

    @staticmethod
    def _content_type_for(ext):
        return CONTENT_TYPES.get(ext.lower(), "application/octet-stream")

    def _delete_by_prefix(self, prefix):
        for blob in self._container_client.list_blobs(name_starts_with=prefix):
            self._container_client.delete_blob(blob.name)

    def _upload_file(self, source_path, blob_name, ext):
        with open(source_path, "rb") as f:
            self._container_client.upload_blob(
                name=blob_name,
                data=f,
                overwrite=True,
                content_settings=ContentSettings(content_type=self._content_type_for(ext)),
            )

    def save_pending(self, session_id, doc_type, source_path):
        """
        Upload an incoming file to pending storage in the blob container.
        Returns the blob key. Overwrites any existing file for the same
        session_id + doc_type (any extension).
        """
        ext = Path(source_path).suffix.lower() or ".bin"

        # Remove any prior pending blob for this doc_type (different extensions)
        self._delete_by_prefix(f"{PENDING_PREFIX}/{session_id}/{doc_type}.")

        blob_name = f"{PENDING_PREFIX}/{session_id}/{doc_type}{ext}"
        self._upload_file(source_path, blob_name, ext)
        logger.info(f"Saved pending blob: {blob_name}")
        return blob_name

    def finalize(self, session_id, course_slug, submission_id):
        """
        Move blobs from pending to permanent storage.
        Returns a dict of {doc_type: blob_key}.
        """
        pending_prefix = f"{PENDING_PREFIX}/{session_id}/"
        file_keys = {}
        moved = []

        for blob in self._container_client.list_blobs(name_starts_with=pending_prefix):
            filename = blob.name[len(pending_prefix):]
            doc_type = Path(filename).stem
            new_key = f"{course_slug}/{submission_id}/{filename}"

            source_blob = self._container_client.get_blob_client(blob.name)
            dest_blob = self._container_client.get_blob_client(new_key)
            dest_blob.start_copy_from_url(source_blob.url)

            moved.append(blob.name)
            file_keys[doc_type] = new_key
            logger.info(f"Finalized blob: {new_key}")

        for old_name in moved:
            self._container_client.delete_blob(old_name)

        if not file_keys:
            logger.warning(f"No pending blobs found for session {session_id}")

        return file_keys

    def get_path(self, key):
        """
        Download a blob to a temporary local file and return its path.
        Provided for backward compatibility with callers that use Flask's
        send_file. For new code, prefer get_download_url() and redirect.
        """
        if not key:
            return None

        blob_client = self._container_client.get_blob_client(key)
        try:
            stream = blob_client.download_blob()
        except Exception as e:
            logger.error(f"Blob not found: {key} ({e})")
            return None

        suffix = Path(key).suffix or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            stream.readinto(tmp)
        finally:
            tmp.close()
        return tmp.name

    def get_download_url(self, key, expiry_hours=1):
        """
        Generate a time-limited read-only SAS URL for a blob key.
        Returns None if key is empty.
        """
        if not key:
            return None

        account_name = self._service_client.account_name
        account_key = self._service_client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.container_name,
            blob_name=key,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )
        return f"{self._service_client.url}{self.container_name}/{key}?{sas_token}"

    def delete(self, key):
        """Delete a single blob by key."""
        if not key:
            return False
        try:
            self._container_client.delete_blob(key)
            logger.info(f"Deleted blob: {key}")
            return True
        except Exception as e:
            logger.error(f"Error deleting blob {key}: {e}")
            return False

    def replace_file(self, course_slug, submission_id, doc_type, source_path):
        """
        Replace a document blob for a submission (used during re-upload).
        Deletes any existing blob for the doc_type and uploads the new one.
        Returns the new blob key.
        """
        ext = Path(source_path).suffix.lower() or ".bin"
        self._delete_by_prefix(f"{course_slug}/{submission_id}/{doc_type}.")

        blob_name = f"{course_slug}/{submission_id}/{doc_type}{ext}"
        self._upload_file(source_path, blob_name, ext)
        logger.info(f"Replaced blob: {blob_name}")
        return blob_name

    def delete_submission_files(self, course_slug, submission_id):
        """Delete all blobs for a submission."""
        prefix = f"{course_slug}/{submission_id}/"
        count = 0
        for blob in self._container_client.list_blobs(name_starts_with=prefix):
            self._container_client.delete_blob(blob.name)
            count += 1
        if count:
            logger.info(f"Deleted {count} blob(s) for {course_slug}/{submission_id}")

    def cleanup_stale_pending(self, max_age_hours=24):
        """Remove pending blobs older than max_age_hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        prefix = f"{PENDING_PREFIX}/"
        removed = 0

        for blob in self._container_client.list_blobs(name_starts_with=prefix):
            last_modified = blob.last_modified
            if last_modified is None:
                continue
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            if last_modified < cutoff:
                try:
                    self._container_client.delete_blob(blob.name)
                    removed += 1
                except Exception as e:
                    logger.error(f"Error cleaning up {blob.name}: {e}")

        if removed:
            logger.info(f"Cleaned up {removed} stale pending blob(s)")


# Singleton instance
_storage = None


def get_storage():
    """Get the storage instance (creates on first call)."""
    global _storage
    if _storage is None:
        _storage = AzureBlobStorage()
    return _storage
