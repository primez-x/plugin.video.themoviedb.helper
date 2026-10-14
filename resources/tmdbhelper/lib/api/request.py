import jurialmunkey.reqapi
from tmdbhelper.lib.addon.plugin import get_setting
from tmdbhelper.lib.addon.logger import kodi_log
from tmdbhelper.lib.files.bcache import BasicCache


def null_function(*args, **kwargs):
    return


class RequestAPI(jurialmunkey.reqapi.RequestAPI):
    error_notification = True
    _basiccache = BasicCache

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        notification = kwargs.get('error_notification', args[4] if len(args) > 4 else None)
        self._error_notification = True if notification is None else notification

    def do_error_notification(self, log_msg, note_head, note_body, notification=True):
        return super().do_error_notification(
            log_msg, note_head, note_body,
            notification=notification and get_setting('connection_notifications'))

    @staticmethod
    def kodi_log(msg, level=0):
        kodi_log(msg, level)


class NoCacheRequestAPI(RequestAPI):
    _basiccache = null_function
