import pytest
from responses import RequestsMock


@pytest.fixture
def responses():
    with RequestsMock() as rsps:
        yield rsps
