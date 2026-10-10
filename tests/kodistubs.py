"""
Primez: Minimal stand-ins for Kodi (xbmc*), script.module.jurialmunkey and the heavy
tmdbhelper modules so focused unit tests can import monitor code without Kodi or network.
Call install() before importing any tmdbhelper module.
"""
import os
import sys
import time
import types
import threading
import atexit
import shutil
import tempfile
import contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(ROOT, 'resources')

INFOLABELS = {}  # getInfoLabel values
CONDITIONS = {}  # getCondVisibility values
URLS = {}  # Remote url -> bytes served by xbmcvfs.File
READS = []  # Paths read by xbmcvfs.File
COPIES = []  # (source, destination) copied by xbmcvfs.copy
WINDOW_PROPERTIES = {}  # {window_id: {key: value}}
SET_PROPERTY_CALLS = []  # (window_id, key, value) for every setProperty
CURRENT_WINDOW = [10025]

_installed = False


def reset():
    INFOLABELS.clear()
    CONDITIONS.clear()
    URLS.clear()
    READS.clear()
    COPIES.clear()
    WINDOW_PROPERTIES.clear()
    SET_PROPERTY_CALLS.clear()
    CURRENT_WINDOW[0] = 10025


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class _Monitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=0):
        return False


class _Player:
    def isPlayingVideo(self):
        return False


class _Window:
    def __init__(self, window_id=10000):
        self.window_id = window_id
        self.properties = WINDOW_PROPERTIES.setdefault(window_id, {})

    def getProperty(self, key):
        return self.properties.get(key.lower(), '')

    def setProperty(self, key, value):
        SET_PROPERTY_CALLS.append((self.window_id, key, value))
        self.properties[key.lower()] = value

    def clearProperty(self, key):
        self.properties.pop(key.lower(), None)


class _File:
    def __init__(self, path, mode='r'):
        self.path = path
        self.mode = mode
        self.buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def readBytes(self, numbytes=0):
        READS.append(self.path)
        if self.path in URLS:
            return bytearray(URLS[self.path])
        if self.path.startswith(('http://', 'https://')):
            return bytearray()
        try:
            with open(self.path, 'rb') as f:
                return bytearray(f.read())
        except OSError:
            return bytearray()

    def write(self, data):
        self.buffer += data
        return True

    def close(self):
        if 'w' in self.mode:
            with open(self.path, 'wb') as f:
                f.write(self.buffer)


def _vfs_exists(path):
    return os.path.exists(path)


def _vfs_copy(source, destination):
    COPIES.append((source, destination))
    data = URLS.get(source)
    if data is None and os.path.exists(source):
        with open(source, 'rb') as f:
            data = f.read()
    if data is None:
        return False
    with open(destination, 'wb') as f:
        f.write(data)
    return True


def _vfs_delete(path):
    with contextlib.suppress(OSError):
        os.remove(path)
    return True


def _try_type(value, output=None):
    if output is int:
        return _try_int(value)
    if output is float:
        return _try_float(value)
    return value


def _try_int(value, base=10, fallback=0):
    try:
        return int(value, base) if isinstance(value, str) and base != 10 else int(value)
    except (ValueError, TypeError):
        return fallback


def _try_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


class _cached_property:
    def __init__(self, func):
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def _get_current_window(get_dialog=True):
    return CURRENT_WINDOW[0]


def _get_property(name, set_property=None, clear_property=False, window_id=None, prefix=None, is_type=None):
    name = f'{prefix or "TMDbHelper"}.{name}' if prefix != -1 else name
    window = _Window(window_id or 10000)
    ret_property = set_property or window.getProperty(name)
    if clear_property:
        window.clearProperty(name)
    if set_property is not None:
        window.setProperty(name, f'{set_property}')
    return _try_type(ret_property, is_type or str)


class _WindowPropertySetter:
    window_id = 10000

    def get_window(self, use_current_window=False, get_dialog=False):
        return _Window(_get_current_window() if use_current_window else self.window_id)

    def get_property(self, name, set_property=None, clear_property=False, is_type=None, prefix='TMDbHelper', use_current_window=False):
        _win = self.get_window(use_current_window)
        name = f'{prefix}.{name}'
        ret_property = set_property or _win.getProperty(name)
        if clear_property:
            _win.clearProperty(name)
        if set_property is not None:
            _win.setProperty(name, f'{set_property}')
        return _try_type(ret_property, is_type or str)


class _WindowChecker:
    def get_current_window(self):
        self._current_window = _get_current_window()
        return self._current_window

    def get_current_base_window(self):
        self._current_base_window = _get_current_window(get_dialog=False)
        return self._current_base_window

    def is_current_window_xml(self, values):
        return False

    def is_current_base_window_xml(self, values):
        return False

    def get_window_property(self, key, is_type=None, is_home=False, is_id=0):
        return ''


def _kodi_try_except(log_msg, exception_retval=None):
    def decorator(func):
        return func
    return decorator


@contextlib.contextmanager
def _timer_func(*args, **kwargs):
    yield


def _make_path(path, warn_dialog=False):
    os.makedirs(path, exist_ok=True)
    return path


def _set_timestamp(wait_time=60, set_int=False):
    return time.time() + wait_time


def _get_timestamp(timestamp=None, set_int=False):
    if not timestamp:
        return
    if time.time() > timestamp:
        return
    return timestamp


class MonitorItemDetailsStub:
    """ Stand-in for tmdbhelper.lib.monitor.itemdetails.MonitorItemDetails """
    def __init__(self, parent, position=0):
        self.parent = parent
        self.position = position
        self.identifier = self.get_identifier()

    def get_identifier(self):
        return INFOLABELS.get('identifier', '')

    def get_infolabel(self, info):
        return INFOLABELS.get(f'ListItem.{info}', '')


def install(scratch_dir=None):
    """ Install stub modules once. scratch_dir is used as the addon data folder for image output """
    global _installed
    if _installed:
        return
    _installed = True

    if RESOURCES not in sys.path:
        sys.path.insert(0, RESOURCES)

    if not scratch_dir:
        scratch_dir = tempfile.mkdtemp(prefix='tmdbhelper-tests-')
        atexit.register(shutil.rmtree, scratch_dir, True)
    addondata = scratch_dir.rstrip('/') + '/'

    def get_infolabel(info):
        return INFOLABELS.get(info, '')

    def get_condvisibility(condition):
        return CONDITIONS.get(condition, False)

    _module(
        'xbmc',
        getInfoLabel=get_infolabel, getCondVisibility=get_condvisibility,
        Monitor=_Monitor, Player=_Player, sleep=lambda ms: None,
        getCacheThumbName=lambda path: f'{abs(hash(path)) & 0xffffffff:08x}.tbn',
        skinHasImage=lambda image: False, executebuiltin=lambda *args, **kwargs: None,
        log=lambda *args, **kwargs: None, getSkinDir=lambda: 'skin.test',
        LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
    _module(
        'xbmcgui', Window=_Window,
        getCurrentWindowId=lambda: CURRENT_WINDOW[0], getCurrentWindowDialogId=lambda: 9999)
    _module(
        'xbmcvfs', File=_File, exists=_vfs_exists, copy=_vfs_copy, delete=_vfs_delete,
        translatePath=lambda path: path, mkdirs=lambda path: os.makedirs(path, exist_ok=True))

    _module('jurialmunkey').__path__ = []
    _module(
        'jurialmunkey.window', WindowPropertySetter=_WindowPropertySetter, WindowChecker=_WindowChecker,
        get_current_window=_get_current_window, get_property=_get_property)
    _module('jurialmunkey.parser', try_int=_try_int, try_float=_try_float, try_type=_try_type)
    _module('jurialmunkey.ftools', cached_property=_cached_property, threaded_cached_property=_cached_property)

    _module(
        'tmdbhelper.lib.addon.plugin',
        get_setting=lambda key, mode=None: '' if mode == 'str' else 0,
        get_infolabel=get_infolabel, get_condvisibility=get_condvisibility,
        get_skindir=lambda: 'skin.test', get_localized=lambda i: str(i),
        executebuiltin=lambda *args, **kwargs: None, ADDONDATA=addondata)
    _module(
        'tmdbhelper.lib.addon.logger',
        kodi_log=lambda *args, **kwargs: None, kodi_try_except=_kodi_try_except, TimerFunc=_timer_func)
    _module('tmdbhelper.lib.addon.thread', SafeThread=threading.Thread)
    _module('tmdbhelper.lib.addon.tmdate', set_timestamp=_set_timestamp, get_timestamp=_get_timestamp)
    _module('tmdbhelper.lib.files.futils', make_path=_make_path, validate_join=os.path.join)
    _module('tmdbhelper.lib.monitor.itemdetails', MonitorItemDetails=MonitorItemDetailsStub)
