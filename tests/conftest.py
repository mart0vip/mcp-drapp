import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def corpus_dir():
    """Corpus real. Los datos son clinicos: se leen, nunca se commitean."""
    d = ROOT / "data" / "hce"
    if not d.exists() or not any(d.glob("*.json")):
        pytest.skip("corpus ausente; correr scripts/fetch_hce.py")
    return d
