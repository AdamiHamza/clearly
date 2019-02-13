from queue import Queue
from unittest import mock
from unittest.mock import DEFAULT, PropertyMock

import pytest
from celery import states
from celery.events.state import Task, Worker

from clearly.event_core.event_listener import EventListener
from clearly.utils import worker_states


@pytest.fixture
def listener():
    with mock.patch('threading.Thread'), \
         mock.patch('threading.Event'), \
         mock.patch('clearly.event_core.event_listener.Celery'):
        # noinspection PyTypeChecker
        yield EventListener('', Queue())


@pytest.fixture(params=(False, True))
def bool1(request):
    return request.param


@pytest.fixture(params=(False, True))
def bool2(request):
    return request.param


@pytest.fixture(params=sorted(states.ALL_STATES))
def task_state_type(request):
    yield request.param


@pytest.fixture(params=sorted(worker_states.ALL_STATES))
def worker_state_type(request):
    yield request.param


@pytest.mark.parametrize('raw_event', [
    dict(type='task-received'),
    dict(type='worker-heartbeat'),
    dict(type='cool-event'),
])
def test_listener_process_event(raw_event, listener):
    with mock.patch.multiple(listener,
                             _process_task_event=DEFAULT,
                             _process_worker_event=DEFAULT) as mtw:
        listener._process_event(raw_event)
        name, _, _ = raw_event['type'].partition('-')
        m = dict(task=mtw['_process_task_event'],
                 worker=mtw['_process_worker_event']).get(name)
        if m:
            m.assert_called_once_with(raw_event)
        else:
            all(m.assert_not_called() for m in mtw.values())


def test_listener_process_task(bool1, bool2, task_state_type, listener):
    with mock.patch.object(listener.memory.tasks, 'get') as tg, \
            mock.patch.object(listener.memory, 'event') as mev, \
            mock.patch('clearly.event_core.event_listener.immutable_task') as it, \
            mock.patch('clearly.event_core.event_listener.EventListener.compile_task_result') as ctr:
        tg.return_value = Task('uuid', state='pre_state') if bool1 else None
        task = Task('uuid', state=task_state_type, result='ok')
        mev.return_value = (task, ''), ''
        if bool2:
            ctr.side_effect = SyntaxError

        listener._process_task_event(dict(uuid='uuid'))

    if task_state_type == states.SUCCESS:
        ctr.assert_called_once_with(task)
        if bool2:
            listener._app.AsyncResult.assert_called_once_with('uuid')
    it.assert_called_once_with(task, task_state_type, 'pre_state' if bool1 else states.PENDING, not bool1)


def test_listener_process_worker(bool1, listener):
    with mock.patch.object(listener.memory.workers, 'get') as wg, \
            mock.patch.object(listener.memory, 'event') as mev, \
            mock.patch('clearly.event_core.event_listener.immutable_worker') as it:
        worker_pre = Worker('hostname')
        wg.return_value = worker_pre if bool1 else None
        worker = Worker('hostname')
        mev.return_value = (worker, ''), ''

        with mock.patch('celery.events.state.Worker.status_string', new_callable=PropertyMock) as wss:
            wss.side_effect = (('pre_state',) if bool1 else ()) + ('state',)
            listener._process_worker_event(dict(hostname='hostname'))

    it.assert_called_once_with(worker, 'state', 'pre_state' if bool1 else worker_states.OFFLINE, not bool1)


@pytest.mark.parametrize('worker_version, num_calls, expected', [
    ('3.nice', 2, 'a'),
    ('4.cool', 1, 'x'),
])
def test_listener_celery_result_compiler(worker_version, num_calls, expected):
    task = mock.Mock()
    task.result = 'x'
    task.worker.sw_ver = worker_version

    with mock.patch('clearly.event_core.event_listener.safe_compile_text') as msc:
        msc.side_effect = ('a', 'b')
        result = EventListener.compile_task_result(task)

    assert msc.call_count == num_calls
    assert result == expected
