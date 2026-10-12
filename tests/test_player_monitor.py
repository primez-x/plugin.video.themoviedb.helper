import unittest

import kodistubs

kodistubs.install()

from tmdbhelper.lib.monitor.player import PlayerMonitor  # noqa: E402


class StoppedPlayerMonitor(PlayerMonitor):
    """ Playback has already ended when the callback runs """
    def __init__(self):
        self.resets = 0

    def getPlayingFile(self):
        raise RuntimeError('Kodi is not playing any file')

    def reset_properties(self):
        self.resets += 1


class EndsAfterPlayingFileMonitor(StoppedPlayerMonitor):
    """ Playback ends after getPlayingFile() but before the item info is read """
    def getPlayingFile(self):
        return 'plugin://plugin.video.example/movie.mp4'

    def reset_player_item(self):
        raise RuntimeError('Kodi is not playing any file')


class TestPlayerMonitor(unittest.TestCase):
    def test_av_started_after_playback_ended_resets_properties(self):
        monitor = StoppedPlayerMonitor()
        monitor.onAVStarted()
        self.assertEqual(monitor.resets, 1)

    def test_playback_ending_while_reading_the_item_resets_properties(self):
        monitor = EndsAfterPlayingFileMonitor()
        monitor.onAVChange()
        self.assertEqual(monitor.resets, 1)


if __name__ == '__main__':
    unittest.main()
