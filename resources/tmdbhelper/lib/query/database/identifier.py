from collections import namedtuple


IdentifierTuple = namedtuple("identifierTuple", "item_id tmdb_id tmdb_type")


TABLE = 'identifier'
KEYS = ('id', 'tmdb_id', 'tmdb_type')
IDENTIFIER_EXPIRY = 60 * 60 * 24 * 90  # Primez: re-check fuzzy matches after 90 days


def make_identifier_id(
    dbtype=None,
    query=None,
    season=None,
    episode=None,
    imdb_id=None,
    year=None,
    episode_year=None,
    infolabel_uniqueid_tmdb=None,
    infolabel_uniqueid_tvshow_tmdb=None,
):
    return '.'.join(map(str, (
        dbtype or None,
        query or None,
        season or None,
        episode or None,
        imdb_id or None,
        year or None,
        episode_year or None,
        infolabel_uniqueid_tmdb or None,
        infolabel_uniqueid_tvshow_tmdb or None,
    )))


class FindQueriesDatabaseIdentifier:

    identifier_columns = {
        'id': {
            'data': 'BLOB PRIMARY KEY',
            'indexed': True
        },
        'tmdb_id': {
            'data': 'INTEGER'
        },
        'tmdb_type': {
            'data': 'TEXT'
        },
    }

    def get_identifier(self, item_id):
        # Primez: per-item expiry so a wrong fuzzy match is not kept forever;
        # rows written before per-item expiry existed count as expired.
        if self.is_expired(f'{TABLE}.{item_id}'):
            return None
        with self.access.connection.open():
            data = self.get_all_values(TABLE, KEYS, values=(item_id, ), conditions='id=?')
        return (
            IdentifierTuple(item_id, data[0]['tmdb_id'], data[0]['tmdb_type'])
            if data and data[0] else
            None
        )

    def set_identifier(self, item_id, tmdb_id, tmdb_type):
        if not item_id or not tmdb_id or not tmdb_type:
            return
        identifier_tuple = IdentifierTuple(item_id, tmdb_id, tmdb_type)
        self.set_cached_values(TABLE, KEYS, [identifier_tuple], item_id=item_id, expiry=IDENTIFIER_EXPIRY)
        return identifier_tuple

    def del_identifier(self, item_id):
        with self.access.connection.open() as connection:
            connection.execute('BEGIN')
            self.access.del_cached(TABLE, item_id, children=False)
            self.access.del_cached('expiry', f'{TABLE}.{item_id}', children=False)
            connection.execute('COMMIT')
