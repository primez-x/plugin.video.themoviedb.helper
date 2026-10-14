from tmdbhelper.lib.addon.plugin import get_language, get_setting
from tmdbhelper.lib.api.request import NoCacheRequestAPI
from tmdbhelper.lib.api.tmdb.mapping import ItemMapper
from tmdbhelper.lib.api.api_keys.tmdb import API_KEY
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.files.mcache import MemoryCache
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit


API_URL = 'https://api.themoviedb.org/3' if not get_setting('use_alternate_api_url') else 'https://api.tmdb.org/3'


class TMDbAPI(NoCacheRequestAPI):

    api_key = API_KEY
    api_url = API_URL
    api_name = 'TMDbAPI'

    def __init__(
            self,
            api_key=None,
            language=get_language()):
        api_key = api_key or self.api_key
        api_url = self.api_url
        api_name = self.api_name

        super(TMDbAPI, self).__init__(
            req_api_name=api_name,
            req_api_url=api_url,
            req_api_key=f'api_key={api_key}')
        self.language = language
        TMDb.api_key = api_key

    @property
    def req_language(self):
        return f'{self.iso_language}-{self.iso_country}'

    @property
    def iso_language(self):
        return self.language[:2]

    @property
    def iso_country(self):
        return self.language[-2:]

    @property
    def genres(self):
        return

    @property
    def mapper(self):
        try:
            return self._mapper
        except AttributeError:
            self._mapper = ItemMapper(self.language, self.genres)
            return self._mapper

    @staticmethod
    def get_url_separator(separator=None):
        if separator == 'AND':
            return '%2C'
        elif separator == 'OR':
            return '%7C'
        elif not separator:
            return '%2C'
        else:
            return False

    @staticmethod
    def get_paginated_items(items, limit=None, page=1, total_pages=None):
        from jurialmunkey.parser import try_int
        if total_pages and try_int(page) < try_int(total_pages):
            items.append({'next_page': try_int(page) + 1})
            return items
        if limit is not None:
            from tmdbhelper.lib.items.pages import PaginatedItems
            paginated_items = PaginatedItems(items, page=page, limit=limit)
            return paginated_items.items + paginated_items.next_page
        return items

    def configure_request_kwargs(self, kwargs):
        kwargs['language'] = self.req_language
        return kwargs

    @cached_property
    def missing_metadata_cache(self):
        return MemoryCache('TMDbMissingMetadata')

    def missing_metadata_key(self, request, postdata=None, headers=None, method=None):
        if method not in (None, 'get') or postdata or headers:
            return
        if not request or not request.startswith(f'{self.req_api_url}/'):
            return
        url = urlsplit(request)
        if {'session_id', 'guest_session_id'} & parse_qs(url.query, keep_blank_values=True).keys():
            return
        path = url.path[len(urlsplit(self.req_api_url).path) + 1:].split('/')
        if len(path) < 2 or path[0] not in ('movie', 'tv', 'person', 'collection'):
            return
        if not path[1].isascii() or not path[1].isdigit():
            return
        tmdbtype = path[0]
        path = path[2:]
        if tmdbtype == 'tv' and len(path) >= 2 and path[0] == 'season' and path[1].isascii() and path[1].isdigit():
            tmdbtype, path = 'season', path[2:]
            if len(path) >= 2 and path[0] == 'episode' and path[1].isascii() and path[1].isdigit():
                tmdbtype, path = 'episode', path[2:]
        if path:
            endpoint = TMDb.append_to_response_endpoints.get('/'.join(path))
            if not endpoint or tmdbtype not in endpoint[1]:
                return
        return sha256(request.encode('utf-8')).hexdigest()

    def get_simple_api_request(self, request=None, postdata=None, headers=None, method=None):
        response = super(TMDbAPI, self).get_simple_api_request(request, postdata, headers, method)
        key = self.missing_metadata_key(request, postdata, headers, method)
        if not key or response is None:
            return response
        if response.status_code == 200:
            # Clear both properties without a memo lookup, including after forced requests.
            cache = self.missing_metadata_cache
            for field in ('expr', 'data'):
                cache.del_window_property(f'{cache._sc_name}_{field}_{key}')
        elif response.status_code == 404:
            try:
                data = response.json()
            except ValueError:
                return response
            if not isinstance(data, dict) or type(data.get('status_code')) is not int:
                return response
            if data['status_code'] in (6, 34) and (data.get('success') is None or data.get('success') is False):
                self.missing_metadata_cache.set(key, True, cache_minutes=5)
        return response

    def get_response_json(self, *args, postdata=None, headers=None, method=None, cache_refresh=False, **kwargs):
        kwargs = self.configure_request_kwargs(kwargs)
        requrl = self.get_request_url(*args, **kwargs)
        key = self.missing_metadata_key(requrl, postdata, headers, method)
        if key and not cache_refresh and self.missing_metadata_cache.get(key):
            return {}
        return self.get_api_request_json(requrl, postdata=postdata, headers=headers, method=method)


ATR_STANDARD = 0
ATR_EXTENDED = 1
ATR_LANGUAGE = 2


class TMDb(TMDbAPI):

    append_to_response_endpoints = {
        'images': (ATR_STANDARD, ('person', 'movie', 'tv', 'season', 'episode', 'collection')),
        'release_dates': (ATR_STANDARD, ('person', 'movie', )),
        'external_ids': (ATR_STANDARD, ('person', 'movie', 'tv', 'season', 'episode', )),
        'content_ratings': (ATR_STANDARD, ('tv', )),
        'movie_credits': (ATR_STANDARD, ('person', )),
        'tv_credits': (ATR_STANDARD, ('person', )),
        'credits': (ATR_EXTENDED, ('movie', 'episode', )),
        'keywords': (ATR_EXTENDED, ('movie', 'tv', )),
        'reviews': (ATR_EXTENDED, ('movie', 'tv', )),
        'videos': (ATR_EXTENDED, ('movie', 'tv', 'season', 'episode', )),
        'watch/providers': (ATR_EXTENDED, ('movie', 'tv', 'season', )),
        'aggregate_credits': (ATR_EXTENDED, ('tv', 'season', )),
        'translations': (ATR_LANGUAGE, ('person', 'movie', 'tv', 'season', 'episode', 'collection')),
    }

    def get_append_to_response(self, tmdbtype, extended=False, language=False):
        endpoints = (
            k for k, v in self.append_to_response_endpoints.items()
            if (v[0] == ATR_STANDARD or (extended and v[0] == ATR_EXTENDED) or (language and v[0] == ATR_LANGUAGE))
            and tmdbtype in v[1]
        )
        return ','.join(endpoints)

    api_name = 'TMDb'

    @property
    def tmdb_database(self):
        from tmdbhelper.lib.query.database.database import FindQueriesDatabase
        tmdb_database = FindQueriesDatabase()
        tmdb_database.tmdb_api = self  # Must override attribute to avoid circular import
        return tmdb_database

    @property
    def get_tmdb_id(self):
        return self.tmdb_database.get_tmdb_id

    @cached_property
    def genres(self):
        return self.tmdb_database.genres

    @property
    def iso_region(self):
        if not self.setting_ignore_regionreleasefilter:
            return self.iso_country

    @property
    def setting_ignore_regionreleasefilter(self):
        try:
            return self._setting_ignore_regionreleasefilter
        except AttributeError:
            self._setting_ignore_regionreleasefilter = get_setting('ignore_regionreleasefilter')
            return self._setting_ignore_regionreleasefilter

    @property
    def include_image_language(self):
        return f'{self.iso_language},null,en'

    @property
    def include_video_language(self):
        return f'{self.iso_language},null,en'

    def configure_request_kwargs(self, kwargs):
        kwargs['region'] = self.iso_region
        kwargs['language'] = self.req_language
        kwargs['include_image_language'] = self.include_image_language
        kwargs['include_video_language'] = self.include_video_language
        return kwargs
