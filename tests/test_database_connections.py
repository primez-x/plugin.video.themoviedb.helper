from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread
import unittest

from tests._support import ConnectionFactory, FailingCursorConnection, ORIGINAL_CONNECT
from tmdbhelper.lib.files.dbfunc import DatabaseAccess, DatabaseConnection


class FakeCache:
    def __init__(self, database_path, connection_class=None):
        self.database_path = database_path
        self.factory = ConnectionFactory(connection_class) if connection_class else ConnectionFactory()

    @property
    def connections(self):
        return self.factory.connections

    def get_database(self):
        return self.factory(self.database_path, timeout=10.0)


class DatabaseConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_path = str(Path(self.temp_directory.name) / 'cache.db')

    def test_shared_database_access_uses_per_thread_connections(self):
        cache = FakeCache(self.database_path)
        access = DatabaseAccess()
        access.cache = cache
        manager = access.connection
        first_opened = Event()
        release_first = Event()
        cursors = []
        errors = []

        def first_worker():
            try:
                with manager.open() as cursor:
                    cursors.append(cursor)
                    cursor.execute('SELECT 1').fetchone()
                    first_opened.set()
                    if not release_first.wait(5):
                        raise TimeoutError('second worker did not finish')
            except BaseException as error:
                errors.append(error)

        def second_worker():
            try:
                if not first_opened.wait(5):
                    raise TimeoutError('first worker did not open its connection')
                with manager.open() as cursor:
                    cursors.append(cursor)
                    cursor.execute('SELECT 1').fetchone()
            except BaseException as error:
                errors.append(error)
            finally:
                release_first.set()

        threads = [Thread(target=first_worker), Thread(target=second_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(cache.connections), 2)
        self.assertEqual(len({id(cursor) for cursor in cursors}), 2)
        self.assertEqual(len({cursor.creator_thread for cursor in cursors}), 2)
        self.assertTrue(all(connection.closed for connection in cache.connections))
        self.assertTrue(all(cursor.closed for connection in cache.connections for cursor in connection.cursors))
        self.assertIsNone(manager.open_connection)

    def test_database_access_initializes_one_shared_wrapper(self):
        cache = FakeCache(self.database_path)
        access = DatabaseAccess()
        access.cache = cache
        barrier = Barrier(8)
        managers = []

        def get_manager():
            barrier.wait()
            managers.append(access.connection)

        threads = [Thread(target=get_manager) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(managers), 8)
        self.assertEqual(len({id(manager) for manager in managers}), 1)

    def test_concurrent_transactions_preserve_integrity(self):
        with ORIGINAL_CONNECT(self.database_path) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute(
                'CREATE TABLE item(worker INTEGER, sequence INTEGER, '
                'PRIMARY KEY(worker, sequence))'
            )
        connection.close()

        cache = FakeCache(self.database_path)
        manager = DatabaseConnection(cache)
        worker_count = 8
        rows_per_worker = 25
        barrier = Barrier(worker_count)
        errors = []

        def worker(worker_id):
            try:
                barrier.wait(10)
                with manager.open() as cursor:
                    cursor.executemany(
                        'INSERT INTO item(worker, sequence) VALUES (?, ?)',
                        [(worker_id, sequence) for sequence in range(rows_per_worker)],
                    )
            except BaseException as error:
                errors.append(error)

        threads = [Thread(target=worker, args=(worker_id,)) for worker_id in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(cache.connections), worker_count)
        self.assertTrue(all(connection.closed for connection in cache.connections))

        with ORIGINAL_CONNECT(self.database_path) as connection:
            row_count = connection.execute('SELECT COUNT(*) FROM item').fetchone()[0]
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
        connection.close()

        self.assertEqual(row_count, worker_count * rows_per_worker)
        self.assertEqual(integrity, 'ok')

    def test_nested_open_reuses_cursor_until_outer_exit(self):
        cache = FakeCache(self.database_path)
        manager = DatabaseConnection(cache)

        with manager.open() as outer_cursor:
            connection = cache.connections[0]
            with manager.open() as inner_cursor:
                self.assertIs(inner_cursor, outer_cursor)
                self.assertFalse(inner_cursor.closed)
                self.assertFalse(connection.closed)
            self.assertFalse(outer_cursor.closed)
            self.assertFalse(connection.closed)

        self.assertTrue(outer_cursor.closed)
        self.assertTrue(connection.closed)
        self.assertEqual(outer_cursor.close_count, 1)
        self.assertEqual(connection.close_count, 1)
        self.assertIsNone(manager.open_connection)

    def test_open_commits_on_success_and_rolls_back_on_exception(self):
        with ORIGINAL_CONNECT(self.database_path) as connection:
            connection.execute('CREATE TABLE item(id INTEGER PRIMARY KEY)')
        connection.close()

        cache = FakeCache(self.database_path)
        manager = DatabaseConnection(cache)

        with manager.open() as cursor:
            cursor.execute('INSERT INTO item(id) VALUES (1)')

        with self.assertRaisesRegex(RuntimeError, 'roll back'):
            with manager.open() as cursor:
                cursor.execute('INSERT INTO item(id) VALUES (2)')
                raise RuntimeError('roll back')

        with ORIGINAL_CONNECT(self.database_path) as connection:
            item_ids = connection.execute('SELECT id FROM item ORDER BY id').fetchall()
        connection.close()

        self.assertEqual(item_ids, [(1,)])
        self.assertTrue(all(connection.closed for connection in cache.connections))

    def test_open_closes_resources_when_body_raises(self):
        cache = FakeCache(self.database_path)
        manager = DatabaseConnection(cache)

        with self.assertRaisesRegex(RuntimeError, 'body failed'):
            with manager.open() as cursor:
                connection = cache.connections[0]
                cursor.execute('CREATE TABLE item(id INTEGER)')
                raise RuntimeError('body failed')

        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)
        self.assertEqual(cursor.close_count, 1)
        self.assertEqual(connection.close_count, 1)
        self.assertIsNone(manager.open_connection)

    def test_open_closes_connection_when_cursor_creation_fails(self):
        cache = FakeCache(self.database_path, FailingCursorConnection)
        manager = DatabaseConnection(cache)

        with self.assertRaisesRegex(RuntimeError, 'cursor creation failed'):
            with manager.open():
                pass

        self.assertEqual(len(cache.connections), 1)
        self.assertTrue(cache.connections[0].closed)
        self.assertEqual(cache.connections[0].close_count, 1)
        self.assertIsNone(manager.open_connection)


if __name__ == '__main__':
    unittest.main()
