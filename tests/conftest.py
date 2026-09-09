"""Session-wide hermeticity.

The dedup cache dir and the memory DB used to default into the repo tree /
live data. Every test in this suite must be disk-hermetic:

* ``HOUSE_CACHE_DIR`` → a session-scoped tmp dir (was: repo ``cache/`` —
  tests that built a ``House()`` without an override wrote real cache files
  into the repo tree);
* ``HOUSE_MEMORY_DB`` → a session-scoped tmp db, so a test that builds
  ``app = build_app()`` can never touch the live ``data/memory.db``.
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _hermetic_house_dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("house_hermetic")
    cache = root / "cache"
    db = root / "memory.db"
    cache.mkdir(parents=True, exist_ok=True)
    import os
    os.environ["HOUSE_CACHE_DIR"] = str(cache)
    os.environ["HOUSE_MEMORY_DB"] = str(db)
    # Each test that needs isolation still passes its own tmp_path when the
    # test semantics require a FRESH db (the env value only covers accidental
    # build_app() imports without an explicit override).
    yield
    os.environ.pop("HOUSE_CACHE_DIR", None)
    os.environ.pop("HOUSE_MEMORY_DB", None)
