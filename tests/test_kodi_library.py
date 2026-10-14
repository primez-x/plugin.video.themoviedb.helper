"""Cover indexed IDs, duplicates, title fallback, cache reuse, and consumed RPC fields."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import kodistubs

kodistubs.install()
ROOT = Path(__file__).resolve().parents[1]


def load_rpc():
    parser = types.ModuleType('jurialmunkey.parser')
    parser.__dict__.update(sys.modules['jurialmunkey.parser'].__dict__)
    parser.find_dict_in_list = lambda rows, key, value: [n for n, row in enumerate(rows) if row.get(key) == value]
    thread = types.ModuleType('tmdbhelper.lib.addon.thread')
    thread.use_thread_lock = lambda *a, **k: lambda func: func
    jsnrpc = types.ModuleType('jurialmunkey.jsnrpc')
    for name in ('get_library', 'set_tags', 'set_watched', 'set_playprogress', 'get_directory', 'get_jsonrpc'):
        setattr(jsnrpc, name, mock.Mock())
    spec = importlib.util.spec_from_file_location('runtime_kodi_rpc', ROOT / 'resources/tmdbhelper/lib/api/kodi/rpc.py')
    result = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {
            parser.__name__: parser, thread.__name__: thread, jsnrpc.__name__: jsnrpc}), \
            mock.patch('jurialmunkey.jsnrpc', jsnrpc, create=True):
        spec.loader.exec_module(result)
    return result


class KodiLibraryLookupTest(unittest.TestCase):
    def setUp(self):
        self.rpc = load_rpc()
        self.library = self.rpc.KodiLibrary('both')
        self.library.index_identifiers = True
        self.library._database = [
            {'dbid': 10, 'tmdb_id': '42', 'imdb_id': 'tt42', 'tvdb_id': '100', 'title': 'Title', 'year': 2024},
            {'dbid': 11, 'tmdb_id': '42', 'imdb_id': 'tt43', 'title': 'Other', 'year': 2020},
            {'dbid': 12, 'tmdb_id': '99', 'title': 'Title', 'year': 2020},
        ]

    def test_identifiers_preserve_priority_duplicates_and_numeric_input(self):
        with mock.patch.object(self.rpc, 'find_dict_in_list', side_effect=AssertionError('linear ID scan')):
            self.assertEqual(self.library._get_info('dbid', tmdb_id=42), 10)
            self.assertEqual(self.library._get_info('dbid', imdb_id='tt43', tmdb_id=42), 11)
            self.assertEqual(self.library._get_info('dbid', tvdb_id=100), 10)
            self.assertEqual(self.library._get_info('dbid', dbid=12, tmdb_id=42), 12)
            self.assertEqual(self.library._get_info('dbid', imdb_id='absent', tmdb_id=42), 10)

    def test_indexes_build_once_and_title_year_fallback_is_preserved(self):
        class Rows(list):
            scans = 0

            def __iter__(self):
                self.scans += 1
                return super().__iter__()

        rows = Rows(self.library._database)
        self.library._database = rows
        for number in range(20):
            self.assertEqual(self.library._get_info('dbid', tmdb_id=42), 10)
        self.assertEqual(rows.scans, 1)
        self.assertEqual(self.library._get_info('dbid', title='Title', year=2020), 12)
        self.assertIsNone(self.library._get_info('dbid', title='Title', year=1900))

    def test_empty_library_is_a_miss(self):
        self.library._database = []
        self.assertIsNone(self.library._get_info('dbid', tmdb_id=42))

    def test_default_player_lookup_keeps_the_original_path(self):
        self.library.index_identifiers = False
        with mock.patch.object(self.rpc, 'find_dict_in_list', wraps=self.rpc.find_dict_in_list) as find:
            self.assertEqual(self.library._get_info('dbid', tmdb_id=42), 10)
        find.assert_called_once()
        self.assertNotIn('identifier_indexes', self.library.__dict__)

    def test_directory_kodi_db_enables_indexes(self):
        mapping = types.ModuleType('tmdbhelper.lib.api.mapping')
        mapping.set_show = mock.Mock()
        mapping.get_empty_item = mock.Mock()
        spec = importlib.util.spec_from_file_location('runtime_kodi_items', ROOT / 'resources/tmdbhelper/lib/items/kodi.py')
        result = importlib.util.module_from_spec(spec)
        self.library.index_identifiers = False
        with mock.patch.dict(sys.modules, {mapping.__name__: mapping, 'tmdbhelper.lib.api.kodi.rpc': self.rpc}), \
                mock.patch.object(self.rpc, 'get_kodi_library', return_value=self.library):
            spec.loader.exec_module(result)
            directory_db = result.KodiDb('movie')
        self.assertIs(directory_db.kodi_db, self.library)
        self.assertTrue(directory_db.kodi_db.index_identifiers)

    def test_details_request_excludes_unused_fields_and_keeps_mapped_fields(self):
        with mock.patch.object(self.rpc, 'get_item_details', return_value={}) as details:
            self.rpc.get_movie_details(1)
            movie = details.call_args.kwargs['properties']
            self.rpc.get_tvshow_details(2)
            tv = details.call_args.kwargs['properties']
        for properties in (movie, tv):
            self.assertTrue({'cast', 'art', 'ratings', 'uniqueid', 'playcount', 'title'}.issubset(properties))
            self.assertFalse({'fanart', 'thumbnail', 'file', 'year'}.intersection(properties))
        self.assertFalse({'resume', 'episodeguide'}.intersection(movie + tv))
        self.assertIn('streamdetails', movie)
        self.assertIn('watchedepisodes', tv)


class ThreadSettingsTest(unittest.TestCase):
    def test_thread_limit_changes_between_pools(self):
        thread = types.ModuleType('jurialmunkey.thread')

        class Pool:
            def __init__(self, items, func):
                self.pool_size = self.thread_max

        thread.ParallelThread = Pool
        thread.SafeThread = object
        plugin = sys.modules['tmdbhelper.lib.addon.plugin']
        settings = {'limit': 2}
        spec = importlib.util.spec_from_file_location('runtime_thread', ROOT / 'resources/tmdbhelper/lib/addon/thread.py')
        result = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {thread.__name__: thread}), \
                mock.patch('jurialmunkey.thread', thread, create=True), \
                mock.patch.object(plugin, 'encode_url', lambda *a, **k: '', create=True), \
                mock.patch.object(plugin, 'get_setting', lambda *a, **k: settings['limit']):
            spec.loader.exec_module(result)
            first = result.ParallelThread([], None)
            settings['limit'] = 5
            second = result.ParallelThread([], None)
        self.assertEqual((first.pool_size, second.pool_size), (2, 5))


if __name__ == '__main__':
    unittest.main()
