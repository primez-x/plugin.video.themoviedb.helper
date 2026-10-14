"""Cover disabled providers, redundant TMDb requests, shared queries, and rating formats."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import kodistubs

kodistubs.install()
ROOT = Path(__file__).resolve().parents[1]


def load_ratings():
    base = types.ModuleType('tmdbhelper.lib.items.database.baseview_factories.concrete_classes.baseclass')
    base.BaseList = object
    queries = types.ModuleType('tmdbhelper.lib.query.database.database')
    queries.FindQueriesDatabase = mock.Mock(side_effect=AssertionError('new query database'))
    thread = types.ModuleType('tmdbhelper.lib.addon.thread')

    class Parallel:
        def __init__(self, items, func):
            self.queue = [func(item) for item in items]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    thread.ParallelThread = Parallel
    spec = importlib.util.spec_from_file_location(
        'runtime_ratings', ROOT / 'resources/tmdbhelper/lib/items/database/baseview_factories/concrete_classes/ratings.py')
    result = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {base.__name__: base, queries.__name__: queries, thread.__name__: thread}):
        spec.loader.exec_module(result)
    return result


class RatingsProviderTest(unittest.TestCase):
    def setUp(self):
        self.module = load_ratings()
        self.settings = {}
        self.patcher = mock.patch.object(self.module, 'get_setting', lambda key, *a: self.settings.get(key, False), create=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.ratings = self.module.RatingsDict()
        self.ratings.tmdb_type = 'movie'
        self.ratings.tmdb_id = 42
        self.ratings.common_apis = types.SimpleNamespace(
            query_database=mock.Mock(), tmdb_api=mock.Mock(),
            omdb_api=None, trakt_api=None, mdblist_api=None)
        self.ratings.parent_item_data = {'infolabels': {'rating': 7.4, 'votes': 1234}}

    def test_all_disabled_providers_make_no_calls(self):
        self.assertEqual(self.ratings.online_data_mapped, {})
        self.ratings.common_apis.query_database.assert_not_called()
        self.assertEqual(self.ratings.common_apis.query_database.mock_calls, [])
        self.assertEqual(self.ratings.common_apis.tmdb_api.mock_calls, [])

    def test_each_provider_control_suppresses_only_that_provider(self):
        providers = ('omdb', 'mdblist', 'trakt', 'tmdb', 'top250')
        for enabled in providers:
            with self.subTest(enabled=enabled):
                ratings = self.module.RatingsDict()
                ratings.tmdb_type = 'movie'
                ratings.tmdb_id = 42
                ratings.common_apis = self.ratings.common_apis
                self.settings = {f'ratings_{provider}': provider == enabled for provider in providers}
                attrs = ('omdb_ratings', 'mdblist_ratings', 'trakt_ratings', 'tmdb_ratings', 'imdb_top250')
                with mock.patch.multiple(self.module.RatingsDict, **{
                        attr: mock.PropertyMock(return_value={provider: 1}) for provider, attr in zip(providers, attrs)}):
                    self.assertEqual(ratings.online_data_mapped, {enabled: 1})

    def test_tmdb_votes_come_from_parent_without_detail_request(self):
        self.assertEqual(self.ratings.tmdb_ratings, {'tmdb_rating': 74, 'tmdb_votes': 1234})
        self.assertEqual(self.ratings.common_apis.tmdb_api.mock_calls, [])

    def test_missing_and_zero_tmdb_votes_do_not_trigger_requests(self):
        for values, expected in (({}, {}), ({'rating': 0, 'votes': 0}, {'tmdb_rating': 0, 'tmdb_votes': 0})):
            self.ratings.__dict__.pop('tmdb_ratings', None)
            self.ratings.parent_item_data = {'infolabels': values}
            self.assertEqual(self.ratings.tmdb_ratings, expected)
        self.assertEqual(self.ratings.common_apis.tmdb_api.mock_calls, [])

    def test_imdb_and_top250_use_shared_query_database(self):
        query = self.ratings.common_apis.query_database
        query.get_trakt_id.return_value = 'tt42'
        query.get_imdb_top250_list_cached.return_value = [42]
        self.assertEqual(self.ratings.get_imdb_id(), 'tt42')
        self.assertEqual(self.ratings.get_imdb_top250_list(), [42])
        self.assertEqual(query.get_trakt_id.call_count, 1)
        self.assertEqual(query.get_imdb_top250_list_cached.call_count, 1)

    def test_cached_ratings_keep_skin_formats(self):
        self.ratings.get_unmapped_data = lambda: [{'id': 'movie.42', 'expiry': 99, 'tmdb_rating': 74, 'tmdb_votes': 1234}]
        self.assertEqual(self.ratings.get_cached_data(), {
            'tmdb_rating': '7.4', 'tmdb_votes': 1234, 'comma_tmdb_votes': '1,234',
            'percent_tmdb_rating': 74, 'decimal_tmdb_rating': '7.4', 'starred_tmdb_rating': '3.7'})


class MDbListGateTest(unittest.TestCase):
    def test_unconfigured_mdblist_never_imports_provider(self):
        from tmdbhelper.lib.api.contains import CommonContainerAPIs
        with mock.patch('tmdbhelper.lib.addon.plugin.get_setting', return_value=''):
            self.assertIsNone(CommonContainerAPIs().mdblist_api)

    def test_monitor_shares_apis_without_preloading_disabled_providers(self):
        from tmdbhelper.lib.monitor.common import CommonMonitorDetails
        monitor = CommonMonitorDetails()
        calls = []

        class Ratings:
            data = {'tmdb_rating': '7.4'}

            def __init__(self, common_apis=None):
                calls.append(common_apis)

        ratings = types.ModuleType('tmdbhelper.lib.items.database.baseview_factories.concrete_classes.ratings')
        ratings.RatingsDict = Ratings
        with mock.patch.dict(sys.modules, {ratings.__name__: ratings}):
            self.assertEqual(monitor.get_detailed_ratings('movie', 42), {'tmdb_rating': '7.4'})
        self.assertEqual(calls, [monitor])
        self.assertNotIn('query_database', monitor.__dict__)
        self.assertNotIn('mdblist_api', monitor.__dict__)


class RatingsSettingsTest(unittest.TestCase):
    def test_all_provider_controls_exist_and_mdblist_defaults_off(self):
        root = ET.parse(ROOT / 'resources/settings.xml').getroot()
        for provider in ('omdb', 'mdblist', 'trakt', 'tmdb', 'top250'):
            setting = root.find(f'.//setting[@id="ratings_{provider}"]')
            self.assertIsNotNone(setting)
            self.assertEqual(setting.get('type'), 'boolean')
            self.assertEqual(setting.findtext('default').lower(), 'false' if provider == 'mdblist' else 'true')
            self.assertTrue(setting.get('help'))

    def test_dead_provider_setting_is_absent(self):
        root = ET.parse(ROOT / 'resources/settings.xml').getroot()
        self.assertIsNone(root.find('.//setting[@id="default_player_provider"]'))


if __name__ == '__main__':
    unittest.main()
