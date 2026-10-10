import unittest

import kodistubs

kodistubs.install()

from tmdbhelper.lib.monitor.common import CommonMonitorFunctions  # noqa: E402
from tmdbhelper.lib.script.method.maintenance import DatabaseMaintenance  # noqa: E402
from tmdbhelper.lib.query.database.trakt_stats import GetTraktStatsRequest  # noqa: E402


class UnchangedPropertyTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()
        self.monitor = CommonMonitorFunctions()

    def set_calls(self):
        return [i for i in kodistubs.SET_PROPERTY_CALLS if i[1] == 'TMDbHelper.ListItem.title']

    def test_unchanged_value_is_not_set_again(self):
        self.monitor.set_property('title', 'Alien')
        self.monitor.set_property('title', 'Alien')
        self.assertEqual(len(self.set_calls()), 1)
        self.monitor.set_property('title', 'Aliens')
        self.assertEqual(len(self.set_calls()), 2)
        self.assertEqual(kodistubs.WINDOW_PROPERTIES[10000]['tmdbhelper.listitem.title'], 'Aliens')

    def test_value_is_set_again_after_clear(self):
        self.monitor.set_property('title', 'Alien')
        self.monitor.clear_property('title')
        self.monitor.set_property('title', 'Alien')
        self.assertEqual(len(self.set_calls()), 2)
        self.monitor.set_property('title', None)
        self.assertNotIn('tmdbhelper.listitem.title', kodistubs.WINDOW_PROPERTIES[10000])
        self.monitor.set_property('title', 'Alien')
        self.assertEqual(len(self.set_calls()), 3)

    def test_item_change_keeps_shared_values_and_clears_old(self):
        self.monitor.set_properties({'infolabels': {'title': 'Alien', 'mpaa': 'R'}})
        self.monitor.set_properties({'infolabels': {'title': 'Aliens'}})
        props = kodistubs.WINDOW_PROPERTIES[10000]
        self.assertEqual(props['tmdbhelper.listitem.title'], 'Aliens')
        self.assertNotIn('tmdbhelper.listitem.mpaa', props)
        self.monitor.set_properties({'infolabels': {'title': 'Aliens', 'mpaa': 'R'}})
        self.assertEqual(props['tmdbhelper.listitem.mpaa'], 'R')

    def test_clear_properties_forgets_values(self):
        self.monitor.set_properties({'infolabels': {'title': 'Alien'}})
        self.monitor.clear_properties()
        self.monitor.set_properties({'infolabels': {'title': 'Alien'}})
        self.assertEqual(len(self.set_calls()), 2)
        self.assertEqual(kodistubs.WINDOW_PROPERTIES[10000]['tmdbhelper.listitem.title'], 'Alien')


class VacuumGatingTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()
        self.maintenance = DatabaseMaintenance()

    def test_vacuum_postponed_until_idle(self):
        self.assertFalse(self.maintenance.is_vacuum_allowed)
        self.assertEqual(self.maintenance.next_vacuum, 0)  # Not rescheduled so next cron poll checks again
        kodistubs.CONDITIONS[DatabaseMaintenance.vacuum_idle_condition] = True
        self.assertTrue(self.maintenance.is_vacuum_allowed)

    def test_vacuum_still_waits_for_interval(self):
        kodistubs.CONDITIONS[DatabaseMaintenance.vacuum_idle_condition] = True
        self.maintenance.set_next_vacuum()
        self.assertFalse(self.maintenance.is_vacuum_allowed)


class FakeTraktAPI:
    def __init__(self, response_json):
        self.response_json = response_json

    def get_response_json(self, *args, **kwargs):
        return self.response_json


class TraktStatsGuardTest(unittest.TestCase):
    def stats(self, response_json):
        return GetTraktStatsRequest(FakeTraktAPI(response_json))

    def test_valid_response(self):
        sync = self.stats({'movies': {'plays': 3, 'watched': 2, 'ratings': {'total': 1}}, 'network': {'friends': 1}})
        self.assertEqual(sorted(sync.values), [('friends', 'network', 1), ('plays', 'movies', 3), ('watched', 'movies', 2)])

    def test_odd_responses_do_not_raise(self):
        for response_json in ([], [{'movies': {}}], {}, None, 'error', {'movies': [1, 2]}, {'movies': None, 'shows': 4}):
            self.assertEqual(self.stats(response_json).values, [])


if __name__ == '__main__':
    unittest.main()
