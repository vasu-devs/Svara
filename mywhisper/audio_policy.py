"""Which microphone Svara should be listening to, and when to change its mind.

v0.4 only reacted to a mic *dying*. That covers the unplugged headset and
misses the case people actually hit daily: a better mic is now available and
Svara is still on the laptop's built-in one. Docking a laptop, closing the lid,
plugging in a headset — the input the user wants changed, nothing broke, and
nothing noticed.

Three policies:

- `preferred` (default) — honour `audio.input_device`, fall back on failure.
  Exactly the pre-0.5 behaviour.
- `system_default` — always follow the Windows default input device, so
  changing it in Sound settings changes Svara too.
- `external_first` — prefer any external input over a built-in one, and switch
  automatically when an external mic appears or disappears.

A note on clamshell mode: this is device-preference based, not lid-event based.
Reading the actual lid switch needs `RegisterPowerSettingNotification` and a
message pump, and it turns out not to be worth it — the case people describe as
"clamshell" is almost always "docked, with an external mic connected", which
`external_first` handles, along with the far more common headset case. If a
real lid signal is ever needed, it hooks in at `rank_devices`.

Ranking is a pure function of the device list so it can be unit tested without
any audio hardware.
"""

import logging
import re

log = logging.getLogger(__name__)

POLICIES = ("preferred", "system_default", "external_first")

# Name fragments that mark a device as built into the machine.
_INTERNAL = re.compile(
    r"internal|built[- ]?in|laptop|realtek|intel.*smart.sound|"
    r"microphone array|integrated|onboard|digital microphone",
    re.IGNORECASE)

# …and ones that mark it as something the user deliberately attached.
_EXTERNAL = re.compile(
    r"usb|headset|airpods|bluetooth|wireless|yeti|rode|shure|elgato|"
    r"webcam|hyperx|steelseries|logitech|razer|jabra|sennheiser|"
    r"external|dock|thunderbolt|scarlett|audio.?interface",
    re.IGNORECASE)


def is_internal(name: str) -> bool:
    name = name or ""
    if _EXTERNAL.search(name):
        return False
    return bool(_INTERNAL.search(name))


def is_external(name: str) -> bool:
    return bool(_EXTERNAL.search(name or ""))


def rank_devices(devices: list[dict], policy: str = "preferred",
                 preferred=None, default_index=None) -> list:
    """Ordered list of device indexes (plus `None` for "system default") to try.

    `devices` is sounddevice's `query_devices()` output — dicts with `name` and
    `max_input_channels`. Only inputs are considered.
    """
    policy = policy if policy in POLICIES else "preferred"
    inputs = [(i, d) for i, d in enumerate(devices)
              if (d.get("max_input_channels") or 0) > 0]

    external = [i for i, d in inputs if is_external(d.get("name", ""))]
    internal = [i for i, d in inputs if is_internal(d.get("name", ""))]
    others = [i for i, _ in inputs if i not in external and i not in internal]

    order: list = []

    def push(item):
        if item not in order:
            order.append(item)

    if policy == "external_first":
        for i in external:
            push(i)
        push(None)                       # system default
        for i in others:
            push(i)
        for i in internal:
            push(i)
    elif policy == "system_default":
        push(None)
        for i in external + others + internal:
            push(i)
    else:  # preferred
        if preferred is not None:
            push(preferred)
        push(None)
        for i in external + others + internal:
            push(i)

    # The chosen device must still be reachable as a last resort.
    if default_index is not None:
        push(default_index)
    return order


def should_switch(policy: str, current_name: str, devices: list[dict]) -> bool:
    """Under `external_first`, is a better mic available than the one we're on?

    Deliberately one-directional: it only ever moves *up* to an external mic,
    or off one that has gone away. It never second-guesses a working external
    mic, because "Svara keeps changing my microphone" is a worse bug than
    "Svara didn't notice my new headset".
    """
    if policy != "external_first":
        return False
    names = [d.get("name", "") for d in devices
             if (d.get("max_input_channels") or 0) > 0]
    have_external = any(is_external(n) for n in names)
    on_external = is_external(current_name)
    if have_external and not on_external:
        return True
    if on_external and current_name not in names:
        return True
    return False
