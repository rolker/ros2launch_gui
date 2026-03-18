__all__ = ['UserInterface']


def __getattr__(name):
    if name == 'UserInterface':
        from .main import UserInterface
        return UserInterface
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
