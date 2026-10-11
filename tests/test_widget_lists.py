"""
Primez: Widget listing regressions.
- Discover widgets must not send the volatile reload= token to TMDb or into the list cache name.
- TMDb listitems must carry label and title (label, ListItem.Title and the info tag).
"""
import sys
import types
import unittest
from unittest import mock

import kodistubs

kodistubs.install()


class _ListStandardProperties:
    pass


class _ListStandardLocalProperties(_ListStandardProperties):
    pass


class _ListStandard:
    pass


def _discover_modules():
    """ Stand-ins needed only while importing lists_discover """
    lists_standard = types.ModuleType('tmdbhelper.lib.items.directories.tmdb.lists_standard')
    lists_standard.ListStandard = _ListStandard
    lists_standard.ListStandardProperties = _ListStandardProperties
    lists_standard.ListStandardLocalProperties = _ListStandardLocalProperties
    parser = types.ModuleType('jurialmunkey.parser')
    parser.__dict__.update(sys.modules['jurialmunkey.parser'].__dict__)
    parser.split_items = lambda items, separator='/': items.split(f' {separator} ') if isinstance(items, str) else [items]
    tmdate = types.ModuleType('tmdbhelper.lib.addon.tmdate')
    tmdate.__dict__.update(sys.modules['tmdbhelper.lib.addon.tmdate'].__dict__)
    tmdate.get_datetime_now = lambda: None
    tmdate.get_timedelta = lambda **kwargs: None
    return {
        'tmdbhelper.lib.items.directories.tmdb.lists_standard': lists_standard,
        'jurialmunkey.parser': parser,
        'tmdbhelper.lib.addon.tmdate': tmdate,
    }


def _import_discover():
    with mock.patch.dict(sys.modules, _discover_modules()):
        sys.modules.pop('tmdbhelper.lib.items.directories.tmdb.lists_discover', None)
        from tmdbhelper.lib.items.directories.tmdb import lists_discover
        sys.modules.pop('tmdbhelper.lib.items.directories.tmdb.lists_discover', None)
    return lists_discover


class DiscoverReloadParamTest(unittest.TestCase):

    def make_properties(self, **params):
        lists_discover = _import_discover()
        properties = lists_discover.ListDiscoverProperties()
        properties.request_url = 'discover/{tmdb_type}'
        properties.class_name = 'ListDiscover'
        properties.tmdb_type = 'movie'
        properties.page = 1
        properties.pmax = 1
        properties.discover_params = params
        return properties

    def test_reload_not_sent_to_tmdb(self):
        properties = self.make_properties(
            info='discover', tmdb_type='movie', widget='true', reload='1760000000',
            sort_by='popularity.desc', with_original_language='en')
        self.assertNotIn('reload', properties.url)
        self.assertIn('sort_by=popularity.desc', properties.url)
        self.assertIn('with_original_language=en', properties.url)

    def test_reload_does_not_change_cache_name(self):
        params = dict(info='discover', tmdb_type='movie', widget='true', sort_by='popularity.desc')
        first = self.make_properties(reload='1760000000', **params)
        second = self.make_properties(reload='1760000999', **params)
        no_reload = self.make_properties(**params)
        self.assertEqual(first.cache_name_tuple, second.cache_name_tuple)
        self.assertEqual(first.cache_name_tuple, no_reload.cache_name_tuple)
        self.assertEqual(first.url, no_reload.url)


class _KodiListItem:
    def __init__(self, label='', label2='', path='', offscreen=False):
        self.label = label
        self.label2 = label2
        self.path = path
        self.art = {}
        self.properties = {}

    def setLabel2(self, label2):
        self.label2 = label2

    def setArt(self, art):
        self.art.update(art)

    def setProperties(self, properties):
        self.properties.update(properties)

    def addContextMenuItems(self, items):
        pass


class _ListItemInfoTag:
    def __init__(self, listitem, *args, **kwargs):
        self.listitem = listitem

    def set_info(self, infolabels):
        self.listitem.info = dict(infolabels)

    def set_unique_ids(self, unique_ids):
        pass

    def set_cast(self, cast):
        pass

    def set_stream_details(self, stream_details):
        pass

    def set_resume_point(self, infoproperties):
        pass


def _listitem_modules():
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.__dict__.update(sys.modules['xbmcgui'].__dict__)
    xbmcgui.ListItem = _KodiListItem
    infotagger = types.ModuleType('infotagger')
    infotagger.__path__ = []
    infotagger_listitem = types.ModuleType('infotagger.listitem')
    infotagger_listitem.ListItemInfoTag = _ListItemInfoTag
    parser = types.ModuleType('jurialmunkey.parser')
    parser.__dict__.update(sys.modules['jurialmunkey.parser'].__dict__)
    parser.boolean = lambda value: str(value).lower() in ('true', '1')

    def merge_two_dicts(x, y, reverse=False, deep=False):
        xx = y or {} if reverse else x or {}
        yy = x or {} if reverse else y or {}
        z = xx.copy()
        z.update(yy)
        return z

    parser.merge_two_dicts = merge_two_dicts

    class GlobalSettingsDict(dict):
        route = {}

    plugin = types.ModuleType('tmdbhelper.lib.addon.plugin')
    plugin.__dict__.update(sys.modules['tmdbhelper.lib.addon.plugin'].__dict__)
    plugin.ADDONPATH = 'special://home/addons/plugin.video.themoviedb.helper'
    plugin.PLUGINPATH = 'plugin://plugin.video.themoviedb.helper/'
    plugin.encode_url = lambda path, **kwargs: path + '?' + '&'.join(f'{k}={v}' for k, v in kwargs.items())
    plugin.get_flatseasons_info_param = lambda: 'seasons'
    plugin.GlobalSettingsDict = GlobalSettingsDict
    tmdate = types.ModuleType('tmdbhelper.lib.addon.tmdate')
    tmdate.__dict__.update(sys.modules['tmdbhelper.lib.addon.tmdate'].__dict__)
    tmdate.is_unaired_timestamp = lambda date_str, no_date=True: False
    return {
        'xbmcgui': xbmcgui,
        'infotagger': infotagger,
        'infotagger.listitem': infotagger_listitem,
        'jurialmunkey.parser': parser,
        'tmdbhelper.lib.addon.plugin': plugin,
        'tmdbhelper.lib.addon.tmdate': tmdate,
    }


class WidgetListItemTitleTest(unittest.TestCase):
    """ Mapped TMDb list items (as produced by TMDb mapper finalise) keep label and title on the Kodi ListItem """

    def setUp(self):
        patcher = mock.patch.dict(sys.modules, _listitem_modules())
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop('tmdbhelper.lib.items.listitem', None)
        self.addCleanup(sys.modules.pop, 'tmdbhelper.lib.items.listitem', None)
        from tmdbhelper.lib.items.listitem import ListItem
        self.ListItem = ListItem

    @staticmethod
    def mapped_item(tmdb_type, title):
        dbtype = 'movie' if tmdb_type == 'movie' else 'tvshow'
        infolabels = {'title': title, 'mediatype': dbtype, 'plot': 'Plot'}
        if tmdb_type == 'tv':
            infolabels['tvshowtitle'] = title
        return {
            'label': title,
            'infolabels': infolabels,
            'infoproperties': {'tmdb_type': tmdb_type, 'dbtype': dbtype},
            'art': {'poster': 'https://image.tmdb.org/t/p/original/poster.jpg'},
            'unique_ids': {'tmdb': 1},
            'params': {'info': 'details', 'tmdb_type': tmdb_type, 'tmdb_id': 1},
        }

    def test_movie_and_tvshow_listitems_have_label_and_title(self):
        for tmdb_type, title in (('movie', 'Dune: Part Two'), ('tv', 'Shogun')):
            with self.subTest(tmdb_type=tmdb_type):
                listitem = self.ListItem(**self.mapped_item(tmdb_type, title)).get_listitem()
                self.assertEqual(listitem.label, title)
                self.assertEqual(listitem.info['title'], title)

    def test_cached_details_without_title_keep_list_title(self):
        li = self.ListItem(**self.mapped_item('movie', 'Dune: Part Two'))
        li.set_details({'label': None, 'infolabels': {'title': None, 'plot': 'Cached plot'}}, override=True, reverse_artwork=True)
        listitem = li.get_listitem()
        self.assertEqual(listitem.label, 'Dune: Part Two')
        self.assertEqual(listitem.info['title'], 'Dune: Part Two')

    def test_cached_details_title_overrides_label(self):
        li = self.ListItem(**self.mapped_item('movie', 'Dune: Part Two'))
        li.set_details({'label': 'Dune : Deuxieme partie', 'infolabels': {'title': 'Dune : Deuxieme partie'}}, override=True)
        listitem = li.get_listitem()
        self.assertEqual(listitem.label, 'Dune : Deuxieme partie')
        self.assertEqual(listitem.info['title'], 'Dune : Deuxieme partie')


if __name__ == '__main__':
    unittest.main()
