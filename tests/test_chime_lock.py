"""Chimes must serialize on PORTAUDIO_LOCK: two concurrent sd.play() calls
crashed PortAudio ("double free") when 'recording' and 'locked' chimed at once."""
import sys
import threading
import time
import unittest
from unittest import mock

from mywhisper import app, audio


@unittest.skipIf(sys.platform == "win32", "Linux chime path only")
class ChimeLockTest(unittest.TestCase):
    def test_chimes_never_overlap(self):
        inside, overlap = [0], [False]

        def fake_play(*_a, **_k):
            self.assertTrue(audio.PORTAUDIO_LOCK.locked())
            inside[0] += 1
            overlap[0] |= inside[0] > 1
            time.sleep(0.02)
            inside[0] -= 1

        with mock.patch("sounddevice.play", fake_play):
            app._chime(300); app._chime(400)
            time.sleep(0.3)
        self.assertFalse(overlap[0])


if __name__ == "__main__":
    unittest.main()
