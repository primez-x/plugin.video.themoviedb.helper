from contextlib import contextmanager
from functools import cached_property
from pathlib import Path
from threading import RLock, get_ident
from types import ModuleType
import sqlite3
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_PATH = REPOSITORY_ROOT / 'resources'
ORIGINAL_CONNECT = sqlite3.connect


class threaded_cached_property:
    def __init__(self, func):
        self.__doc__ = getattr(func, '__doc__')
        self.func = func
        self.lock = RLock()

    def __get__(self, obj, cls):
        if obj is None:
            return self
        name = self.func.__name__
        with self.lock:
            try:
                return obj.__dict__[name]
            except KeyError:
                return obj.__dict__.setdefault(name, self.func(obj))


@contextmanager
def null_context(*args, **kwargs):
    yield


class FileUtils:
    pass


def install_module_stubs():
    resources_path = str(RESOURCES_PATH)
    if resources_path not in sys.path:
        sys.path.insert(0, resources_path)

    jurialmunkey = sys.modules.setdefault('jurialmunkey', ModuleType('jurialmunkey'))
    jurialmunkey.__path__ = []

    ftools = ModuleType('jurialmunkey.ftools')
    ftools.cached_property = cached_property
    ftools.threaded_cached_property = threaded_cached_property
    sys.modules['jurialmunkey.ftools'] = ftools

    locker = ModuleType('jurialmunkey.locker')
    locker.MutexPropLock = null_context
    sys.modules['jurialmunkey.locker'] = locker

    logger = ModuleType('tmdbhelper.lib.addon.logger')
    logger.kodi_log = lambda *args, **kwargs: None
    logger.TimerFunc = null_context
    sys.modules['tmdbhelper.lib.addon.logger'] = logger

    plugin = ModuleType('tmdbhelper.lib.addon.plugin')
    plugin.get_setting = lambda *args, **kwargs: ''
    plugin.get_version = lambda: 'test'
    sys.modules['tmdbhelper.lib.addon.plugin'] = plugin

    futils = ModuleType('tmdbhelper.lib.files.futils')
    futils.FileUtils = FileUtils
    sys.modules['tmdbhelper.lib.files.futils'] = futils


class TrackingCursor(sqlite3.Cursor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False
        self.close_count = 0
        self.creator_thread = get_ident()

    def close(self):
        self.closed = True
        self.close_count += 1
        return super().close()


class TrackingConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False
        self.close_count = 0
        self.creator_thread = get_ident()
        self.cursors = []

    def cursor(self, factory=TrackingCursor):
        cursor = super().cursor(factory)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True
        self.close_count += 1
        return super().close()


class FailingCursorConnection(TrackingConnection):
    def cursor(self, factory=TrackingCursor):
        raise RuntimeError('cursor creation failed')


class FailingSchemaCursor(TrackingCursor):
    def execute(self, sql, parameters=()):
        if sql == 'PRAGMA user_version':
            raise RuntimeError('schema initialization failed')
        return super().execute(sql, parameters)


class FailingSchemaConnection(TrackingConnection):
    def cursor(self, factory=FailingSchemaCursor):
        return super().cursor(factory)


class FailingPartialSchemaCursor(TrackingCursor):
    def execute(self, sql, parameters=()):
        if sql.startswith('CREATE TABLE IF NOT EXISTS second'):
            raise RuntimeError('second table creation failed')
        return super().execute(sql, parameters)


class FailingPartialSchemaConnection(TrackingConnection):
    def cursor(self, factory=FailingPartialSchemaCursor):
        return super().cursor(factory)


class ConnectionFactory:
    def __init__(self, connection_class=TrackingConnection):
        self.connection_class = connection_class
        self.connections = []

    def __call__(self, database, *args, **kwargs):
        kwargs['factory'] = self.connection_class
        connection = ORIGINAL_CONNECT(database, *args, **kwargs)
        self.connections.append(connection)
        return connection


install_module_stubs()
