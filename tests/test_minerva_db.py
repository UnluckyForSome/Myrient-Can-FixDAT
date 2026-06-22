"""
Unit tests for minerva_db
==========================
Run with: python -m pytest tests/test_minerva_db.py -v
Or:       python tests/test_minerva_db.py
"""
import logging
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from minerva_db import (
    COLLECTION_NO_INTRO,
    COLLECTION_REDUMP,
    DatEntry,
    LRUCache,
    MinervaDB,
    bdecode,
    core_title,
    extract_tags,
    fts_escape,
    parse_dat_file,
    parse_rv_fix_csv,
    resolve_match_scope,
    stem_from_romname,
    stems_match,
    title_keywords,
    _is_fix_status,
)


class TestBencode(unittest.TestCase):
    """Test pure-Python bencode parser."""

    def test_decode_integer(self):
        data = b"i42e"
        value, idx = bdecode(data, 0)
        self.assertEqual(value, 42)
        self.assertEqual(idx, 4)

    def test_decode_string(self):
        data = b"5:hello"
        value, idx = bdecode(data, 0)
        self.assertEqual(value, b"hello")
        self.assertEqual(idx, 7)

    def test_decode_list(self):
        data = b"l4:spam4:eggse"
        value, idx = bdecode(data, 0)
        self.assertEqual(value, [b"spam", b"eggs"])
        self.assertEqual(idx, len(data))

    def test_decode_dict(self):
        data = b"d3:bari1e3:fooi2ee"
        value, idx = bdecode(data, 0)
        self.assertEqual(value, {b"bar": 1, b"foo": 2})
        self.assertEqual(idx, len(data))

    def test_decode_nested(self):
        data = b"d4:listli1ei2eee"
        value, idx = bdecode(data, 0)
        self.assertEqual(value, {b"list": [1, 2]})

    def test_decode_real_torrent(self):
        """Decode a real .torrent file and verify structure."""
        torrent = Path("torrents/Minerva Myrient - 1050 torrents/"
                       "Minerva_Myrient - No-Intro - Nintendo - Game Boy Color.torrent")
        if not torrent.exists():
            self.skipTest("Torrent not available")
        data = torrent.read_bytes()
        t, _ = bdecode(data)
        # Top-level dict
        self.assertIsInstance(t, dict)
        # Has 'announce' field
        self.assertIn(b"announce", t)
        # Has 'info' dict
        self.assertIn(b"info", t)
        self.assertIsInstance(t[b"info"], dict)
        # Info has 'name' (top-level torrent name)
        self.assertIn(b"name", t[b"info"])


class TestTitleNormalization(unittest.TestCase):
    """Test title normalization and keyword extraction."""

    def test_strip_extension(self):
        self.assertEqual(stem_from_romname("game.zip"), "game")
        self.assertEqual(stem_from_romname("Game.ZIP"), "game")
        self.assertEqual(stem_from_romname("Game.gbc"), "game")

    def test_core_title_basic(self):
        self.assertEqual(core_title("tetris dx (world)"), "tetris dx")
        self.assertEqual(core_title("tetris dx (world) (sgb enhanced) (gb compatible)"),
                         "tetris dx")

    def test_core_title_normalizes_the(self):
        # "The" prefix → suffix
        self.assertEqual(core_title("the legend of zelda (usa)"), "legend of zelda the")
        # ", The" suffix → suffix (hyphen is preserved as separator)
        # Note: core_title doesn't strip hyphens, so '-' remains
        result = core_title("legend of zelda, the - link's awakening dx")
        self.assertIn("legend of zelda the", result)
        self.assertIn("links awakening dx", result)

    def test_core_title_normalizes_brothers(self):
        self.assertEqual(core_title("super mario brothers (usa)"), "super mario bros")
        self.assertEqual(core_title("super mario bros. (usa)"), "super mario bros")

    def test_core_title_normalizes_punctuation(self):
        # Periods removed
        self.assertEqual(core_title("super mario bros. (usa)"), "super mario bros")
        # Apostrophes removed
        self.assertEqual(core_title("link's awakening (usa)"), "links awakening")
        # Combined
        self.assertEqual(core_title("super mario bros.'s (usa)"), "super mario bross")

    def test_core_title_normalizes_ampersand(self):
        self.assertEqual(core_title("sonic & knuckles (usa)"), "sonic and knuckles")

    def test_title_keywords_filters_stopwords(self):
        kws = title_keywords("the legend of zelda (usa, europe) (sgb enhanced)")
        self.assertIn("legend", kws)
        self.assertIn("zelda", kws)
        self.assertNotIn("the", kws)
        self.assertNotIn("of", kws)
        self.assertNotIn("usa", kws)
        self.assertNotIn("europe", kws)
        self.assertNotIn("sgb", kws)
        self.assertNotIn("enhanced", kws)

    def test_title_keywords_min_length(self):
        # Single chars and 2-char words should be excluded
        kws = title_keywords("legend of zelda (a b cd ef)")
        self.assertNotIn("a", kws)
        self.assertNotIn("b", kws)
        self.assertNotIn("cd", kws)  # cd is in stopwords via len check
        # Actually, cd is len 2 which is < MIN_KEYWORD_LEN=3
        self.assertNotIn("ef", kws)
        self.assertIn("legend", kws)
        self.assertIn("zelda", kws)


class TestStemsMatch(unittest.TestCase):
    """Test fuzzy title matching logic."""

    def test_exact_match(self):
        self.assertTrue(stems_match(
            "tetris dx (world) (sgb enhanced) (gb compatible)",
            "tetris dx (world) (sgb enhanced) (gb compatible)"))

    def test_period_difference(self):
        # "bros" vs "bros." should match (period normalized)
        self.assertTrue(stems_match(
            "super mario bros deluxe (usa, europe)",
            "super mario bros. deluxe (usa, europe)"))

    def test_apostrophe_difference(self):
        # Link-s vs Link's
        self.assertTrue(stems_match(
            "the legend of zelda - link-s awakening dx (usa, europe)",
            "legend of zelda, the - link's awakening dx (germany)"))

    def test_parenthetical_differences(self):
        # DB has extra parens, DAT doesn't
        self.assertTrue(stems_match(
            "r-type dx (usa, europe)",
            "r-type dx (usa, europe) (gb compatible)"))

    def test_the_article_placement(self):
        self.assertTrue(stems_match(
            "the legend of zelda - link-s awakening dx (usa, europe)",
            "legend of zelda, the - link-s awakening dx (usa, europe)"))

    def test_completely_different(self):
        self.assertFalse(stems_match(
            "fake game that does not exist (world)",
            "totally different game (usa)"))

    def test_partial_keyword_overlap(self):
        # 50% overlap shouldn't match
        self.assertFalse(stems_match(
            "super mario bros deluxe (usa, europe)",
            "super mario kart (usa)"))

    def test_keyword_subset(self):
        # Smaller is subset of larger with enough keywords
        self.assertTrue(stems_match(
            "tetris (world)",
            "tetris dx (world) (sgb enhanced)"))


class TestFtsEscape(unittest.TestCase):
    """Test FTS5 query escaping."""

    def test_basic_escape(self):
        self.assertEqual(fts_escape("hello"), '"hello"')

    def test_quote_escape(self):
        # Embedded quotes are doubled per FTS5 syntax
        self.assertEqual(fts_escape('say"hi'), '"say""hi"')

    def test_special_chars(self):
        # Special FTS5 chars don't need escaping when quoted
        self.assertEqual(fts_escape("foo:bar"), '"foo:bar"')
        self.assertEqual(fts_escape("foo*"), '"foo*"')
        self.assertEqual(fts_escape("foo-bar"), '"foo-bar"')


class TestParseDatFile(unittest.TestCase):
    """Test DAT file XML parser."""

    def test_resolve_match_scope_prefers_dat_metadata_when_ui_is_all(self):
        coll, sys_name = resolve_match_scope(
            "No-Intro",
            "Nintendo - Game Boy Advance",
            "All",
            "All",
        )
        self.assertEqual(coll, "No-Intro")
        self.assertEqual(sys_name, "Nintendo - Game Boy Advance")

    def test_resolve_match_scope_keeps_explicit_ui_filter(self):
        coll, sys_name = resolve_match_scope(
            "No-Intro",
            "Nintendo - Game Boy Advance",
            "Redump",
            "Nintendo - Game Boy Color",
        )
        self.assertEqual(coll, "Redump")
        self.assertEqual(sys_name, "Nintendo - Game Boy Color")

    def test_nonexistent_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_dat_file(Path("/nonexistent/path.dat"))

    def test_parse_real_fixdat(self):
        """Parse an actual fixDat file from the project."""
        fp = Path("fixDat__Nintendo - Game Boy Color (No-Intro - Fresh1G1R - Hearto).dat")
        if not fp.exists():
            self.skipTest("Test fixDat not available")
        info = parse_dat_file(fp)
        self.assertGreater(len(info.entries), 0)
        self.assertIsNotNone(info.name)
        self.assertEqual(info.collection, COLLECTION_NO_INTRO)
        # Entries have valid filenames
        for e in info.entries[:5]:
            self.assertTrue(e.filename)
            self.assertIsInstance(e.size, int)

    def test_infer_no_intro_from_url(self):
        import tempfile
        xml = b"""<?xml version="1.0"?>
<datafile>
  <header>
    <name>Nintendo - Test</name>
    <url>https://datomatic.no-intro.org/index.php?page=download</url>
  </header>
  <game name="Test (USA)">
    <rom name="Test (USA).zip" size="1234"/>
  </game>
</datafile>"""
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            f.write(xml)
            path = Path(f.name)
        try:
            info = parse_dat_file(path)
            self.assertEqual(info.collection, COLLECTION_NO_INTRO)
            self.assertEqual(info.name, "Nintendo - Test")
            self.assertEqual(len(info.entries), 1)
            self.assertEqual(info.entries[0].filename, "Test (USA).zip")
            self.assertEqual(info.entries[0].size, 1234)
        finally:
            path.unlink()

    def test_clean_fixdat_retool_system_name(self):
        import tempfile
        xml = b"""<?xml version="1.0"?>
<datafile>
  <header>
    <name>FixDat_Nintendo - Game Boy Color (Retool)</name>
    <url>https://no-intro.org/</url>
  </header>
  <game name="Test Game (USA)">
    <rom name="Test Game (USA).zip" size="1234"/>
  </game>
</datafile>"""
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            f.write(xml)
            path = Path(f.name)
        try:
            info = parse_dat_file(path)
            self.assertEqual(info.collection, COLLECTION_NO_INTRO)
            self.assertEqual(info.system, "Nintendo - Game Boy Color")
        finally:
            path.unlink()

    def test_fallback_system_from_filename_stem(self):
        import tempfile
        xml = b"""<?xml version="1.0"?>
<datafile>
  <header>
    <url>https://example.invalid/</url>
  </header>
  <game name="Test Game (USA)">
    <rom name="Test Game (USA).zip" size="1234"/>
  </game>
</datafile>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixDat__Nintendo - Game Boy Advance [T-En] Collection (2026-04-10).dat"
            path.write_bytes(xml)
            info = parse_dat_file(path)
            self.assertIsNone(info.collection)
            self.assertEqual(info.system, "Nintendo - Game Boy Advance [T-En] Collection")

    def test_infer_redump_from_url(self):
        import tempfile
        xml = b"""<?xml version="1.0"?>
<datafile>
  <header>
    <name>Sony - PlayStation</name>
    <url>http://redump.org/</url>
  </header>
  <game name="Game (USA)">
    <rom name="Game (USA).bin" size="5678"/>
  </game>
</datafile>"""
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            f.write(xml)
            path = Path(f.name)
        try:
            info = parse_dat_file(path)
            self.assertEqual(info.collection, COLLECTION_REDUMP)
        finally:
            path.unlink()


class TestParseRvFixCsv(unittest.TestCase):
    """Test RomVault CSV parser."""

    def test_basic_csv(self):
        import tempfile
        csv = b"""Status,Game,Size,CRC,SHA1,Emulator,Date
Missing,Tetris DX.zip,107374,abc,def,No-Intro,2025-01-01
OK,Good Game.zip,12345,xyz,uvw,No-Intro,2025-01-01
Missing,Pokemon.zip,2097152,123,456,No-Intro,2025-01-01
"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(csv)
            path = Path(f.name)
        try:
            info = parse_rv_fix_csv(path)
            # 2 entries (OK filtered out)
            self.assertEqual(len(info.entries), 2)
            names = [e.filename for e in info.entries]
            self.assertIn("Tetris DX.zip", names)
            self.assertIn("Pokemon.zip", names)
            self.assertEqual(info.name, path.stem)
        finally:
            path.unlink()

    def test_quoted_csv_with_parens(self):
        import tempfile
        csv = (b'"Status","Game","Size"\n'
               b'"Missing","Tetris DX (World) (SGB).zip","107374"\n')
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(csv)
            path = Path(f.name)
        try:
            info = parse_rv_fix_csv(path)
            self.assertEqual(len(info.entries), 1)
            self.assertEqual(info.entries[0].filename,
                             "Tetris DX (World) (SGB).zip")
        finally:
            path.unlink()

    def test_unquoted_csv_remerges_parens(self):
        import tempfile
        # Comma inside parens splits the field, but we re-merge it
        csv = b"""Status,Game,Size
Missing,Pokemon Crystal (USA, Europe).zip,2097152
"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(csv)
            path = Path(f.name)
        try:
            info = parse_rv_fix_csv(path)
            self.assertEqual(len(info.entries), 1)
            self.assertIn("(USA, Europe)", info.entries[0].filename)
        finally:
            path.unlink()

    def test_alternative_status_values(self):
        """Verify all fix status values are recognized."""
        for status in ["Missing", "Fix Required", "Wrong Size", "Bad CRC",
                       "Not Found", "Mismatch", "fixme"]:
            self.assertTrue(_is_fix_status(status), f"Should accept: {status}")
        for status in ["OK", "Verified", "Complete", "Have"]:
            self.assertFalse(_is_fix_status(status), f"Should reject: {status}")


class TestLRUCache(unittest.TestCase):
    """Test LRU cache implementation."""

    def test_basic_get_put(self):
        cache = LRUCache(max_entries=3, ttl=10)
        cache.put(("k1",), ("v1", 0))
        result = cache.get(("k1",))
        self.assertEqual(result, ("v1", 0))

    def test_miss_returns_none(self):
        cache = LRUCache()
        self.assertIsNone(cache.get(("missing",)))

    def test_eviction(self):
        cache = LRUCache(max_entries=2, ttl=10)
        cache.put(("k1",), ("v1", 0))
        cache.put(("k2",), ("v2", 0))
        cache.put(("k3",), ("v3", 0))  # Should evict k1
        self.assertIsNone(cache.get(("k1",)))
        self.assertEqual(cache.get(("k2",)), ("v2", 0))
        self.assertEqual(cache.get(("k3",)), ("v3", 0))

    def test_lru_ordering(self):
        cache = LRUCache(max_entries=2, ttl=10)
        cache.put(("k1",), ("v1", 0))
        cache.put(("k2",), ("v2", 0))
        # Access k1 to make it most recently used
        cache.get(("k1",))
        # Now add k3, should evict k2 (oldest)
        cache.put(("k3",), ("v3", 0))
        self.assertEqual(cache.get(("k1",)), ("v1", 0))
        self.assertIsNone(cache.get(("k2",)))
        self.assertEqual(cache.get(("k3",)), ("v3", 0))

    def test_ttl_expiration(self):
        import time
        cache = LRUCache(max_entries=10, ttl=1)  # 1 second TTL
        cache.put(("k1",), ("v1", 0))
        self.assertEqual(cache.get(("k1",)), ("v1", 0))
        time.sleep(1.1)
        self.assertIsNone(cache.get(("k1",)))

    def test_stats(self):
        cache = LRUCache()
        cache.put(("k1",), ("v1", 0))
        cache.get(("k1",))  # hit
        cache.get(("k2",))  # miss
        stats = cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)

    def test_clear(self):
        cache = LRUCache()
        cache.put(("k1",), ("v1", 0))
        cache.get(("k1",))  # 1 hit
        cache.clear()        # resets counters
        # After clear, next get is a miss (counters reset)
        self.assertIsNone(cache.get(("k1",)))
        stats = cache.stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 1)  # 1 miss from the get after clear


class TestIntegrationMatchDat(unittest.TestCase):
    """Integration tests for MinervaDB.match_dat (requires index)."""

    @classmethod
    def setUpClass(cls):
        """Skip these tests if a usable index doesn't exist."""
        cls.db_path = Path("torrents/minerva_index.db")
        if not cls.db_path.exists() or cls.db_path.stat().st_size == 0:
            raise unittest.SkipTest(f"Index not found: {cls.db_path}")
        import sqlite3
        try:
            c = sqlite3.connect(str(cls.db_path))
            has_files = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'"
            ).fetchone()
            has_rows = has_files and c.execute("SELECT 1 FROM files LIMIT 1").fetchone()
            c.close()
        except sqlite3.OperationalError:
            has_rows = None
        if not has_rows:
            raise unittest.SkipTest(f"Index not built (no data): {cls.db_path}")

    def setUp(self):
        self.db = MinervaDB.__new__(MinervaDB)  # bypass __init__
        from minerva_db import LRUCache
        self.db._path = str(self.db_path)
        self.db._cache = LRUCache()
        self.db._validate_schema()

    def test_match_exact(self):
        entries = [
            DatEntry("Tetris DX (World) (SGB Enhanced) (GB Compatible).zip", 107374),
        ]
        report = self.db.match_dat(
            entries,
            collection="No-Intro",
            system="Nintendo - Game Boy Color",
        )
        self.assertEqual(len(report.matched_stems), 1)
        self.assertEqual(len(report.unmatched), 0)
        self.assertEqual(report.results[0].matched_via, "exact")

    def test_match_fuzzy_super_mario(self):
        # Periods differ between DAT and torrent
        entries = [
            DatEntry("Super Mario Bros Deluxe (USA, Europe).zip", 524288),
        ]
        report = self.db.match_dat(
            entries,
            collection="No-Intro",
            system="Nintendo - Game Boy Color",
        )
        self.assertEqual(len(report.matched_stems), 1)
        self.assertEqual(len(report.unmatched), 0)
        # Should match via fuzzy (not exact)
        self.assertIn(report.results[0].matched_via, ["fts5", "trigram", "keyword"])

    def test_match_unmatched(self):
        entries = [
            DatEntry("Completely Fake Game That Does Not Exist.zip", 12345),
        ]
        report = self.db.match_dat(
            entries,
            collection="No-Intro",
            system="Nintendo - Game Boy Color",
        )
        self.assertEqual(len(report.matched_stems), 0)
        self.assertEqual(len(report.unmatched), 1)

    def test_match_gbc_fixdat(self):
        """Full GBC fixDat test - should be fast."""
        fp = Path("fixDat__Nintendo - Game Boy Color "
                  "(No-Intro - Fresh1G1R - Hearto).dat")
        if not fp.exists():
            self.skipTest("GBC fixDat not available")
        info = parse_dat_file(fp)
        report = self.db.match_dat(
            info.entries,
            collection="No-Intro",
            system="Nintendo - Game Boy Color",
        )
        # Should match most entries
        self.assertGreater(len(report.matched_stems), 250)
        # Should be reasonably fast
        self.assertLess(report.total_time_ms, 10000)  # < 10s
        # Cache should be populated
        stats = self.db.cache_stats()
        self.assertEqual(stats["misses"], len(info.entries) + 1)  # +1 for cache key lookup

    def test_cache_works(self):
        entries = [
            DatEntry("Tetris DX (World) (SGB Enhanced) (GB Compatible).zip", 107374),
        ]
        # First call - cache miss
        report1 = self.db.match_dat(entries, "No-Intro", "Nintendo - Game Boy Color")
        # Second call - cache hit
        report2 = self.db.match_dat(entries, "No-Intro", "Nintendo - Game Boy Color")
        # Results should be the same object (cached)
        self.assertIs(report1, report2)

    def test_search_tetris_returns_results(self):
        rows, total = self.db.search("Tetris", limit=10)
        self.assertGreater(total, 0)
        self.assertGreater(len(rows), 0)

    def test_search_with_scope_returns_results(self):
        rows, total = self.db.search(
            "Tetris",
            collection="No-Intro",
            system="Nintendo - Game Boy Color",
            limit=10,
        )
        self.assertGreater(total, 0)
        self.assertGreater(len(rows), 0)

    def test_search_by_tags_supports_scope_query_and_size(self):
        rows, total = self.db.search_by_tags(
            query="Tetris",
            collection="No-Intro",
            systems=["Nintendo - Game Boy Color"],
            limit=10,
        )
        self.assertGreater(total, 0)
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(
            row["collection"] == "No-Intro"
            and row["system"] == "Nintendo - Game Boy Color"
            for row in rows
        ))

        target_size = rows[0]["size"]
        sized_rows, sized_total = self.db.search_by_tags(
            query="Tetris",
            collection="No-Intro",
            systems=["Nintendo - Game Boy Color"],
            min_size=target_size,
            max_size=target_size,
            limit=10,
        )
        self.assertGreater(sized_total, 0)
        self.assertGreater(len(sized_rows), 0)
        self.assertTrue(all(row["size"] == target_size for row in sized_rows))


class TestBenchmarks(unittest.TestCase):
    """Performance benchmarks (not assertions, just timing)."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = Path("torrents/minerva_index.db")
        if not cls.db_path.exists() or cls.db_path.stat().st_size == 0:
            raise unittest.SkipTest("Index not found")
        import sqlite3
        try:
            c = sqlite3.connect(str(cls.db_path))
            has_files = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'"
            ).fetchone()
            has_rows = has_files and c.execute("SELECT 1 FROM files LIMIT 1").fetchone()
            c.close()
        except sqlite3.OperationalError:
            has_rows = None
        if not has_rows:
            raise unittest.SkipTest("Index not built (no data)")

    def setUp(self):
        from minerva_db import LRUCache
        self.db = MinervaDB.__new__(MinervaDB)
        self.db._path = str(self.db_path)
        self.db._cache = LRUCache()
        self.db._validate_schema()

    def test_benchmark_search(self):
        """Benchmark substring search."""
        import time
        t0 = time.time()
        rows, total = self.db.search("Tetris", limit=100)
        elapsed = (time.time() - t0) * 1000
        print(f"\n  search('Tetris', limit=100): {elapsed:.0f}ms, {total:,} total")

        t0 = time.time()
        rows, total = self.db.search("Mario", limit=100)
        elapsed = (time.time() - t0) * 1000
        print(f"  search('Mario', limit=100): {elapsed:.0f}ms, {total:,} total")

    def test_benchmark_match_scaling(self):
        """Benchmark match_dat scaling."""
        import time
        entries = [DatEntry("Tetris DX (World) (SGB Enhanced) (GB Compatible).zip", 107374)] * 50
        t0 = time.time()
        self.db.match_dat(
            entries, "No-Intro", "Nintendo - Game Boy Color")
        elapsed = (time.time() - t0) * 1000
        print(f"\n  match_dat(50 identical entries, cache): {elapsed:.0f}ms")
        # Should be fast due to cache
        self.assertLess(elapsed, 100)


class TestExtractTags(unittest.TestCase):
    """Test tag extraction from filename stems."""

    def test_extracts_known_tag(self):
        self.assertEqual(extract_tags("tetris dx (world) (aftermarket)"), {"aftermarket"})

    def test_multiple_tags(self):
        tags = extract_tags("game (usa) (translation) (v1.0)")
        self.assertIn("translation", tags)
        self.assertNotIn("v1.0", tags)

    def test_unknown_tag_ignored(self):
        self.assertEqual(extract_tags("game (usa) (customtag)"), set())

    def test_no_tags(self):
        self.assertEqual(extract_tags("mario bros"), set())

    def test_tag_case_insensitive(self):
        self.assertEqual(extract_tags("game (Aftermarket)"), {"aftermarket"})

    def test_private_tag(self):
        self.assertEqual(extract_tags("game (Private)"), {"private"})

    def test_homebrew_tag(self):
        self.assertEqual(extract_tags("game (Homebrew)"), {"homebrew"})


class _DictRow(dict):
    """A dict that also supports attribute access, like sqlite3.Row."""


class TestBuildSyntheticDat(unittest.TestCase):
    """Test synthetic DAT XML generation."""

    def setUp(self):
        self.db = MinervaDB.__new__(MinervaDB)
        self.db._cache = None
        self.db._path = ":memory:"

    def test_generates_valid_xml(self):
        rows = [
            self._row("Tetris (USA)", "Tetris (USA).zip", 1234),
            self._row("Mario (Japan)", "Mario (Japan).zip", 5678),
        ]
        xml = self.db.build_synthetic_dat(rows, "Test DAT")
        self.assertIn("<datafile>", xml)
        self.assertIn("<header>", xml)
        self.assertIn("Tetris (USA)", xml)
        self.assertIn('size="1234"', xml)
        self.assertIn("no-intro.org", xml)

    def test_parse_roundtrip(self):
        """Generated DAT can be parsed back by parse_dat_file()."""
        import tempfile
        rows = [
            self._row("Game (World)", "Game (World).zip", 9999),
        ]
        xml = self.db.build_synthetic_dat(rows, "Roundtrip Test",
                                          system="Nintendo - Test")
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False, mode="w") as f:
            f.write(xml)
            path = Path(f.name)
        try:
            info = parse_dat_file(path)
            self.assertEqual(len(info.entries), 1)
            self.assertEqual(info.entries[0].filename, "Game (World).zip")
            self.assertEqual(info.entries[0].size, 9999)
        finally:
            path.unlink()

    def test_xml_escapes_special_chars(self):
        rows = [
            self._row('Game & "Reloaded" (USA)', 'Game & "Reloaded" (USA).zip', 0),
        ]
        xml = self.db.build_synthetic_dat(rows)
        self.assertIn("&amp;", xml)
        self.assertIn("&quot;", xml)
        # The roundtrip test above already validates the XML is parseable;
        # here we just verify the entities are present.

    def _row(self, stem: str, basename: str, size: int) -> _DictRow:
        return _DictRow(stem=stem, basename=basename, size=size)


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.WARNING)
    unittest.main(verbosity=2)
