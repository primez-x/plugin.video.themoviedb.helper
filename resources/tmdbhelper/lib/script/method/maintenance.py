# Module: default
# Author: jurialmunkey
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html


class DatabaseMaintenance:

    next_vacuum = 0
    next_delete = 0
    next_prune = 0

    vacuum_interval = 60 * 60 * 6
    delete_interval = 60 * 60 * 24
    prune_interval = 60 * 60 * 24

    # Primez: derivative image caches and expired cache rows otherwise grow
    # without bound (blur_v3 alone reached 2.5 GB on a CoreELEC box).
    img_cache_folders = ('blur_v3', 'crop_v2', 'desaturate_v2', 'colors_v2')
    img_cache_max_age = 60 * 60 * 24 * 30  # delete derivatives unused for 30 days
    expired_item_grace = 60 * 60 * 24 * 90  # delete items expired for over 90 days
    prune_time_budget = 120  # seconds of work per daily run; leftovers wait a day
    prune_batch_size = 500

    allow_during_video_playback = False

    vacuum_idle_condition = 'System.IdleTime(600) | System.ScreenSaverActive'  # Primez: Only vacuum when user is idle

    legacy_databases_folders = (
        'database',
        'database_v2',
        'database_v3',
        'database_v4',
        'database_v5',
        'database_v6',
        'database_v7'
    )

    legacy_img_cache_folders = (
        'blur', 'blur_v2',
        'crop',
        'desaturate',
        'colors'
    )

    def set_next_vacuum(self):
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        self.next_vacuum = set_timestamp(self.vacuum_interval)

    def set_next_delete(self):
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        self.next_delete = set_timestamp(self.delete_interval)

    def set_next_prune(self):
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        self.next_prune = set_timestamp(self.prune_interval)

    @property
    def is_next_vacuum(self):
        from tmdbhelper.lib.addon.tmdate import get_timestamp
        return bool(not get_timestamp(self.next_vacuum))

    @property
    def is_next_delete(self):
        from tmdbhelper.lib.addon.tmdate import get_timestamp
        return bool(not get_timestamp(self.next_delete))

    @property
    def is_next_prune(self):
        from tmdbhelper.lib.addon.tmdate import get_timestamp
        return bool(not get_timestamp(self.next_prune))

    @property
    def is_blocked_by_playback(self):
        if self.allow_during_video_playback:
            return False
        import xbmc
        return xbmc.Player().isPlayingVideo()

    @property
    def is_blocked_by_activity(self):
        """ Primez: Block until user is idle. Next vacuum time is only set after running so blocked checks just postpone """
        import xbmc
        return not xbmc.getCondVisibility(self.vacuum_idle_condition)

    @property
    def is_vacuum_allowed(self):
        if self.is_blocked_by_playback:
            return False
        if not self.is_next_vacuum:  # Primez: Check timestamp before idle condition
            return False
        return not self.is_blocked_by_activity

    @property
    def is_delete_allowed(self):
        if self.is_blocked_by_playback:
            return False
        return self.is_next_delete

    @property
    def is_prune_allowed(self):
        if self.is_blocked_by_playback:
            return False
        return self.is_next_prune

    @property
    def legacy_usr_cache_folders(self):
        from tmdbhelper.lib.addon.plugin import get_setting
        image_location = get_setting('image_location', 'str')
        return tuple((
            f'{image_location}{f}'
            for f in self.legacy_img_cache_folders
        )) if image_location else tuple()

    @property
    def todays_date(self):
        from tmdbhelper.lib.addon.tmdate import get_todays_date
        return get_todays_date()

    def vacuum(self, force=False):
        if not force and not self.is_vacuum_allowed:
            return
        self.set_next_vacuum()
        from tmdbhelper.lib.addon.logger import TimerFunc
        from tmdbhelper.lib.items.database.database import ItemDetailsDatabase
        from tmdbhelper.lib.query.database.database import FindQueriesDatabase
        with TimerFunc('Vacuuming databases:', inline=True):
            ItemDetailsDatabase().execute_sql_and_close("VACUUM")
            FindQueriesDatabase().execute_sql_and_close("VACUUM")

    def delete_legacy_folders(self, force=False):
        """ Once-off routine to delete old unused database versions to avoid wasting disk space """
        if not force and not self.is_delete_allowed:
            return
        self.set_next_delete()
        from tmdbhelper.lib.files.futils import delete_folder
        for f in self.legacy_databases_folders:
            delete_folder(f, force=True, check_exists=True, join_addon_data=True)
        for f in self.legacy_img_cache_folders:
            delete_folder(f, force=True, check_exists=True, join_addon_data=True)
        for f in self.legacy_usr_cache_folders:
            delete_folder(f, force=True, check_exists=True, join_addon_data=False)

    @property
    def img_cache_base(self):
        from tmdbhelper.lib.addon.plugin import get_setting, ADDONDATA
        return get_setting('image_location', 'str') or ADDONDATA

    def prune_image_caches(self, force=False):
        """ Primez: delete derivative images untouched for img_cache_max_age.
        Cache hits refresh mtime (see images._touch_file), so anything older
        has not been displayed in that long and regenerates on demand. """
        if not force and not self.is_prune_allowed:
            return
        import time
        import xbmcvfs
        from tmdbhelper.lib.addon.logger import kodi_log
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        cutoff = set_timestamp(0, set_int=True) - self.img_cache_max_age
        deadline = time.monotonic() + self.prune_time_budget
        deleted = 0
        for folder in self.img_cache_folders:
            path = f'{self.img_cache_base}{folder}/'
            if not xbmcvfs.exists(path):  # Listing a missing folder logs a Kodi error
                continue
            for filename in xbmcvfs.listdir(path)[1]:
                if time.monotonic() > deadline or self.is_blocked_by_playback:
                    kodi_log(f'Image cache prune paused after {deleted} files', 1)
                    return
                filepath = f'{path}{filename}'
                try:
                    if xbmcvfs.Stat(filepath).st_mtime() < cutoff:
                        deleted += bool(xbmcvfs.delete(filepath))
                except Exception as exc:
                    kodi_log(f'Image cache prune failed for {filepath}: {exc}', 1)
        kodi_log(f'Image cache prune deleted {deleted} files', 1) if deleted else None

    def prune_caches(self, force=False):
        if not force and not self.is_prune_allowed:
            return
        self.set_next_prune()
        self.prune_image_caches(force=True)
        self.delete_expired_items(force=True)

    def delete_expired_items(self, force=False):
        """ Primez: expired ItemDetails rows are invisible to every read
        (all conditions require expiry >= now) but were never deleted, so
        the database only grew. Delete baseitems expired for over
        expired_item_grace in batches; foreign keys cascade to child
        tables. Items with user-chosen art are kept. Also drop stale
        FindQueries expiry markers and expired identifier matches. """
        if not force and not self.is_prune_allowed:
            return
        import time
        from tmdbhelper.lib.addon.logger import kodi_log
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        from tmdbhelper.lib.items.database.database import ItemDetailsDatabase
        from tmdbhelper.lib.query.database.database import FindQueriesDatabase
        now = set_timestamp(0, set_int=True)
        cutoff = now - self.expired_item_grace
        deadline = time.monotonic() + self.prune_time_budget
        database = ItemDetailsDatabase()
        deleted = 0
        while time.monotonic() < deadline and not self.is_blocked_by_playback:
            cursor = database.execute_sql(
                'SELECT id FROM baseitem WHERE expiry > 0 AND expiry < ? '
                'AND id NOT IN (SELECT parent_id FROM user_art) LIMIT ?',
                data=(cutoff, self.prune_batch_size), read_only=True)
            item_ids = [row[0] for row in cursor.fetchall()] if cursor else []
            database.close_cursor(cursor, close_connection=True)
            if not item_ids:
                break
            database.execute_sql_and_close(
                f'DELETE FROM baseitem WHERE id IN ({",".join("?" * len(item_ids))})',
                data=tuple(item_ids))
            deleted += len(item_ids)
            if len(item_ids) < self.prune_batch_size:
                break
        queries = FindQueriesDatabase()
        queries.execute_sql_and_close(
            'DELETE FROM identifier WHERE id IN '
            '(SELECT substr(id, 12) FROM expiry WHERE id LIKE ? AND expiry < ?)',
            data=('identifier.%', now))
        queries.execute_sql_and_close(
            'DELETE FROM expiry WHERE expiry < ?', data=(cutoff, ))
        kodi_log(f'Expired item purge deleted {deleted} items', 1) if deleted else None

    @staticmethod
    def recache_kodidb(notification=True, confirmation=False):
        from tmdbhelper.lib.addon.plugin import ADDONPATH, get_setting
        from tmdbhelper.lib.api.kodi.rpc import KodiLibrary
        from tmdbhelper.lib.addon.logger import TimerFunc
        from xbmcgui import Dialog

        if get_setting('use_kodi_local_db', 'int') or get_setting('default_player_kodi', 'int'):
            with TimerFunc('KodiLibrary sync took', inline=True):
                KodiLibrary('movie', cache_refresh=True).database
                KodiLibrary('tvshow', cache_refresh=True).database
            data = 'Kodi Library cache refreshed'
        else:
            data = 'Kodi Library lookup is disabled'

        if notification:
            head = 'TMDbHelper'
            icon = f'{ADDONPATH}/icon.png'
            Dialog().notification(head, data, icon=icon)

        if confirmation:
            head = 'TMDbHelper'
            Dialog().ok(head, data)


recache_kodidb = DatabaseMaintenance.recache_kodidb
