"""Missing-metadata contract with real RequestAPI and loopback HTTP responses.

The tests fetch a pinned source for the declared request dependency.
Set TMDBHELPER_REQAPI_SOURCE to use a local reqapi.py source.
Kodi-only dependencies use the existing test doubles. RequestAPI and MemoryCache
remain real. No TMDb credentials or live TMDb service are required.
"""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import tempfile
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

# Load requests before module patches so CookieJar classes keep one identity.
import requests
import kodistubs

kodistubs.install()

ROOT = Path(__file__).resolve().parents[1]
REQUEST_SOURCE = os.environ.get('TMDBHELPER_REQAPI_SOURCE')
REQUEST_SOURCE_URL = 'https://raw.githubusercontent.com/jurialmunkey/script.module.jurialmunkey/8f42fb5f4698f3e4552f38955964b2f3843dba69/resources/modules/jurialmunkey/reqapi.py'
REQUEST_SOURCE_SHA256 = '19351bbe5a5aa7bf9c2f3f893a61ae7effb7ed70afa2d0118d59082e362d0367'
MISSING = {'success': False, 'status_code': 34, 'status_message': 'Resource not found.'}


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module(name, **attrs):
    result = types.ModuleType(name)
    result.__dict__.update(attrs)
    return result


class MissingMetadataHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request_source = REQUEST_SOURCE
        if not cls.request_source:
            folder = tempfile.TemporaryDirectory(prefix='tmdb-request-contract-')
            cls.addClassCleanup(folder.cleanup)
            cls.request_source = Path(folder.name) / 'reqapi.py'
            with urlopen(REQUEST_SOURCE_URL, timeout=20) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != REQUEST_SOURCE_SHA256:
                raise RuntimeError('Request dependency checksum mismatch')
            cls.request_source.write_bytes(content)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.requests.append((self.command, self.path))
                status, body, content_type, delay = self.server.responses.pop(0) if self.server.responses else (404, MISSING, 'application/json', 0)
                if delay:
                    time.sleep(delay)
                payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    pass

            do_POST = do_GET
            do_PUT = do_GET
            do_DELETE = do_GET

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/3'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        kodistubs.reset()
        kodistubs.CONDITIONS['System.InternetState'] = True
        self.server.requests = []
        self.server.responses = []
        self.sessions = []
        self.logs = []
        self.notifications = []
        self.now = int(time.time())

        plugin = module(
            'tmdbhelper.lib.addon.plugin', get_setting=lambda *a, **k: False,
            get_language=lambda: 'en-US', format_name=lambda *a, **k: '')
        logger = module('tmdbhelper.lib.addon.logger', kodi_log=lambda *a: self.logs.append(a))
        dependencies = {
            'jurialmunkey.plugin': module('jurialmunkey.plugin', KodiPlugin=lambda *a: types.SimpleNamespace(get_localized=lambda code: str(code))),
            'jurialmunkey.bcache': module('jurialmunkey.bcache', BasicCache=lambda **k: None),
            'jurialmunkey.tmdate': module('jurialmunkey.tmdate', get_timestamp=kodistubs._get_timestamp, set_timestamp=kodistubs._set_timestamp),
            'tmdbhelper.lib.addon.plugin': plugin,
            'tmdbhelper.lib.addon.logger': logger,
            'tmdbhelper.lib.files.bcache': module('tmdbhelper.lib.files.bcache', BasicCache=lambda **k: None),
            'tmdbhelper.lib.files.futils': module('tmdbhelper.lib.files.futils', json_loads=json.loads),
            'tmdbhelper.lib.api.tmdb.mapping': module('tmdbhelper.lib.api.tmdb.mapping', ItemMapper=object),
            'tmdbhelper.lib.api.api_keys.tmdb': module('tmdbhelper.lib.api.api_keys.tmdb', API_KEY='test-key'),
            'tmdbhelper.lib.files.dbfunc': module('tmdbhelper.lib.files.dbfunc', DatabaseAccess=object),
            'tmdbhelper.lib.api.contains': module('tmdbhelper.lib.api.contains', CommonContainerAPIs=lambda: None),
            'tmdbhelper.lib.items.database.mappings': module('tmdbhelper.lib.items.database.mappings', ItemMapper=object),
            'tmdbhelper.lib.items.database.basemeta_factories.factory': module('tmdbhelper.lib.items.database.basemeta_factories.factory', BaseMetaFactory=object),
            'tmdbhelper.lib.items.database.itemmeta_factories.factory': module('tmdbhelper.lib.items.database.itemmeta_factories.factory', ItemMetaFactory=object),
            'infotagger.listitem': module('infotagger.listitem', _ListItemInfoTagVideo=types.SimpleNamespace(_tag_attr=())),
        }
        self.modules_patch = mock.patch.dict(sys.modules, dependencies)
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        self.dialog_patch = mock.patch('xbmcgui.Dialog', lambda: types.SimpleNamespace(notification=lambda *a: self.notifications.append(a)), create=True)
        self.dialog_patch.start()
        self.addCleanup(self.dialog_patch.stop)
        reqapi = load_source('runtime_reqapi', self.request_source)
        sys.modules['jurialmunkey.reqapi'] = reqapi
        self.parent_patch = mock.patch('jurialmunkey.reqapi', reqapi, create=True)
        self.parent_patch.start()
        self.addCleanup(self.parent_patch.stop)
        request = load_source('runtime_request', ROOT / 'resources/tmdbhelper/lib/api/request.py')
        sys.modules['tmdbhelper.lib.api.request'] = request
        self.memory = load_source('runtime_mcache', ROOT / 'resources/tmdbhelper/lib/files/mcache.py')
        sys.modules['tmdbhelper.lib.files.mcache'] = self.memory
        self.clock_patch = mock.patch.object(self.memory, 'set_timestamp', lambda delay=0, set_int=False: self.now + delay)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.api_module = load_source('runtime_tmdb_api', ROOT / 'resources/tmdbhelper/lib/api/tmdb/api.py')
        self.api_module.TMDbAPI.api_url = self.url
        sys.modules['tmdbhelper.lib.items.database.basedata'] = load_source('runtime_basedata', ROOT / 'resources/tmdbhelper/lib/items/database/basedata.py')
        tmdate = sys.modules['tmdbhelper.lib.addon.tmdate']
        self.date_patch = mock.patch.multiple(tmdate, convert_timestamp=lambda *a, **k: None, get_days_to_air=lambda *a: None, create=True)
        self.date_patch.start()
        self.addCleanup(self.date_patch.stop)
        self.baseitem = load_source('runtime_baseitem', ROOT / 'resources/tmdbhelper/lib/items/database/baseitem_factories/concrete_classes/baseclass.py').BaseItem

    def tearDown(self):
        for session in self.sessions:
            session.close()

    def api(self, language='en-US', api_key='test-key', url=None):
        api = self.api_module.TMDbAPI(language=language, api_key=api_key)
        if url:
            api.req_api_url = url
        self.sessions.append(api.session)
        return api

    def response(self, status=404, body=None, content_type='application/json', delay=0):
        self.server.responses.append((status, MISSING if body is None else body, content_type, delay))

    def memo_properties(self):
        return {key: value for key, value in kodistubs.WINDOW_PROPERTIES.get(10000, {}).items() if '.memcache.' in key}

    def test_connection_notification_setting_changes_after_api_creation(self):
        api = self.api()
        settings = {'enabled': False}
        request = sys.modules['tmdbhelper.lib.api.request']
        with mock.patch.object(request, 'get_setting', lambda *a, **k: settings['enabled']):
            api.do_error_notification('log', 'head', 'body')
            settings['enabled'] = True
            api.do_error_notification('log', 'head', 'body')
            settings['enabled'] = False
            api.do_error_notification('log', 'head', 'body')
        self.assertEqual(self.notifications, [('head', 'body')])

    def test_provider_notification_suppression_survives_global_enable(self):
        request = sys.modules['tmdbhelper.lib.api.request']

        class API(request.RequestAPI):
            _basiccache = staticmethod(lambda **kwargs: None)

        with mock.patch.object(request, 'get_setting', return_value=True):
            api = API(error_notification=False)
            api.do_error_notification('log', 'head', 'body')
            api = API()
            api._error_notification = False
            api.do_error_notification('log', 'head', 'body')
        self.assertEqual(self.notifications, [])

    def test_confirmed_missing_reuses_global_memo_until_five_minute_expiry(self):
        for code in (6, 34):
            with self.subTest(code=code):
                self.server.responses.clear()
                api = self.api()
                self.response(body=dict(MISSING, status_code=code))
                self.response(body=dict(MISSING, status_code=code))
                self.assertEqual(api.get_response_json('movie', code), {})
                count = len(self.server.requests)
                self.assertEqual(api.get_response_json('movie', code), {})
                self.assertEqual(self.api().get_response_json('movie', code), {})
                self.now += 299
                self.assertEqual(api.get_response_json('movie', code), {})
                self.assertEqual(len(self.server.requests), count)
                self.now += 1
                self.assertEqual(api.get_response_json('movie', code), {})
                self.assertEqual(len(self.server.requests), count + 1)

    def test_force_bypasses_memo_and_success_clears_previous_missing(self):
        api = self.api()
        self.response()
        self.response(200, {'id': 12, 'title': 'Recovered'})
        self.response(200, {'id': 12, 'title': 'Current'})
        self.assertEqual(api.get_response_json('movie', 12), {})
        self.assertEqual(api.get_response_json('movie', 12, cache_refresh=True), {'id': 12, 'title': 'Recovered'})
        self.assertEqual(api.get_response_json('movie', 12), {'id': 12, 'title': 'Current'})
        self.assertEqual(len(self.server.requests), 3)
        self.assertTrue(all('cache_refresh' not in parse_qs(urlsplit(path).query) for _, path in self.server.requests))

    def test_positive_responses_remain_uncached_and_closed(self):
        api = self.api()
        self.response(200, {'id': 12, 'title': 'First'})
        self.response(200, {'id': 12, 'title': 'Second'})
        closed = []
        original_close = requests.Response.close

        def close(response):
            closed.append(response.status_code)
            original_close(response)

        with mock.patch.object(requests.Response, 'close', close):
            self.assertEqual(api.get_response_json('movie', 12)['title'], 'First')
            self.assertEqual(api.get_response_json('movie', 12)['title'], 'Second')
        self.assertEqual(closed, [200, 200])
        self.assertFalse(self.memo_properties())

    def test_unconfirmed_failures_do_not_create_a_missing_memo(self):
        cases = [
            (404, '<html>Missing</html>', 'text/html'),
            (404, '{broken', 'application/json'),
            (404, [], 'application/json'),
            (404, {'status_code': 37, 'success': False}, 'application/json'),
            (404, {'status_code': '34', 'success': False}, 'application/json'),
            (404, {'status_code': 34.0, 'success': False}, 'application/json'),
            (404, {'status_code': 34, 'success': True}, 'application/json'),
            (404, {'status_code': 34, 'success': 'false'}, 'application/json'),
            (404, 'null', 'application/json'),
            (404, {}, 'application/json'),
            (401, MISSING, 'application/json'),
            (403, MISSING, 'application/json'),
            (429, MISSING, 'application/json'),
            (500, MISSING, 'application/json'),
            (502, MISSING, 'application/json'),
            (503, MISSING, 'application/json'),
        ]
        for index, (status, body, content_type) in enumerate(cases):
            with self.subTest(status=status, body=body):
                self.server.responses.clear()
                kodistubs.reset()
                api = self.api()
                self.response(status, body, content_type)
                self.response(200, {'id': index})
                self.assertEqual(api.get_response_json('movie', index + 1), {})
                self.assertFalse(self.memo_properties())
                count = len(self.server.requests)
                if status in (429, 500, 503):
                    self.assertEqual(api.get_response_json('movie', index + 1), {})
                    self.assertEqual(len(self.server.requests), count)
                    api.req_connect_err = 0
                    api.req_500_err.clear()
                self.assertEqual(api.get_response_json('movie', index + 1), {'id': index})
                self.assertEqual(len(self.server.requests), count + 1)

    def test_timeout_has_no_missing_memo_and_parent_timeout_state_remains(self):
        api = self.api()
        api.timeout = 0.02
        self.response(delay=0.15)
        self.response(200, {'id': 12})
        self.assertEqual(api.get_response_json('movie', 12), {})
        self.assertFalse(self.memo_properties())
        self.assertGreater(api.req_timeout_err, time.time())
        self.assertEqual(api.get_response_json('movie', 12), {'id': 12})

    def test_metadata_route_boundary(self):
        allowed = [
            'movie/12', 'tv/12', 'person/12', 'collection/12',
            'tv/12/season/0', 'tv/12/season/2/episode/1',
            'movie/12/images', 'tv/12/season/0/translations',
            'tv/12/season/2/episode/1/external_ids', 'tv/12/watch/providers',
        ]
        excluded = [
            'movie/popular', 'movie/12/account_states', 'movie/12/rating',
            'movie/12/lists', 'movie/12/recommendations', 'tv/12/season',
            'tv/12/season/2/episode', 'tv/12/season/2/account_states',
            'person/12/unknown', 'movie/12/images/extra', 'collection/12/rating',
            'search/movie', 'list/12', 'account/12', 'authentication/session/new',
            'movie/../12', 'movie/12/', 'movie/12%2Faccount_states',
        ]
        for path in allowed + excluded:
            with self.subTest(path=path):
                self.server.responses.clear()
                kodistubs.reset()
                api = self.api()
                self.response()
                self.response()
                count = len(self.server.requests)
                self.assertEqual(api.get_response_json(path), {})
                self.assertEqual(api.get_response_json(path), {})
                self.assertEqual(len(self.server.requests) - count, 1 if path in allowed else 2)
                self.server.responses.clear()

    def test_mutations_and_authorised_requests_ignore_memo(self):
        api = self.api()
        self.response()
        api.get_response_json('movie', 12)
        for kwargs in (
                {'method': 'post'}, {'method': 'json', 'postdata': {'rating': 8}},
                {'method': 'put'}, {'method': 'delete'},
                {'postdata': {'rating': 8}}, {'headers': {'Authorization': 'Bearer test-token'}},
                {'session_id': 'test-session'}, {'guest_session_id': 'test-guest'}, {'session_id': ''}):
            with self.subTest(kwargs=kwargs):
                self.response()
                self.response()
                count = len(self.server.requests)
                self.assertEqual(api.get_response_json('movie', 12, **kwargs), {})
                self.assertEqual(api.get_response_json('movie', 12, **kwargs), {})
                self.assertEqual(len(self.server.requests), count + 2)

    def test_lower_hook_never_suppresses_direct_requests(self):
        api = self.api()
        self.response()
        api.get_response_json('movie', 12)
        self.response(200, {'id': 12})
        url = api.get_request_url('movie', 12, language='en-US')
        self.assertEqual(api.get_api_request_json(url), {'id': 12})
        self.response(200, {'id': 12})
        self.assertEqual(api.get_response_json('movie', 12), {'id': 12})
        self.assertEqual(len(self.server.requests), 3)

    def test_url_identity_and_secret_free_properties(self):
        variants = [
            (self.api(), ('movie', 12), {}),
            (self.api(language='fr-FR'), ('movie', 12), {}),
            (self.api(api_key='second-secret'), ('movie', 12), {}),
            (self.api(), ('movie', 13), {}),
            (self.api(), ('person', 12), {}),
            (self.api(), ('movie', 12), {'append_to_response': 'images'}),
            (self.api(url=self.url.replace('127.0.0.1', 'localhost')), ('movie', 12), {}),
        ]
        for api, args, kwargs in variants:
            self.response()
            api.get_response_json(*args, **kwargs)
        self.assertEqual(len(self.server.requests), len(variants))
        for api, args, kwargs in variants:
            self.assertEqual(api.get_response_json(*args, **kwargs), {})
        self.assertEqual(len(self.server.requests), len(variants))
        stored = json.dumps(self.memo_properties())
        for secret in ('test-key', 'second-secret', 'api_key=', self.url, 'status_message'):
            self.assertNotIn(secret, stored)

    def test_baseitem_force_refresh_reaches_api_and_positive_database_data_remains(self):
        api = self.api()
        api.get_append_to_response = lambda **kwargs: 'images'
        database = sqlite3.connect(':memory:')
        self.addCleanup(database.close)
        database.execute('CREATE TABLE cached (payload TEXT)')

        class Item(self.baseitem):
            tmdb_type = 'movie'
            tmdb_id = 12

            def get_cached_data(self):
                row = database.execute('SELECT payload FROM cached').fetchone()
                return json.loads(row[0]) if row else None

            def try_cached_data(self, return_data=False):
                return self.online_data

        common = types.SimpleNamespace(tmdb_api=api)
        self.response()
        self.assertEqual(Item(common).get_data(), {})
        self.assertEqual(Item(common).get_data(), {})
        self.assertEqual(len(self.server.requests), 1)
        self.response(200, {'id': 12, 'title': 'Recovered'})
        forced = Item(common)
        forced.cache_refresh = 'force'
        self.assertEqual(forced.get_data(), {'id': 12, 'title': 'Recovered'})
        self.assertEqual(len(self.server.requests), 2)
        database.execute('INSERT INTO cached VALUES (?)', (json.dumps({'id': 12, 'title': 'Database'}),))
        self.assertEqual(Item(common).get_data(), {'id': 12, 'title': 'Database'})
        self.assertEqual(len(self.server.requests), 2)
        for mode in (None, 'basic', 'never'):
            item = Item(common)
            item.cache_refresh = mode
            self.assertFalse(item.online_data_kwgs.get('cache_refresh'))


if __name__ == '__main__':
    unittest.main()
