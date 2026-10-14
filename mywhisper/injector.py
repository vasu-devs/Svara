"""System-wide text injection primitives, chosen per platform.

Windows: Win32 SendInput + clipboard (`injector_win`). Linux/Wayland: a uinput
virtual keyboard + wl-clipboard (`injector_wayland`). Both expose the same
names so `injection/` and `transforms/` never ask which OS they are on.
"""

import os

if os.name == "nt":
    from .injector_win import *  # noqa: F401,F403
    from .injector_win import (_clipboard_get, _clipboard_set,  # noqa: F401
                               _key_event, _send)
else:
    from .injector_wayland import *  # noqa: F401,F403
    from .injector_wayland import _clipboard_get, _clipboard_set  # noqa: F401


def __getattr__(name: str):
    # `TextInjector` moved to `mywhisper.injection`; resolved lazily so the old
    # import path keeps working without a circular import.
    if name == "TextInjector":
        from .injection import TextInjector

        return TextInjector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
