import pytest

from app.cases import load_cases
from app.resolver import Resolver


@pytest.fixture(scope="session")
def cases():
    return load_cases()


@pytest.fixture(scope="session")
def resolver(cases):
    return Resolver(cases)
