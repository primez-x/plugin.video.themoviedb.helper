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


class TestPlayerMonitor(unittest.TestCase):
    def test_av_started_after_playback_ended_resets_properties(self):
        monitor = StoppedPlayerMonitor()
        monitor.onAVStarted()
        self.assertEqual(monitor.resets, 1)


if __name__ == '__main__':
    unittest.main()
