# -*- coding: utf-8 -*-
import pytest

from mozci import config
from mozci.util import req


@pytest.fixture
def clear_sessions():
    req.get_session.cache_clear()
    yield
    req.get_session.cache_clear()


@pytest.fixture
def user_agent():
    old_user_agent = config["user_agent"]
    yield
    config.set(user_agent=old_user_agent)


def test_configured_user_agent(responses, clear_sessions, user_agent):
    config.set(user_agent="my-project")
    session = req.get_session()
    assert session.headers["User-Agent"] == "my-project"

    responses.add(responses.GET, "https://hg.mozilla.org/test", json={})
    session.get("https://hg.mozilla.org/test")
    assert responses.calls[0].request.headers["User-Agent"] == "my-project"


def test_missing_user_agent(clear_sessions, user_agent):
    del config._config["user_agent"]
    with pytest.raises(KeyError, match="user_agent"):
        req.get_session()
