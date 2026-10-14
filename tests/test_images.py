import io
import os
import unittest
import json
from unittest import mock

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

    def test_missing_tiled_output_is_regenerated(self):
        destination = self.imgfunc.blur(ORIGINAL)
        tiled = f'{destination}-tiled.jpg'
        os.remove(tiled)
        self.assertTrue(os.path.exists(destination))
        self.assertTrue(os.path.exists(f'{destination}-diffuse-{self.imgfunc.corner}.jpg'))

        self.assertEqual(self.imgfunc.blur(ORIGINAL), destination)
        self.assertTrue(os.path.exists(tiled))

    def test_cached_blur_kept_when_source_unavailable_for_missing_tile(self):
        destination = self.imgfunc.blur(ORIGINAL)
        os.remove(f'{destination}-tiled.jpg')
        kodistubs.URLS.clear()

        self.assertEqual(self.imgfunc.blur(ORIGINAL), destination)

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


@unittest.skipIf(Image is None, 'Pillow not installed')
class DerivativeOutputTest(unittest.TestCase):
    """Cover large sources, alpha, corrupt sidecars, cache reuse, and live skin settings."""

    def setUp(self):
        kodistubs.reset()
        self.functions = []

    def tearDown(self):
        for func in self.functions:
            for name in os.listdir(func.save_path):
                os.remove(os.path.join(func.save_path, name))

    def function(self, method):
        func = images.ImageFunctions(method=method, is_thread=False)
        self.functions.append(func)
        return func

    def source(self, mode='RGB', size=(3840, 2160), color=(120, 80, 40)):
        buffer = io.BytesIO()
        Image.new(mode, size, color).save(buffer, 'PNG')
        kodistubs.URLS[ORIGINAL] = buffer.getvalue()

    def test_desaturate_bounds_opaque_output_and_encodes_jpeg(self):
        self.source()
        func = self.function('desaturate')
        output = func.desaturate(ORIGINAL)
        with Image.open(output) as result:
            self.assertEqual(result.size, (1920, 1080))
            self.assertEqual(result.format, 'JPEG')
        with mock.patch.object(images, '_openimage', side_effect=AssertionError('cache missed')), \
                mock.patch.object(images, '_touch_file') as touch:
            self.assertEqual(func.desaturate(ORIGINAL), output)
        touch.assert_called_once_with(output)

    def test_desaturate_keeps_alpha(self):
        self.source('RGBA', color=(120, 80, 40, 80))
        output = self.function('desaturate').desaturate(ORIGINAL)
        with Image.open(output) as result:
            self.assertEqual(result.format, 'PNG')
            self.assertEqual(result.getpixel((0, 0))[1], 80)

    def test_crop_keeps_clearlogo_transparency(self):
        self.source('RGBA', size=(1000, 400), color=(120, 80, 40, 80))
        output = self.function('crop').crop(ORIGINAL)
        with Image.open(output) as result:
            self.assertEqual(result.format, 'PNG')
            self.assertIn('A', result.getbands())

    def test_colors_reuse_tiny_rgb_sidecar_without_decode_and_touch_cache(self):
        self.source(size=(300, 400))
        func = self.function('colors')
        first = func.colors(ORIGINAL)
        self.assertRegex(first, r'^FF[0-9a-f]{6}$')
        paths = [os.path.join(func.save_path, name) for name in os.listdir(func.save_path)]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith('.json'))
        self.assertLess(os.path.getsize(paths[0]), 100)
        with open(paths[0]) as stream:
            self.assertEqual(json.load(stream), [120, 80, 40])
        for key in ('ListItem.Colors.Main', 'ListItem.Colors.Comp'):
            func.get_property(key, clear_property=True)
        kodistubs.INFOLABELS['Skin.String(TMDbHelper.Colors.Luminance)'] = '0.8'
        with mock.patch.object(images, '_openimage', side_effect=AssertionError('source decoded')), \
                mock.patch.object(images, '_imageopen', side_effect=AssertionError('cache decoded')), \
                mock.patch.object(images, '_touch_file') as touch:
            second = func.colors(ORIGINAL)
        self.assertNotEqual(first, second)
        touch.assert_called_once_with(paths[0])
        self.assertRegex(func.get_property('ListItem.Colors.Comp'), r'^FF[0-9a-f]{6}$')

    def test_corrupt_color_sidecar_is_regenerated(self):
        self.source(size=(30, 40))
        func = self.function('colors')
        path = os.path.join(func.save_path, f'{images.md5hash(ORIGINAL)}.json')
        for value in (b'broken', b'[]', b'[0,0,"bad"]', b'[999,0,0]', b'[NaN,0,0]'):
            with open(path, 'wb') as stream:
                stream.write(value)
            self.assertTrue(func.colors(ORIGINAL))

    def test_missing_color_source_returns_empty_without_sidecar(self):
        func = self.function('colors')
        self.assertEqual(func.colors(ORIGINAL), '')
        self.assertEqual(os.listdir(func.save_path), [])

    def test_image_settings_change_between_operations_and_corner_zero_is_valid(self):
        first = self.function('blur')
        kodistubs.INFOLABELS.update({
            'Skin.String(TMDbHelper.Blur.Size)': '240',
            'Skin.String(TMDbHelper.Blur.Radius)': '12',
            'Skin.String(TMDbHelper.Corner.Radius)': '0',
        })
        second = self.function('blur')
        self.assertEqual((second.blur_size, second.radius, second.corner), (240, 12, 0))
        self.assertNotEqual(first.blur_size, second.blur_size)


if __name__ == '__main__':
    unittest.main()
