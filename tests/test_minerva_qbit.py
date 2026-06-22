"""
Unit tests for minerva_qbit
============================
Run with: python -m pytest tests/test_minerva_qbit.py -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from minerva_qbit import (
    QBittorrentClient,
    QBittorrentApiError,
    QBittorrentConnectionError,
)


def _make_session():
    """Return a MagicMock that quacks like requests.Session()."""
    return MagicMock()


def _ok_response(status=200, json_data=None, cookies=None, text=""):
    """Build a mock requests.Response."""
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_data if json_data is not None else []
    r.cookies.keys.return_value = cookies or []
    return r


class TestQBittorrentClientInit(unittest.TestCase):
    def test_default_url_has_trailing_slash_stripped(self):
        c = QBittorrentClient(url="http://localhost:8080/")
        self.assertEqual(c._url, "http://localhost:8080")

    def test_credentials_stored(self):
        c = QBittorrentClient("http://q", "alice", "secret")
        self.assertEqual(c._username, "alice")
        self.assertEqual(c._password, "secret")
        self.assertFalse(c._logged_in)


class TestLogin(unittest.TestCase):
    def test_login_success_204_with_sid_cookie(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.cookies.keys.return_value = ["QBT_SID_8080"]
        c._session.post.return_value = _ok_response(status=204)
        self.assertTrue(c.login())
        self.assertTrue(c._logged_in)

    def test_login_success_200_with_sid_cookie(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.cookies.keys.return_value = ["SID"]
        c._session.post.return_value = _ok_response(status=200)
        self.assertTrue(c.login())

    def test_login_failure_204_without_sid_cookie(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.cookies.keys.return_value = ["other_cookie"]
        c._session.post.return_value = _ok_response(status=204)
        with self.assertRaises(QBittorrentApiError):
            c.login()
        self.assertFalse(c._logged_in)

    def test_login_failure_500(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.post.return_value = _ok_response(status=500)
        with self.assertRaises(QBittorrentApiError):
            c.login()

    def test_login_network_error(self):
        import requests
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.post.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(QBittorrentConnectionError):
            c.login()


class TestTestConnection(unittest.TestCase):
    def test_returns_version_on_200(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.get.return_value = _ok_response(status=200, text="v4.6.0\n")
        ver = c.test_connection()
        self.assertEqual(ver, "v4.6.0")

    def test_raises_on_500(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.get.return_value = _ok_response(status=500, text="oops")
        with self.assertRaises(QBittorrentApiError):
            c.test_connection()

    def test_raises_on_network_failure(self):
        import requests
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.get.side_effect = requests.ConnectionError("nope")
        with self.assertRaises(QBittorrentConnectionError):
            c.test_connection()


class TestAddTorrentPaused(unittest.TestCase):
    def test_returns_hash_on_200(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        # 1st call: POST /torrents/add  → 200
        # 2nd call: GET  /torrents/info → torrent list
        c._session.post.return_value = _ok_response(status=200)
        c._session.get.return_value = _ok_response(
            status=200,
            json_data=[{"name": "Some_Torrent", "hash": "ABC123",
                        "added_on": 1000}],
        )
        m = mock_open(read_data=b"fake-torrent-bytes")
        with patch("builtins.open", m, create=True):
            h = c.add_torrent_paused("/tmp/some_torrent.torrent", "/save")
        self.assertEqual(h, "ABC123")

    def test_returns_hash_on_409(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.post.return_value = _ok_response(status=409)
        c._session.get.return_value = _ok_response(
            status=200,
            json_data=[{"name": "Some_Torrent", "hash": "EXISTING",
                        "added_on": 999}],
        )
        m = mock_open(read_data=b"x")
        with patch("builtins.open", m, create=True):
            h = c.add_torrent_paused("/tmp/some_torrent.torrent", "/save")
        self.assertEqual(h, "EXISTING")

    def test_raises_on_500(self):
        c = QBittorrentClient("http://q", "u", "p")
        c._session = _make_session()
        c._session.post.return_value = _ok_response(status=500)
        m = mock_open(read_data=b"x")
        with patch("builtins.open", m, create=True):
            with self.assertRaises(QBittorrentApiError):
                c.add_torrent_paused("/tmp/x.torrent", "/save")


class TestGetFiles(unittest.TestCase):
    def test_returns_file_list(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(
            status=200, json_data=[{"index": 0, "name": "a.rom"},
                                   {"index": 1, "name": "b.rom"}])
        files = c.get_files("HASH")
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["name"], "a.rom")

    def test_raises_on_500(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(status=500)
        with self.assertRaises(QBittorrentApiError):
            c.get_files("HASH")


class TestSetFilePriority(unittest.TestCase):
    def test_skips_when_empty(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c.set_file_priority("HASH", [])
        c._session.post.assert_not_called()

    def test_posts_with_comma_separated_ids(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.post.return_value = _ok_response()
        c.set_file_priority("HASH", [0, 2, 5], priority=0)
        call = c._session.post.call_args
        self.assertEqual(call.args[0], "http://localhost:8080/api/v2/torrents/filePrio")
        self.assertEqual(call.kwargs["data"]["hash"], "HASH")
        self.assertEqual(call.kwargs["data"]["id"], "0,2,5")
        self.assertEqual(call.kwargs["data"]["priority"], "0")


class TestResume(unittest.TestCase):
    def test_posts_to_resume_endpoint(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.post.return_value = _ok_response()
        c.resume("HASH")
        call = c._session.post.call_args
        self.assertEqual(call.args[0], "http://localhost:8080/api/v2/torrents/resume")
        self.assertEqual(call.kwargs["data"]["hashes"], "HASH")


class TestGetTorrentInfo(unittest.TestCase):
    def test_returns_first_item(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(
            status=200, json_data=[{"progress": 0.5, "state": "downloading"}])
        info = c.get_torrent_info("HASH")
        self.assertEqual(info["progress"], 0.5)

    def test_returns_none_on_empty(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(status=200, json_data=[])
        self.assertIsNone(c.get_torrent_info("HASH"))


class TestDeleteTorrent(unittest.TestCase):
    def test_delete_with_files(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.post.return_value = _ok_response()
        c.delete_torrent("HASH", delete_files=True)
        call = c._session.post.call_args
        self.assertEqual(call.kwargs["data"]["deleteFiles"], "true")

    def test_delete_without_files(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.post.return_value = _ok_response()
        c.delete_torrent("HASH", delete_files=False)
        call = c._session.post.call_args
        self.assertEqual(call.kwargs["data"]["deleteFiles"], "false")


class TestFindHashByTorrentName(unittest.TestCase):
    def test_returns_most_recent_match(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(
            status=200,
            json_data=[
                {"name": "old_name", "hash": "OLD", "added_on": 100},
                {"name": "Some_Torrent", "hash": "NEW", "added_on": 200},
                {"name": "unrelated", "hash": "X", "added_on": 300},
            ],
        )
        self.assertEqual(c._find_hash_by_torrent_name("Some_Torrent"), "NEW")

    def test_returns_none_when_no_match(self):
        c = QBittorrentClient()
        c._session = _make_session()
        c._session.get.return_value = _ok_response(
            status=200,
            json_data=[{"name": "totally_different", "hash": "X",
                        "added_on": 100}],
        )
        self.assertIsNone(c._find_hash_by_torrent_name("Some_Torrent"))


if __name__ == "__main__":
    unittest.main()
