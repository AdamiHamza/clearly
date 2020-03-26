import re
from typing import Callable

import pytest
from celery import states as task_states

from clearly.utils import worker_states


@pytest.fixture(params=sorted(task_states.ALL_STATES))
def task_state_type(request):
    yield request.param


@pytest.fixture(params=sorted(task_states.ALL_STATES.union(set('TRUNCATE'))))
def task_state_type_truncating(request):
    # task results only make sense in success, so to test truncate resolving mechanism,
    # I can't just insert a bool, as all combinations would not make sense.
    truncating = request.param == 'TRUNCATE'
    yield task_states.SUCCESS if truncating else request.param, truncating


@pytest.fixture(params=sorted(worker_states.ALL_STATES))
def worker_state_type(request):
    yield request.param


@pytest.fixture(params=sorted(worker_states.TYPES.keys()))
def worker_event_type(request):
    yield request.param


@pytest.fixture(params=(True, False))
def bool1(request):
    yield request.param


@pytest.fixture(params=(True, False))
def bool2(request):
    yield request.param


@pytest.fixture(params=(True, False))
def bool3(request):
    yield request.param


@pytest.fixture(params=(True, False, None))
def tristate(request):
    yield request.param


@pytest.fixture
def strip_colors() -> Callable[[str], str]:
    def actual(text: str) -> str:
        return re.sub(r'\033\[.+?m', '', text)

    return actual
