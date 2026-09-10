"""Compatibility shim — prefer ``music_organizer.domain.matching``."""

from music_organizer.domain.matching import *  # noqa: F401,F403
from music_organizer.domain.matching import (  # noqa: F401
    DEFAULT_ALBUM_MIN_SCORE,
    DEFAULT_RECORDING_MIN_SCORE,
    normalize_album_key,
    pick_best_recording,
    score_recording_match,
    score_release_for_library,
    select_best_release,
    should_accept_recording,
    should_accept_release,
)
