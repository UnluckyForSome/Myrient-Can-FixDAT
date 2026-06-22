"""
minerva_qbit — qBittorrent Web API v2 client
============================================

Pure-Python client for the qBittorrent Web UI.  No Qt, no GUI deps — safe
to import from CLI scripts (``poc_minerva.py``) and GUI frontends alike.

The class is extracted from ``minerva_gui.py`` so the batch-download logic
can be shared between the GUI worker thread and the POC CLI.

Typical usage::

    client = QBittorrentClient("http://localhost:8080", "admin", "adminadmin")
    client.login()

    h = client.add_torrent_paused("/path/to/file.torrent", "/save/dir")
    files = client.get_files(h)
    client.set_file_priority(h, [i for i, f in enumerate(files) if skip], 0)
    client.resume(h)

    # Poll for completion
    while True:
        info = client.get_torrent_info(h)
        if info and info["progress"] >= 1.0:
            break
        time.sleep(1)
"""
from __future__ import annotations

from pathlib import Path

import requests


# ── Typed exceptions ───────────────────────────────────────────────────────

class QBittorrentError(RuntimeError):
    """Base exception for qBittorrent client errors."""


class QBittorrentConnectionError(QBittorrentError):
    """Raised when the client cannot connect to the qBittorrent Web UI."""


class QBittorrentApiError(QBittorrentError):
    """Raised when the qBittorrent API returns an error response."""


__all__ = [
    "QBittorrentClient",
    "QBittorrentError",
    "QBittorrentConnectionError",
    "QBittorrentApiError",
]


# ── Client ─────────────────────────────────────────────────────────────────

class QBittorrentClient:
    """Client for qBittorrent Web API (v2)."""

    def __init__(self, url: str = "http://localhost:8080",
                 username: str = "admin", password: str = "adminadmin"):
        self._url = url.rstrip("/")
        self._session = requests.Session()
        self._username = username
        self._password = password
        self._logged_in = False

    @property
    def is_logged_in(self) -> bool:
        """Whether the client has a valid session."""
        return self._logged_in

    def clone(self) -> "QBittorrentClient":
        """Return a new client with the same endpoint and credentials.

        The clone owns an independent ``requests.Session`` and is therefore
        safe to use from another worker thread.
        """
        return QBittorrentClient(self._url, self._username, self._password)

    def login(self) -> bool:
        """Authenticate with qBittorrent Web UI.

        Returns:
            ``True`` on successful authentication.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API rejects credentials or
                returns an unexpected response.
        """
        try:
            r = self._session.post(
                f"{self._url}/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
                timeout=5,
            )
            if r.status_code in (200, 204):
                has_sid = any(
                    k.startswith("QBT_SID") or k == "SID"
                    for k in self._session.cookies.keys()
                )
                if has_sid:
                    self._logged_in = True
                    return True
                raise QBittorrentApiError(
                    "Login succeeded but no SID cookie set"
                )
            elif r.status_code == 403 or "Fails" in r.text:
                raise QBittorrentApiError("Authentication failed")
            else:
                raise QBittorrentApiError(
                    f"Login returned {r.status_code}: {r.text[:200]}"
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def test_connection(self) -> str:
        """Test connection and return the qBittorrent version string.

        Returns:
            The version string (e.g. ``"v4.6.0"``).

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.get(
                f"{self._url}/api/v2/app/version", timeout=5,
            )
            if r.status_code == 200:
                return r.text.strip()
            raise QBittorrentApiError(
                f"test_connection returned {r.status_code}: {r.text[:200]}"
            )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def add_torrent_paused(self, torrent_path: str, save_path: str) -> str | None:
        """Add a torrent in paused state.

        Returns:
            The torrent hash on success, or ``None`` if the torrent was
            accepted but the hash could not be resolved yet.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns an unexpected status.
            QBittorrentError: If the torrent file cannot be read.
        """
        tn = Path(torrent_path).stem
        try:
            with open(torrent_path, "rb") as f:
                r = self._session.post(
                    f"{self._url}/api/v2/torrents/add",
                    files={"torrents": (Path(torrent_path).name, f)},
                    data={"savepath": save_path, "paused": "true"},
                    timeout=15,
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except OSError as e:
            raise QBittorrentError(
                f"Cannot read torrent file {torrent_path}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

        import time
        time.sleep(1)

        if r.status_code in (200, 201):
            return self._find_hash_by_torrent_name(tn)
        if r.status_code == 409:
            return self._find_hash_by_torrent_name(tn)
        raise QBittorrentApiError(
            f"add_torrent_paused returned {r.status_code}: {r.text[:200]}"
        )

    def get_files(self, torrent_hash: str) -> list[dict]:
        """Get file list for a torrent.

        Each entry has ``'index'``, ``'name'``, etc.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.get(
                f"{self._url}/api/v2/torrents/files",
                params={"hash": torrent_hash},
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()
            raise QBittorrentApiError(
                f"get_files returned {r.status_code}: {r.text[:200]}"
            )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def set_file_priority(
        self, torrent_hash: str, file_ids: list[int], priority: int = 0,
    ):
        """Set file priority.  0 = skip, 1 = normal.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        if not file_ids:
            return
        try:
            ids = ",".join(str(i) for i in file_ids)
            r = self._session.post(
                f"{self._url}/api/v2/torrents/filePrio",
                data={
                    "hash": torrent_hash,
                    "id": ids,
                    "priority": str(priority),
                },
                timeout=5,
            )
            if r.status_code != 200:
                raise QBittorrentApiError(
                    f"set_file_priority returned {r.status_code}:"
                    f" {r.text[:200]}"
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def pause(self, torrent_hash: str):
        """Pause a running torrent.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.post(
                f"{self._url}/api/v2/torrents/pause",
                data={"hashes": torrent_hash},
                timeout=5,
            )
            if r.status_code != 200:
                raise QBittorrentApiError(
                    f"pause returned {r.status_code}: {r.text[:200]}"
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def resume(self, torrent_hash: str):
        """Resume a paused torrent.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.post(
                f"{self._url}/api/v2/torrents/resume",
                data={"hashes": torrent_hash},
                timeout=5,
            )
            if r.status_code != 200:
                raise QBittorrentApiError(
                    f"resume returned {r.status_code}: {r.text[:200]}"
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def list_torrents(self, hashes: list[str] | None = None) -> list[dict]:
        """Return torrent snapshots, optionally restricted to *hashes*."""
        params = {}
        if hashes:
            params["hashes"] = "|".join(hashes)
        try:
            r = self._session.get(
                f"{self._url}/api/v2/torrents/info",
                params=params,
                timeout=10,
            )
            if r.status_code == 200:
                return list(r.json())
            raise QBittorrentApiError(
                f"list_torrents returned {r.status_code}: {r.text[:200]}"
            )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def get_torrent_info(self, torrent_hash: str) -> dict | None:
        """Get torrent status info.

        Returns:
            A dict with torrent properties, or ``None`` if the torrent
            list is empty (e.g. hash not found).

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.get(
                f"{self._url}/api/v2/torrents/info",
                params={"hashes": torrent_hash},
                timeout=5,
            )
            if r.status_code == 200:
                items = r.json()
                if items:
                    return items[0]
                return None
            raise QBittorrentApiError(
                f"get_torrent_info returned {r.status_code}: {r.text[:200]}"
            )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False):
        """Remove torrent from qBittorrent.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.post(
                f"{self._url}/api/v2/torrents/delete",
                data={
                    "hashes": torrent_hash,
                    "deleteFiles": "true" if delete_files else "false",
                },
                timeout=5,
            )
            if r.status_code != 200:
                raise QBittorrentApiError(
                    f"delete_torrent returned {r.status_code}: {r.text[:200]}"
                )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e

    # ── Internal helpers ────────────────────────────────────────────────────

    def _find_hash_by_torrent_name(self, name: str) -> str | None:
        """Find recently-added torrent by name (most recent match).

        Returns:
            The torrent hash, or ``None`` if no matching torrent is found.

        Raises:
            QBittorrentConnectionError: If the host is unreachable.
            QBittorrentApiError: If the API returns a non-200 response.
        """
        try:
            r = self._session.get(
                f"{self._url}/api/v2/torrents/info",
                timeout=10,
            )
            if r.status_code == 200:
                nm = name.lower()
                best = None
                best_added = -1
                for t in r.json():
                    tn = t.get("name", "").lower()
                    if nm in tn or tn in nm:
                        added = t.get("added_on", 0)
                        if added > best_added:
                            best_added = added
                            best = t["hash"]
                return best
            raise QBittorrentApiError(
                f"torrents/info returned {r.status_code}: {r.text[:200]}"
            )
        except requests.ConnectionError as e:
            raise QBittorrentConnectionError(
                f"Cannot connect to {self._url}"
            ) from e
        except requests.RequestException as e:
            raise QBittorrentApiError(f"Request failed: {e}") from e
