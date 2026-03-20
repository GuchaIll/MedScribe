"""
Local filesystem storage implementation.
Used for MVP development and testing.
"""

import os
import aiofiles
import aiofiles.os
from pathlib import Path
from typing import BinaryIO, Optional, List
from datetime import datetime

from app.storage.base import (
    StorageBackend,
    StorageError,
    FileNotFoundError as StorageFileNotFoundError,
    UploadError,
    DownloadError
)


class LocalStorage(StorageBackend):
    """
    Local filesystem storage implementation.

    Stores files in a base directory on the local filesystem.
    Suitable for development and MVP deployment.
    """

    def __init__(self, base_dir: str = "storage"):
        """
        Initialize local storage.

        Args:
            base_dir: Base directory for file storage (relative or absolute)
        """
        self.base_dir = Path(base_dir)
        # Create base directory if it doesn't exist
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(self, file: BinaryIO, path: str, metadata: Optional[dict] = None) -> str:
        """
        Upload a file to local storage.

        Args:
            file: File-like object or bytes to upload
            path: Destination path (relative to base_dir)
            metadata: Optional metadata (stored in companion .meta file)

        Returns:
            Full path to the uploaded file

        Raises:
            UploadError: If upload fails
        """
        try:
            # Normalize path
            path = self._normalize_path(path)
            full_path = self.base_dir / path

            # Create parent directories
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            async with aiofiles.open(full_path, 'wb') as f:
                if hasattr(file, 'read'):
                    # File-like object
                    content = await file.read() if hasattr(file.read, '__call__') else file.read()
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    await f.write(content)
                else:
                    # Bytes
                    await f.write(file)

            # Store metadata if provided
            if metadata:
                await self._write_metadata(full_path, metadata)

            return str(full_path)

        except Exception as e:
            raise UploadError(f"Failed to upload file to {path}: {str(e)}")

    async def download(self, path: str) -> bytes:
        """
        Download a file from local storage.

        Args:
            path: Path to the file (relative to base_dir)

        Returns:
            File contents as bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            DownloadError: If download fails
        """
        try:
            # Normalize path
            path = self._normalize_path(path)
            full_path = self.base_dir / path

            if not full_path.exists():
                raise StorageFileNotFoundError(f"File not found: {path}")

            async with aiofiles.open(full_path, 'rb') as f:
                return await f.read()

        except StorageFileNotFoundError:
            raise
        except Exception as e:
            raise DownloadError(f"Failed to download file from {path}: {str(e)}")

    async def delete(self, path: str) -> bool:
        """
        Delete a file from local storage.

        Args:
            path: Path to the file (relative to base_dir)

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            StorageError: If deletion fails
        """
        try:
            # Normalize path
            path = self._normalize_path(path)
            full_path = self.base_dir / path

            if not full_path.exists():
                return False

            # Delete file
            await aiofiles.os.remove(full_path)

            # Delete metadata file if exists
            meta_path = self._get_metadata_path(full_path)
            if meta_path.exists():
                await aiofiles.os.remove(meta_path)

            return True

        except Exception as e:
            raise StorageError(f"Failed to delete file {path}: {str(e)}")

    async def exists(self, path: str) -> bool:
        """
        Check if a file exists in local storage.

        Args:
            path: Path to the file (relative to base_dir)

        Returns:
            True if file exists, False otherwise
        """
        path = self._normalize_path(path)
        full_path = self.base_dir / path
        return full_path.exists() and full_path.is_file()

    async def list_files(self, prefix: str = "") -> List[str]:
        """
        List all files with a given prefix.

        Args:
            prefix: Path prefix to filter files

        Returns:
            List of file paths (relative to base_dir)
        """
        prefix = self._normalize_path(prefix) if prefix else ""
        search_dir = self.base_dir / prefix if prefix else self.base_dir

        if not search_dir.exists():
            return []

        files = []
        for file_path in search_dir.rglob("*"):
            if file_path.is_file() and not file_path.name.endswith('.meta'):
                # Get relative path from base_dir
                relative_path = file_path.relative_to(self.base_dir)
                files.append(str(relative_path))

        return sorted(files)

    async def get_metadata(self, path: str) -> dict:
        """
        Get metadata for a file.

        Args:
            path: Path to the file (relative to base_dir)

        Returns:
            Dictionary with metadata (size, modified_time, etc.)

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        path = self._normalize_path(path)
        full_path = self.base_dir / path

        if not full_path.exists():
            raise StorageFileNotFoundError(f"File not found: {path}")

        # Get file stats
        stat = full_path.stat()

        metadata = {
            "size": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "content_type": self._guess_content_type(full_path),
        }

        # Load custom metadata if exists
        custom_meta = await self._read_metadata(full_path)
        if custom_meta:
            metadata.update(custom_meta)

        return metadata

    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """
        Get a file:// URL for accessing a file.

        Args:
            path: Path to the file (relative to base_dir)
            expires_in: Not used for local storage (included for interface compatibility)

        Returns:
            file:// URL to the file

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        path = self._normalize_path(path)
        full_path = self.base_dir / path

        if not full_path.exists():
            raise StorageFileNotFoundError(f"File not found: {path}")

        # Return file:// URL
        return full_path.as_uri()

    # Helper methods

    def _get_metadata_path(self, file_path: Path) -> Path:
        """Get path for metadata file."""
        return file_path.parent / f"{file_path.name}.meta"

    async def _write_metadata(self, file_path: Path, metadata: dict):
        """Write metadata to companion .meta file."""
        import json
        meta_path = self._get_metadata_path(file_path)

        async with aiofiles.open(meta_path, 'w') as f:
            await f.write(json.dumps(metadata, indent=2))

    async def _read_metadata(self, file_path: Path) -> Optional[dict]:
        """Read metadata from companion .meta file."""
        import json
        meta_path = self._get_metadata_path(file_path)

        if not meta_path.exists():
            return None

        try:
            async with aiofiles.open(meta_path, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except Exception:
            return None

    def _guess_content_type(self, file_path: Path) -> str:
        """Guess content type from file extension."""
        import mimetypes

        content_type, _ = mimetypes.guess_type(str(file_path))
        return content_type or "application/octet-stream"
