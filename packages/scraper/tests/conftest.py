import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))  # rende importabile tests/fakesite.py


def fx(name: str) -> str:
    return (TESTS / "fixtures" / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_html():
    return fx
