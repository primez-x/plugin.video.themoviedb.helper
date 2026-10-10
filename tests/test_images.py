import io
import os
import unittest

import kodistubs

kodistubs.install()

from tmdbhelper.lib.monitor import images  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None


ORIGINAL = 'https://image.tmdb.org/t/p/original/abc123.jpg'


class BlurSourceUrlTest(unittest.TestCase):
    def test_original_is_downloaded_as_w780(self):
        self.assertEqual(images.get_blur_download_url(ORIGINAL), 'https://image.tmdb.org/t/p/w780/abc123.jpg')

    def test_larger_width_is_downloaded_as_w780(self):
        self.assertEqual(
            images.get_blur_download_url('https://image.tmdb.org/t/p/w1280/abc123.jpg'),
            'https://image.tmdb.org/t/p/w780/abc123.jpg')

    def test_smaller_or_equal_width_is_kept(self):
        for size in ('w300', 'w500', 'w780'):
            self.assertIsNone(images.get_blur_download_url(f'https://image.tmdb.org/t/p/{size}/abc123.jpg'))

    def test_non_tmdb_and_filtered_urls_are_kept(self):
        for url in (
                'https://assets.fanart.tv/fanart/movies/1/moviebackground/x.jpg',
                'https://image.tmdb.org/t/p/h100_filter(negate,000,666)/abc123.png',
                'special://skin/media/fanart.jpg', '', None):
            self.assertIsNone(images.get_blur_download_url(url))

    def test_large_blur_size_keeps_original(self):
        self.assertIsNone(images.get_blur_download_url(ORIGINAL, blur_size=1280))


@unittest.skipIf(Image is None, 'Pillow not installed')
class BlurOutputTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()
        source = Image.new('RGB', (1280, 720), (200, 40, 40))
        buffer = io.BytesIO()
        source.save(buffer, 'JPEG')
        kodistubs.URLS['https://image.tmdb.org/t/p/w780/abc123.jpg'] = buffer.getvalue()
        self.imgfunc = images.ImageFunctions(method='blur', is_thread=False, artwork=ORIGINAL)

    def tearDown(self):
        for f in os.listdir(self.imgfunc.save_path):
            os.remove(os.path.join(self.imgfunc.save_path, f))

    def test_blur_outputs(self):
        destination = self.imgfunc.blur(ORIGINAL)

        # Cache key stays on original url so existing cached blurs remain valid
        self.assertEqual(os.path.basename(destination), f'{images.md5hash(ORIGINAL)}-{self.imgfunc.radius}-{self.imgfunc.blur_size}.jpg')

        # Only the smaller rendition is read and read directly without temp file copy
        self.assertIn('https://image.tmdb.org/t/p/w780/abc123.jpg', kodistubs.READS)
        self.assertNotIn(ORIGINAL, kodistubs.READS)
        self.assertEqual(kodistubs.COPIES, [])
        self.assertFalse([f for f in os.listdir(self.imgfunc.save_path) if f.startswith('temp_')])

        with Image.open(destination) as img:
            self.assertEqual(img.format, 'JPEG')
            self.assertEqual(max(img.size), self.imgfunc.blur_size)
        with Image.open(f'{destination}-tiled.jpg') as img:
            self.assertEqual(img.format, 'JPEG')
        with Image.open(f'{destination}-diffuse-{self.imgfunc.corner}.jpg') as img:
            self.assertEqual(img.format, 'PNG')
            self.assertEqual(img.mode, 'RGBA')

    def test_missing_rendition_falls_back_to_original(self):
        kodistubs.URLS[ORIGINAL] = kodistubs.URLS.pop('https://image.tmdb.org/t/p/w780/abc123.jpg')
        destination = self.imgfunc.blur(ORIGINAL)
        self.assertTrue(destination)
        self.assertEqual(kodistubs.READS[-2:], ['https://image.tmdb.org/t/p/w780/abc123.jpg', ORIGINAL])
        self.assertEqual(kodistubs.COPIES, [])

    def test_empty_direct_read_falls_back_to_temp_copy(self):
        kodistubs.URLS[ORIGINAL] = kodistubs.URLS['https://image.tmdb.org/t/p/w780/abc123.jpg']
        original_read = images._imageread
        images._imageread = lambda image: bytearray()
        try:
            destination = self.imgfunc.blur(ORIGINAL)
        finally:
            images._imageread = original_read
        self.assertTrue(destination)
        self.assertEqual(kodistubs.COPIES[0][0], ORIGINAL)
        self.assertFalse([f for f in os.listdir(self.imgfunc.save_path) if f.startswith('temp_')])


class ImageManipulationsOrderTest(unittest.TestCase):
    def setUp(self):
        kodistubs.reset()
        kodistubs.CONDITIONS['Skin.HasSetting(TMDbHelper.EnableBlur)'] = True
        kodistubs.CONDITIONS['Skin.HasSetting(TMDbHelper.EnableCrop)'] = True
        self.calls = []
        self.original_funcs = images.ImageFunctions.blur, images.ImageFunctions.crop

        def blur(imgfunc, source):
            self.calls.append('blur')
            return 'blurred.jpg'

        def crop(imgfunc, source):
            self.calls.append('crop')
            return 'cropped.png'

        images.ImageFunctions.blur, images.ImageFunctions.crop = blur, crop

    def tearDown(self):
        images.ImageFunctions.blur, images.ImageFunctions.crop = self.original_funcs

    def test_blur_runs_first_and_each_output_is_reported(self):
        outputs = []
        manipulations = images.ImageManipulations()
        manipulations.get_artwork = lambda **kwargs: 'image.jpg'
        result = manipulations.get_image_manipulations(allow_list=('crop', 'blur'), on_output=outputs.append)
        self.assertEqual(self.calls, ['blur', 'crop'])
        self.assertEqual(outputs[0], {'blurimage': 'blurred.jpg', 'blurimage.original': 'image.jpg'})
        self.assertEqual(outputs[1], {'cropimage': 'cropped.png', 'cropimage.original': 'image.jpg'})
        self.assertEqual(result['blurimage'], 'blurred.jpg')

    def test_stale_item_stops_before_crop(self):
        outputs = []
        current = iter((True, False))  # Current before blur then item changes during blur
        manipulations = images.ImageManipulations()
        manipulations.get_artwork = lambda **kwargs: 'image.jpg'
        manipulations.get_image_manipulations(
            allow_list=('crop', 'blur'), is_current=lambda: next(current, False), on_output=outputs.append)
        self.assertEqual(self.calls, ['blur'])
        self.assertEqual(outputs, [])  # Stale blur output is not set


if __name__ == '__main__':
    unittest.main()
