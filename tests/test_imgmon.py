import threading
import unittest

import kodistubs

kodistubs.install()

from tmdbhelper.lib.monitor.imgmon import ImagesMonitor  # noqa: E402


class Parent:
    def __init__(self):
        self.update_monitor = kodistubs.sys.modules['xbmc'].Monitor()
        self.mutex_lock = threading.Lock()


class FakeImagesMonitor(ImagesMonitor):
    """ ImagesMonitor with Kodi lookups replaced by test data """
    processed = None

    def setup_current_container(self):
        self.container_item = 'ListItem.'

    def get_cur_info(self):
        return 'label'

    def get_image_manipulations(self, **kwargs):
        self.processed.append(kodistubs.INFOLABELS.get('identifier'))
        images = {'blurimage': f'blur-{kodistubs.INFOLABELS.get("identifier")}', 'blurimage.original': 'fanart.jpg'}
        kwargs['on_output'](images)
        return images

    @property
    def baseitem_properties(self):
        return {}


def make_monitor():
    monitor = FakeImagesMonitor(Parent())
    monitor.processed = []
    monitor.pre_window = kodistubs.CURRENT_WINDOW[0]  # Running monitor has already seen the window
    return monitor


def tick(monitor, identifier):
    kodistubs.INFOLABELS['identifier'] = identifier
    monitor.update_artwork()


class SettleDelayTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()

    def test_item_processed_only_after_unchanged_for_two_ticks(self):
        monitor = make_monitor()
        tick(monitor, 'a')
        tick(monitor, 'a')
        self.assertEqual(monitor.processed, [])
        tick(monitor, 'a')
        self.assertEqual(monitor.processed, ['a'])
        tick(monitor, 'a')
        self.assertEqual(monitor.processed, ['a'])  # Not reprocessed while idle on same item

    def test_moving_items_are_never_processed(self):
        monitor = make_monitor()
        for identifier in ('a', 'b', 'c', 'd', 'e'):
            tick(monitor, identifier)
        self.assertEqual(monitor.processed, [])
        tick(monitor, 'e')
        tick(monitor, 'e')
        self.assertEqual(monitor.processed, ['e'])

    def test_no_processing_on_scroll(self):
        monitor = make_monitor()
        self.assertFalse(monitor._allow_on_scroll)
        called = []
        monitor.on_listitem = lambda: called.append(True)
        monitor._on_scroll()
        self.assertEqual(called, [])

    def test_stale_item_does_not_set_properties(self):
        monitor = make_monitor()
        tick(monitor, 'a')
        tick(monitor, 'a')

        def get_image_manipulations(**kwargs):
            kodistubs.INFOLABELS['identifier'] = 'b'  # Item changes while processing
            images = {'blurimage': 'blur-a', 'blurimage.original': 'fanart.jpg'}
            kwargs['on_output'](images)
            return images

        monitor.get_image_manipulations = get_image_manipulations
        kodistubs.INFOLABELS['identifier'] = 'a'
        monitor.update_artwork()
        self.assertNotIn('tmdbhelper.listitem.blurimage', kodistubs.WINDOW_PROPERTIES.get(10000, {}))

    def test_image_property_set_as_soon_as_ready(self):
        monitor = make_monitor()
        seen = []

        def get_image_manipulations(**kwargs):
            images = {'blurimage': 'blur-a', 'blurimage.original': 'fanart.jpg'}
            kwargs['on_output'](images)
            seen.append(kodistubs.WINDOW_PROPERTIES[10000].get('tmdbhelper.listitem.blurimage'))
            return images

        monitor.get_image_manipulations = get_image_manipulations
        for _ in range(3):
            tick(monitor, 'a')
        self.assertEqual(seen, ['blur-a'])

    def test_forced_update_marks_item_seen(self):
        monitor = make_monitor()
        kodistubs.INFOLABELS['identifier'] = 'a'
        monitor.update_artwork(forced=True)
        self.assertEqual(monitor.processed, ['a'])
        for _ in range(3):
            tick(monitor, 'a')
        self.assertEqual(monitor.processed, ['a'])  # Image thread does not redo forced item


class IdleRefreshTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()

    def idle_refresh(self, monitor):
        monitor._next_refresh = 1  # Expired timestamp
        tick(monitor, 'a')

    def settled_monitor(self):
        monitor = make_monitor()
        for _ in range(4):
            tick(monitor, 'a')
        self.assertEqual(monitor.processed, ['a'])
        return monitor

    def test_idle_refresh_skips_images_without_rotation(self):
        monitor = self.settled_monitor()
        self.idle_refresh(monitor)
        self.assertEqual(monitor.processed, ['a'])

    def test_idle_refresh_redoes_images_for_rotating_source(self):
        kodistubs.WINDOW_PROPERTIES[10000] = {'tmdbhelper.blur.sourceimage': 'Art(fanart{x})'}
        monitor = self.settled_monitor()
        self.idle_refresh(monitor)
        self.idle_refresh(monitor)
        self.assertEqual(monitor.processed, ['a', 'a', 'a'])

    def test_idle_refresh_retries_missing_image_once(self):
        monitor = self.settled_monitor()
        monitor.cur_blurcrop_properties = {'blurimage': '', 'blurimage.original': ''}
        self.idle_refresh(monitor)
        monitor.cur_blurcrop_properties = {'blurimage': '', 'blurimage.original': ''}
        self.idle_refresh(monitor)
        self.assertEqual(monitor.processed, ['a', 'a'])



class FinaliserLockTest(unittest.TestCase):
    def test_forced_artwork_update_holds_service_lock(self):
        from tmdbhelper.lib.monitor.listitemfinaliser import ListItemMonitorFinaliserWindowMethod

        lock = threading.Lock()
        held = []

        class Item:
            is_same_item = True

        class Images:
            def update_artwork(self, forced=False):
                held.append((forced, lock.locked()))
                return {}

        class Service:
            mutex_lock = lock
            images_monitor = Images()

        class Functions:
            service_monitor = Service()

        finaliser = ListItemMonitorFinaliserWindowMethod(Functions())
        finaliser.item = Item()
        finaliser.artwork()
        self.assertEqual(held, [(True, True)])
        self.assertFalse(lock.locked())


if __name__ == '__main__':
    unittest.main()
