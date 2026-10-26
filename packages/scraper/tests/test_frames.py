import pytest

from scraper import frames


def test_frame_rejects_unknown_keys():
    row = {k: None for k in frames.SEGMENTS} | {"extra": 1}
    with pytest.raises(ValueError, match="sconosciute"):
        frames.frame([row], frames.SEGMENTS)


def test_frame_rejects_missing_keys():
    with pytest.raises(ValueError, match="mancanti"):
        frames.frame([{"source": "x"}], frames.SEGMENTS)


def test_frame_empty_has_schema():
    df = frames.frame([], frames.EVENTS)
    assert df.columns == list(frames.EVENTS) and len(df) == 0
