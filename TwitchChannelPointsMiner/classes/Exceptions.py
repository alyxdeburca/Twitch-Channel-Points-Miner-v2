class StreamerDoesNotExistException(Exception):
    pass


class StreamerLookupException(Exception):
    """Channel lookup failed server-side (integrity/gating/etc).

    Distinct from StreamerDoesNotExistException: the user may well exist,
    Twitch just refused to answer. Callers should surface this instead of
    reporting 'does not exist'."""
    pass


class StreamerIsOfflineException(Exception):
    pass


class WrongCookiesException(Exception):
    pass


class BadCredentialsException(Exception):
    pass
