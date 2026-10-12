import threading
import unittest
from unittest import mock

import kodistubs

kodistubs.install()

from tmdbhelper.lib.monitor import images  # noqa: E402
from tmdbhelper.lib.script.method import image_functions  # noqa: E402


class TestImageFunctionsScript(unittest.TestCase):
    """ RunScript(...,blur_image=...) must finish its work before the script returns """
    def test_blur_and_colors_run_in_the_script_thread(self):
        ran = []

        def run(self):
            ran.append((self.save_prop, threading.current_thread() is threading.main_thread()))

        before = threading.active_count()
        with mock.patch.object(images.ImageFunctions, 'run', run):
            image_functions.blur_image(blur_image='fanart.jpg', prefix='ListItem')
            image_functions.image_colors(image_colors='fanart.jpg', prefix='ListItem')

        self.assertEqual(ran, [('ListItem.BlurImage', True), ('ListItem.Colors', True)])
        self.assertEqual(threading.active_count(), before)


if __name__ == '__main__':
    unittest.main()
