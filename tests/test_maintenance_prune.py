"""Primez: cache prune / expired-item purge / identifier expiry tests."""
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import kodistubs

kodistubs.install()

import xbmcvfs  # noqa: E402  (stub installed by kodistubs)

from tmdbhelper.lib.script.method.maintenance import DatabaseMaintenance  # noqa: E402
from tmdbhelper.lib.query.database.identifier import (  # noqa: E402
    FindQueriesDatabaseIdentifier, IDENTIFIER_EXPIRY)


class IdentifierExpiryTest(unittest.TestCase):
    def make_host(self, expired, rows):
        class Access:
            class connection:
                @staticmethod
                def open():
                    class _CM:
                        def __enter__(self):
                            return self

                        def __exit__(self, *exc):
                            return False
                    return _CM()

        class Host(FindQueriesDatabaseIdentifier):
            access = Access()
            set_calls = []

            def is_expired(self, item_id):
                return expired

            def get_all_values(self, table, keys, values=None, conditions=None):
                return rows

            def set_cached_values(self, table, keys, values, item_id=None, expiry=None, overwrite=True):
                self.set_calls.append((table, keys, values, item_id, expiry))

        return Host()

    def test_expired_identifier_is_a_miss(self):
        host = self.make_host(True, [{'tmdb_id': 1, 'tmdb_type': 'movie'}])
        self.assertIsNone(host.get_identifier('movie.Alien'))

    def test_fresh_identifier_is_returned(self):
        host = self.make_host(False, [{'tmdb_id': 348, 'tmdb_type': 'movie'}])
        result = host.get_identifier('movie.Alien')
        self.assertEqual((result.tmdb_id, result.tmdb_type), (348, 'movie'))

    def test_set_identifier_uses_per_item_expiry(self):
        host = self.make_host(False, [])
        host.set_identifier('movie.Alien', 348, 'movie')
        self.assertEqual(len(host.set_calls), 1)
        self.assertEqual(host.set_calls[0][3], 'movie.Alien')
        self.assertEqual(host.set_calls[0][4], IDENTIFIER_EXPIRY)


class _Stat:
    def __init__(self, path):
        self._path = path

    def st_mtime(self):
        return int(os.path.getmtime(self._path))


class PruneImageCachesTest(unittest.TestCase):
    def test_only_stale_files_are_deleted(self):
        kodistubs.reset()
        now = int(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, 'blur_v3')
            os.makedirs(folder)
            for name, age in (('old.jpg', 40 * 86400), ('new.jpg', 1 * 86400)):
                path = os.path.join(folder, name)
                with open(path, 'wb') as f:
                    f.write(b'x')
                os.utime(path, (now - age, now - age))
            deleted = []

            def fake_delete(path):
                deleted.append(path)
                os.remove(path)
                return True

            maintenance = DatabaseMaintenance()
            with mock.patch.object(xbmcvfs, 'listdir', lambda p: ([], os.listdir(p)), create=True), \
                    mock.patch.object(xbmcvfs, 'Stat', _Stat, create=True), \
                    mock.patch.object(xbmcvfs, 'delete', fake_delete), \
                    mock.patch.object(DatabaseMaintenance, 'img_cache_base',
                                      new_callable=mock.PropertyMock, return_value=f'{tmp}/'):
                maintenance.prune_image_caches(force=True)
            self.assertEqual([os.path.basename(p) for p in deleted], ['old.jpg'])
            self.assertTrue(os.path.exists(os.path.join(folder, 'new.jpg')))


class _FakeDatabase:
    """Minimal stand-in with the Database execute_sql surface maintenance uses."""

    def __init__(self, connection):
        self._connection = connection

    def execute_sql(self, query, data=None, read_only=False):
        return self._connection.execute(query, data or ())

    def execute_sql_and_close(self, query, data=None, read_only=False):
        self._connection.execute(query, data or ())
        self._connection.commit()

    @staticmethod
    def close_cursor(cursor, close_connection=False):
        if cursor:
            cursor.close()


class DeleteExpiredItemsTest(unittest.TestCase):
    def test_expired_items_purged_user_art_kept(self):
        kodistubs.reset()
        now = int(time.time())
        details = sqlite3.connect(':memory:')
        details.execute('PRAGMA foreign_keys=ON')
        details.executescript("""
            CREATE TABLE baseitem (id TEXT PRIMARY KEY, expiry INTEGER);
            CREATE TABLE user_art (parent_id TEXT, FOREIGN KEY(parent_id) REFERENCES baseitem(id) ON DELETE CASCADE);
            CREATE TABLE movie (id TEXT, FOREIGN KEY(id) REFERENCES baseitem(id) ON DELETE CASCADE);
        """)
        details.executemany('INSERT INTO baseitem VALUES (?, ?)', [
            ('movie.1', now - 200 * 86400),   # long expired -> delete
            ('movie.2', now + 86400),         # fresh -> keep
            ('movie.3', now - 200 * 86400),   # expired but has user art -> keep
            ('movie.4', now - 10 * 86400),    # expired within grace -> keep
        ])
        details.executemany('INSERT INTO movie VALUES (?)',
                             [('movie.1',), ('movie.2',), ('movie.3',), ('movie.4',)])
        details.execute('INSERT INTO user_art VALUES (?)', ('movie.3',))
        details.commit()

        queries = sqlite3.connect(':memory:')
        queries.executescript("""
            CREATE TABLE expiry (id TEXT PRIMARY KEY, expiry INTEGER);
            CREATE TABLE identifier (id TEXT, tmdb_id INTEGER, tmdb_type TEXT);
        """)
        queries.executemany('INSERT INTO expiry VALUES (?, ?)', [
            ('identifier.movie.Alien', now - 86400),
            ('identifier.movie.Fresh', now + 86400),
            ('genres', now - 200 * 86400),
        ])
        queries.executemany('INSERT INTO identifier VALUES (?, ?, ?)', [
            ('movie.Alien', 348, 'movie'),
            ('movie.Fresh', 999, 'movie'),
        ])
        queries.commit()

        fake_items = types.ModuleType('tmdbhelper.lib.items.database.database')
        fake_items.ItemDetailsDatabase = lambda: _FakeDatabase(details)
        fake_queries = types.ModuleType('tmdbhelper.lib.query.database.database')
        fake_queries.FindQueriesDatabase = lambda: _FakeDatabase(queries)
        maintenance = DatabaseMaintenance()
        with mock.patch.dict(sys.modules, {
                'tmdbhelper.lib.items.database.database': fake_items,
                'tmdbhelper.lib.query.database.database': fake_queries}):
            maintenance.delete_expired_items(force=True)

        kept = {row[0] for row in details.execute('SELECT id FROM baseitem')}
        self.assertEqual(kept, {'movie.2', 'movie.3', 'movie.4'})
        kept_movies = {row[0] for row in details.execute('SELECT id FROM movie')}
        self.assertEqual(kept_movies, {'movie.2', 'movie.3', 'movie.4'})
        kept_ids = {row[0] for row in queries.execute('SELECT id FROM identifier')}
        self.assertEqual(kept_ids, {'movie.Fresh'})
        kept_expiry = {row[0] for row in queries.execute('SELECT id FROM expiry')}
        self.assertEqual(kept_expiry, {'identifier.movie.Fresh', 'identifier.movie.Alien'})
        details.close()
        queries.close()


if __name__ == '__main__':
    unittest.main()
