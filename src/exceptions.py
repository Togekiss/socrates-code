def unwrap(exc: Exception):
    parts = []
    current = exc
    while current:
        tb = current.__traceback__
        funcname = None
        if tb:
            # Walk to the deepest frame of this exception
            while tb.tb_next:
                tb = tb.tb_next
            funcname = tb.tb_frame.f_code.co_name

        parts.append(f"({funcname}) {type(current).__name__}: {current}")
        current = current.__cause__
    return "\n^ caused by <- ".join(parts)

class AlreadyRunningError(Exception):
    pass

class ConsoleCommandError(Exception):
    pass

class DataNotReadyError(Exception):
    pass

class ChannelListError(Exception):
    pass

class GetChannelListError(ChannelListError):
    pass

class CleanChannelListError(ChannelListError):
    pass

class ExportError(Exception):
    pass

class DownloadExportError(ExportError):
    pass

class FileSortingError(Exception):
    pass

class FileSortingReadError(FileSortingError):
    pass

class FileSortingCleanError(FileSortingError):
    pass

class FileSortingWriteError(FileSortingError):
    pass

class AssignIDError(Exception):
    pass

class MergeError(Exception):
    pass

class FixMessagesError(Exception):
    pass

class UpdateInfoError(Exception):
    pass

class FindScenesError(Exception):
    pass