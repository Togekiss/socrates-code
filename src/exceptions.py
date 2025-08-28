def unwrap(exc: Exception):
    parts = []
    current = exc
    while current:
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__
    return(" <- caused by <- ".join(parts))

class ChannelListException(Exception):
    pass

class ChannelListGetException(ChannelListException):
    pass

class ChannelListCleanException(ChannelListException):
    pass

class ConsoleCommandException(Exception):
    pass