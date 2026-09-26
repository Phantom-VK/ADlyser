"""Content-hash disk cache. Expensive steps are never paid for twice."""

import hashlib
import json
from pathlib import Path
from typing import Any


def content_key(*parts: Any) -> str:
    """Hash arbitrary JSON-serialisable parts into a stable cache key.

    :param parts: values that fully determine the result.
    :return: a hex sha256 digest.
    """
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class DiskCache:
    """JSON files under ``root/<namespace>/<key>.json``."""

    def __init__(self, root: Path) -> None:
        """Create a cache rooted at ``root``.

        :param root: directory to store entries in (created lazily).
        """
        self.root = root

    def _path(self, namespace: str, key: str) -> Path:
        """Return the file path for an entry."""
        return self.root / namespace / f"{key}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        """Read an entry.

        :param namespace: logical group, e.g. a prompt name.
        :param key: content hash.
        :return: the stored value, or None on a miss or corrupt file.
        """
        path = self._path(namespace, key)
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Write an entry atomically.

        :param namespace: logical group.
        :param key: content hash.
        :param value: JSON-serialisable value.
        """
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        tmp.replace(path)
