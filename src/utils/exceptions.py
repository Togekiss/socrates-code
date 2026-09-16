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

class BackupError(Exception):
    pass

class ServerBackupClassError(BackupError):
    pass

class LoadFileError(BackupError):
    pass

class AlreadyRunningError(BackupError):
    pass

class ConsoleCommandError(BackupError):
    pass

class DataNotReadyError(BackupError):
    pass

class ChannelListError(BackupError):
    pass

class GetChannelListError(ChannelListError):
    pass

class CleanChannelListError(ChannelListError):
    pass

class ExportError(BackupError):
    pass

class DownloadExportError(ExportError):
    pass

class VerifyError(BackupError):
    pass

class VerifyPathsError(VerifyError):
    pass

class FileSortingError(BackupError):
    pass

class FileSortingReadError(FileSortingError):
    pass

class FileSortingCleanError(FileSortingError):
    pass

class FileSortingWriteError(FileSortingError):
    pass

class AssignIDError(BackupError):
    pass

class UpdatePathsError(BackupError):
    pass

class MergeError(BackupError):
    pass

class FixMessagesError(BackupError):
    pass

class UpdateInfoError(BackupError):
    pass

class IndexScenesError(BackupError):
    pass

class FindCharacterScenesError(BackupError):
    pass