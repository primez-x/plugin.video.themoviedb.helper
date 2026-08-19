from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import sqlite3
import unittest

from tests._support import (
    ConnectionFactory,
    FailingPartialSchemaConnection,
    FailingSchemaConnection,
    ORIGINAL_CONNECT,
)
from tmdbhelper.lib.files import dbdata
from tmdbhelper.lib.files.dbfunc import DatabaseConnection


class TestDatabase(dbdata.DatabaseCore):
    @property
    def database_tables(self):
        return {
            'items': {
                'id': {
                    'data': 'INTEGER PRIMARY KEY',
                    'indexed': True,
                },
                'name': {
                    'data': 'TEXT',
                },
            },
        }


class PartialSchemaDatabase(dbdata.DatabaseCore):
    database_version = 2

    @property
    def database_tables(self):
        return {
            'first': {
                'id': {
                    'data': 'INTEGER PRIMARY KEY',
                },
            },
            'second': {
                'id': {
                    'data': 'INTEGER PRIMARY KEY',
                },
            },
        }


class MigrationDatabase(dbdata.DatabaseCore):
    database_version = 2
    database_changes = {
        2: (
            'ALTER TABLE items ADD guest INTEGER',
        ),
    }

    @property
    def database_tables(self):
        return {
            'items': {
                'id': {
                    'data': 'INTEGER PRIMARY KEY',
                },
                'guest': {
                    'data': 'INTEGER',
                },
            },
        }


class DropThenAlterDatabase(MigrationDatabase):
    database_version = 3
    database_changes = {
        2: (
            'DROP TABLE IF EXISTS items',
        ),
        3: (
            'ALTER TABLE items ADD guest INTEGER',
        ),
    }


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_path = str(Path(self.temp_directory.name) / 'cache.db')
        self.database = object.__new__(TestDatabase)
        self.database._db_file = self.database_path
        self.database._sc_name = 'test_database'

    def test_create_database_closes_resources_and_commits_schema(self):
        factory = ConnectionFactory()

        with patch.object(dbdata.sqlite3, 'connect', side_effect=factory):
            self.assertTrue(self.database.create_database())

        self.assertEqual(len(factory.connections), 1)
        connection = factory.connections[0]
        self.assertTrue(connection.closed)
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(len(connection.cursors), 2)
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))
        self.assertTrue(all(cursor.close_count == 1 for cursor in connection.cursors))

        with closing(ORIGINAL_CONNECT(self.database_path)) as verification_connection:
            with verification_connection:
                table = verification_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
                ).fetchone()
                database_version = verification_connection.execute('PRAGMA user_version').fetchone()[0]

        self.assertEqual(table, ('items',))
        self.assertEqual(database_version, 1)

    def test_schema_failure_rolls_back_partial_ddl_and_logs_query(self):
        database = object.__new__(PartialSchemaDatabase)
        database._db_file = self.database_path
        database._sc_name = 'partial_schema_database'
        database.kodi_log = Mock()
        factory = ConnectionFactory(FailingPartialSchemaConnection)

        with patch.object(dbdata.sqlite3, 'connect', side_effect=factory):
            self.assertFalse(database.create_database())

        self.assertTrue(factory.connections[0].closed)
        logged_messages = [call.args[0] for call in database.kodi_log.call_args_list]
        self.assertTrue(
            any('CREATE TABLE IF NOT EXISTS second' in message for message in logged_messages)
        )

        with closing(ORIGINAL_CONNECT(self.database_path)) as verification_connection:
            tables = verification_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('first', 'second')"
            ).fetchall()
            database_version = verification_connection.execute('PRAGMA user_version').fetchone()[0]

        self.assertEqual(tables, [])
        self.assertEqual(database_version, 0)

    def test_partially_applied_add_column_migration_advances_version(self):
        database = object.__new__(MigrationDatabase)
        database._db_file = self.database_path
        database._sc_name = 'migration_database'

        with closing(ORIGINAL_CONNECT(self.database_path)) as connection:
            with connection:
                connection.execute(
                    'CREATE TABLE items(id INTEGER PRIMARY KEY, guest INTEGER)'
                )
                connection.execute('PRAGMA user_version = 1')

        self.assertTrue(database.create_database())

        with closing(ORIGINAL_CONNECT(self.database_path)) as connection:
            database_version = connection.execute('PRAGMA user_version').fetchone()[0]
            columns = [row[1] for row in connection.execute('PRAGMA table_info(items)')]

        self.assertEqual(database_version, 2)
        self.assertEqual(columns, ['id', 'guest'])

    def test_dropped_table_defers_add_column_to_current_schema_creation(self):
        database = object.__new__(DropThenAlterDatabase)
        database._db_file = self.database_path
        database._sc_name = 'drop_then_alter_database'

        with closing(ORIGINAL_CONNECT(self.database_path)) as connection:
            with connection:
                connection.execute('CREATE TABLE items(id INTEGER PRIMARY KEY)')
                connection.execute('PRAGMA user_version = 1')

        self.assertTrue(database.create_database())

        with closing(ORIGINAL_CONNECT(self.database_path)) as connection:
            database_version = connection.execute('PRAGMA user_version').fetchone()[0]
            columns = [row[1] for row in connection.execute('PRAGMA table_info(items)')]

        self.assertEqual(database_version, 3)
        self.assertEqual(columns, ['id', 'guest'])

    def test_create_database_closes_resources_when_schema_setup_raises(self):
        factory = ConnectionFactory(FailingSchemaConnection)

        with patch.object(dbdata.sqlite3, 'connect', side_effect=factory):
            self.assertFalse(self.database.create_database())

        self.assertEqual(len(factory.connections), 1)
        connection = factory.connections[0]
        self.assertTrue(connection.closed)
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(len(connection.cursors), 2)
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))
        self.assertTrue(all(cursor.close_count == 1 for cursor in connection.cursors))

    def test_execute_helpers_close_owned_connections(self):
        factory = ConnectionFactory()

        with patch.object(dbdata.sqlite3, 'connect', side_effect=factory):
            self.assertTrue(self.database.create_database())
            self.database.execute_sql_and_close(
                'INSERT INTO items(id, name) VALUES (?, ?)',
                (1, 'first'),
            )
            cursor = self.database.execute_sql(
                'SELECT name FROM items WHERE id=?',
                (1,),
                read_only=True,
            )
            try:
                row = cursor.fetchone()
            finally:
                self.database.close_cursor(cursor, close_connection=True)

        self.assertEqual(row['name'], 'first')
        self.assertEqual(len(factory.connections), 3)
        self.assertTrue(all(connection.closed for connection in factory.connections))
        self.assertTrue(all(connection.close_count == 1 for connection in factory.connections))

    def test_helper_error_rolls_back_outer_transaction(self):
        self.assertTrue(self.database.create_database())
        manager = DatabaseConnection(self.database)

        with self.assertRaises(sqlite3.IntegrityError):
            with manager.open() as cursor:
                self.database.execute_sql(
                    'INSERT INTO items(id, name) VALUES (?, ?)',
                    (1, 'first'),
                    connection=cursor,
                )
                self.database.execute_sql(
                    'INSERT INTO items(id, name) VALUES (?, ?)',
                    (1, 'duplicate'),
                    connection=cursor,
                )

        with closing(ORIGINAL_CONNECT(self.database_path)) as connection:
            row_count = connection.execute('SELECT COUNT(*) FROM items').fetchone()[0]

        self.assertEqual(row_count, 0)


if __name__ == '__main__':
    unittest.main()
