"""
Abstract storage interface for file operations.
Provides a consistent API for local filesystem and cloud storage (S3, GCS, Azure).
"""

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List
from pathlib import Path


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.

    Implementations should provide:
    - LocalStorage: For development and MVP
    - S3Storage: For AWS production deployment
    - GCSStorage: For Google Cloud (optional)
    - AzureStorage: For Azure (optional)
    """

    @abstractmethod
    async def upload(self, file: BinaryIO, path: str, metadata: Optional[dict] = None) -> str:
        """
        Upload a file to storage.

        Args:
            file: File-like object to upload
            path: Destination path (relative to storage root)
            metadata: Optional metadata to store with the file

        Returns:
            Full path or URL to the uploaded file

        Raises:
            StorageError: If upload fails
        """
        pass

    @abstractmethod
    async def download(self, path: str) -> bytes:
        """
        Download a file from storage.

        Args:
            path: Path to the file (relative to storage root)

        Returns:
            File contents as bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            StorageError: If download fails
        """
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            path: Path to the file (relative to storage root)

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            StorageError: If deletion fails
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            path: Path to the file (relative to storage root)

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    async def list_files(self, prefix: str = "") -> List[str]:
        """
        List all files with a given prefix.

        Args:
            prefix: Path prefix to filter files

        Returns:
            List of file paths matching the prefix

        Raises:
            StorageError: If listing fails
        """
        pass

    @abstractmethod
    async def get_metadata(self, path: str) -> dict:
        """
        Get metadata for a file.

        Args:
            path: Path to the file (relative to storage root)

        Returns:
            Dictionary with metadata (size, content_type, modified_time, etc.)

        Raises:
            FileNotFoundError: If file doesn't exist
            StorageError: If metadata retrieval fails
        """
        pass

    @abstractmethod
    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """
        Get a signed URL for accessing a file.

        Args:
            path: Path to the file (relative to storage root)
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Signed URL for accessing the file

        Raises:
            FileNotFoundError: If file doesn't exist
            StorageError: If URL generation fails
        """
        pass

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a path to use forward slashes and remove leading/trailing slashes.

        Args:
            path: Path to normalize

        Returns:
            Normalized path
        """
        # Convert backslashes to forward slashes
        path = path.replace("\\", "/")
        # Remove leading slash
        path = path.lstrip("/")
        # Remove trailing slash
        path = path.rstrip("/")
        return path


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


class FileNotFoundError(StorageError):
    """Exception raised when a file is not found in storage."""
    pass


class UploadError(StorageError):
    """Exception raised when file upload fails."""
    pass


class DownloadError(StorageError):
    """Exception raised when file download fails."""
    pass
