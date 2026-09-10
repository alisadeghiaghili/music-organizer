#!/usr/bin/env python3
"""Pure matching and release-policy helpers (no I/O).

Album-centric policy for Music Organizer:
  * Prefer the oldest studio album over newer remasters/compilations.
  * Prefer the release title that matches the user's album tag.
  * Never invent track numbers.
  * Score recording candidates instead of taking search result [0].
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence

# Thresholds (Phase B defaults). Overridable via config later if needed.
DEFAULT_RECORDING_MIN_SCORE = 0.82
DEFAULT_ALBUM_MIN_SCORE = 55.0

_SECONDARY_PENALTY = {
    "compilation": 40.0,
    "greatest hits": 40.0,
    "best of": 40.0,
    "live": 25.0,
    "remaster": 10.0,
    "remix": 15.0,
    "soundtrack": 20.0,
    "tribute": 30.0,
    "karaoke": 35.0,
    "bootleg": 45.0,
}

_YEAR_PREFIX_RE = re.compile(r"^\d{3,4}\s*-\s*")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalize_album_key(folder_name: str) -> str:
    """Normalize an album folder name into a merge key.

    Keeps Unicode letters (Persian, Arabic, Cyrillic, CJK, …) so distinct
    non-ASCII albums do not collapse into one empty bucket. Falls back to a
    stable escaped key when the stripped name would be empty.

    Args:
        folder_name: Album folder name, optionally with a year prefix.

    Returns:
        Lowercased, punctuation-free key. Never an empty string unless the
        input itself is empty/whitespace.

    Examples:
        >>> normalize_album_key("2020 - Greatest Hits!")
        'greatesthits'
        >>> normalize_album_key("آبی")
        'آبی'
    """
    name = _YEAR_PREFIX_RE.sub("", str(folder_name)).strip()
    if not name:
        return ""
    folded = unicodedata.normalize("NFKC", name).casefold()
    folded = _PUNCT_RE.sub(" ", folded)
    folded = _SPACE_RE.sub(" ", folded).strip()
    if not folded:
        # Keep distinct identity for symbol-only names.
        return "sym_" + re.sub(r"[^0-9a-z]+", "", name.casefold())[:16] or "sym"
    return folded.replace(" ", "")


def _year_from_release(release: Mapping[str, Any]) -> int | None:
    date = str(release.get("date") or "")
    year_part = date[:4]
    if year_part.isdigit():
        year = int(year_part)
        if 1000 <= year <= 2999:
            return year
    return None


def _type_bonus(release: Mapping[str, Any]) -> float:
    rtype = str(release.get("primary-type") or "").strip().casefold()
    secondary = [str(s).strip().casefold() for s in release.get("secondary-types") or []]
    bonus = 0.0
    if rtype == "album":
        bonus += 20.0
    elif rtype == "single":
        bonus += 5.0
    elif rtype == "ep":
        bonus += 8.0
    for sec in secondary:
        bonus -= _SECONDARY_PENALTY.get(sec, 12.0)
    return bonus


def _similarity(a: str, b: str) -> float:
    """Lightweight token-set similarity in [0, 1] without external deps."""
    ta = set(_normalize_for_sim(a).split())
    tb = set(_normalize_for_sim(b).split())
    if not ta or not tb:
        return 1.0 if (not ta and not tb) else 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _normalize_for_sim(text: str) -> str:
    folded = unicodedata.normalize("NFKC", str(text)).casefold()
    folded = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", folded)  # drop bracketed editions
    folded = _PUNCT_RE.sub(" ", folded)
    folded = _SPACE_RE.sub(" ", folded).strip()
    return folded


def score_release_for_library(
    release: Mapping[str, Any],
    *,
    desired_album: str = "",
    desired_artist: str = "",
    prefer_oldest: bool = True,
    reference_year: int | None = None,
) -> float:
    """Score how well a MusicBrainz release fits this library entry.

    Args:
        release: MusicBrainz release object (title/date/types/...).
        desired_album: User's existing album tag (may be empty).
        desired_artist: User's artist tag (reserved for future weighting).
        prefer_oldest: When True, earlier years win among equal album matches.
        reference_year: Year used for recency scoring; defaults to newest
            candidate year when omitted by the caller.

    Returns:
        Score roughly in [0, 100]. Higher is better.

    Examples:
        >>> score_release_for_library(
        ...     {"title": "OK Computer", "date": "1997-05-21",
        ...      "primary-type": "Album", "secondary-types": []},
        ...     desired_album="OK Computer")
        100.0
    """
    title = str(release.get("title") or "")
    year = _year_from_release(release)

    # Album similarity is the dominant signal when the user knows the album.
    if desired_album:
        sim = _similarity(title, desired_album)
        album_score = sim * 55.0
    else:
        # Without a desired album, treat all studio albums equally on name.
        album_score = 40.0

    type_score = _type_bonus(release)

    year_score = 0.0
    if year is not None:
        if prefer_oldest:
            # Older is better: invert year into a small bonus (1900s preferred).
            year_score = max(0.0, (2100 - year) / 200.0) * 15.0
        else:
            year_score = min(15.0, max(0.0, (year - 1950) / 5.0))

    # Presence of media/track hints helps track resolution later.
    media = release.get("media") or release.get("mediums") or []
    track_hint = 10.0 if media else 0.0

    score = album_score + type_score + year_score + track_hint
    return round(max(0.0, min(100.0, score)), 2)


def select_best_release(
    releases: Sequence[Mapping[str, Any]],
    *,
    desired_album: str = "",
    prefer_oldest: bool = True,
) -> tuple[Mapping[str, Any] | None, int | None]:
    """Select the release that best matches library policy.

    Prefers the user's album title, then studio albums, then the oldest year.

    Args:
        releases: MusicBrainz release list from a recording (or album search).
        desired_album: Existing album tag used as the primary target.
        prefer_oldest: Prefer earlier release dates on ties.

    Returns:
        Tuple ``(release_or_None, year_or_None)``.

    Examples:
        >>> select_best_release(
        ...     [{"title": "X", "date": "2011-01-01", "primary-type": "Album",
        ...       "secondary-types": []},
        ...      {"title": "X", "date": "1973-01-01", "primary-type": "Album",
        ...       "secondary-types": []}],
        ...     desired_album="X")[1]
        1973
    """
    if not releases:
        return None, None

    scored: list[tuple[float, Mapping[str, Any], int | None]] = []
    for rel in releases:
        year = _year_from_release(rel)
        s = score_release_for_library(
            rel, desired_album=desired_album, prefer_oldest=prefer_oldest
        )
        scored.append((s, rel, year))

    # Prefer higher score; on ties prefer older year when prefer_oldest.
    scored.sort(
        key=lambda item: (
            -item[0],
            item[2] if prefer_oldest else -(item[2] or 0),
            str(item[1].get("id") or ""),
        )
    )
    best_score, best, year = scored[0]
    return best, year


def score_recording_match(
    query_artist: str,
    query_title: str,
    candidate_artist: str,
    candidate_title: str,
    *,
    query_album: str = "",
    candidate_album: str = "",
) -> float:
    """Score a MusicBrainz recording candidate against local tags.

    Args:
        query_artist: Local artist tag.
        query_title: Local title tag.
        candidate_artist: Candidate artist from search.
        candidate_title: Candidate title from search.
        query_album: Optional local album tag (small bonus only).
        candidate_album: Optional candidate album (small bonus only).

    Returns:
        Score in [0, 1]. Weighted artist+title with a small album bonus.

    Examples:
        >>> score_recording_match("A", "T", "A", "T")
        1.0
    """
    artist_sim = _similarity(query_artist, candidate_artist)
    title_sim = _similarity(query_title, candidate_title)
    album_sim = _similarity(query_album, candidate_album) if query_album else 0.0

    score = 0.45 * artist_sim + 0.50 * title_sim
    if query_album:
        score += 0.05 * album_sim
    return round(min(1.0, score), 4)


def should_accept_recording(
    score: float, threshold: float = DEFAULT_RECORDING_MIN_SCORE
) -> bool:
    """Return True when a recording candidate clears the acceptance bar.

    Args:
        score: Output of :func:`score_recording_match`.
        threshold: Minimum score (inclusive).

    Returns:
        Whether the recording may be used for metadata.

    Examples:
        >>> should_accept_recording(0.90)
        True
        >>> should_accept_recording(0.40)
        False
    """
    return score >= threshold


def should_accept_release(
    score: float, threshold: float = DEFAULT_ALBUM_MIN_SCORE
) -> bool:
    """Return True when a release candidate clears the album acceptance bar.

    Args:
        score: Output of :func:`score_release_for_library`.
        threshold: Minimum score (inclusive).

    Returns:
        Whether the release may supply album/year/track metadata.

    Examples:
        >>> should_accept_release(80.0)
        True
        >>> should_accept_release(20.0)
        False
    """
    return score >= threshold


def pick_best_recording(
    candidates: Sequence[Mapping[str, Any]],
    *,
    query_artist: str,
    query_title: str,
    query_album: str = "",
    min_score: float = DEFAULT_RECORDING_MIN_SCORE,
) -> tuple[Mapping[str, Any] | None, float]:
    """Pick the best-scoring recording candidate above the threshold.

    Args:
        candidates: MusicBrainz recording objects (must include title and
            artist-credit when available).
        query_artist: Local artist tag.
        query_title: Local title tag.
        query_album: Optional local album tag.
        min_score: Minimum accepted recording score.

    Returns:
        Tuple ``(recording_or_None, score)``. Score is 0.0 when none accepted.

    Examples:
        >>> pick_best_recording([], query_artist="A", query_title="T")
        (None, 0.0)
    """
    best: Mapping[str, Any] | None = None
    best_score = 0.0
    for rec in candidates:
        cand_title = str(rec.get("title") or "")
        credits = rec.get("artist-credit") or []
        cand_artist = ""
        if credits:
            cand_artist = str((credits[0].get("artist") or {}).get("name") or "")
        s = score_recording_match(
            query_artist, query_title, cand_artist, cand_title,
            query_album=query_album,
            candidate_album="",  # recording object may not carry album
        )
        if s > best_score:
            best_score = s
            best = rec
    if best is None or not should_accept_recording(best_score, min_score):
        return None, best_score if best is not None else 0.0
    return best, best_score
