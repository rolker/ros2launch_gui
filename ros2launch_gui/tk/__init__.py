__all__ = ['UserInterface']


def __getattr__(name):
    if name == 'UserInterface':
        from .user_interface import UserInterface
        return UserInterface
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
