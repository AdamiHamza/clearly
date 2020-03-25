import re
from unittest import mock

import grpc
import pytest
from celery import states

from clearly.client import ClearlyClient
from clearly.protos import clearly_pb2
from clearly.utils import worker_states


@pytest.fixture
def mocked_client():
    with mock.patch('clearly.client.grpc.insecure_channel'), \
         mock.patch('clearly.client.clearly_pb2_grpc.ClearlyServerStub'):
        yield ClearlyClient()


@pytest.fixture
def mocked_display(mocked_client):
    with mock.patch('clearly.client.ClearlyClient._display_task'), \
         mock.patch('clearly.client.ClearlyClient._display_worker'):
        yield mocked_client


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


@pytest.fixture(params=sorted(states.ALL_STATES))
def task_state_type(request):
    yield request.param


@pytest.fixture(params=sorted(worker_states.ALL_STATES))
def worker_state_type(request):
    yield request.param


# noinspection PyProtectedMember
def test_client_reset(mocked_client):
    mocked_client.reset()
    assert mocked_client._stub.reset_tasks.call_count == 1


# noinspection PyProtectedMember
def test_client_seen_tasks_do_print(mocked_client, capsys):
    inner_tasks = ['app{i}.task{i}'.format(i=i) for i in range(3)]
    tasks = clearly_pb2.SeenTasksMessage()
    tasks.task_types.extend(inner_tasks)
    mocked_client._stub.seen_tasks.return_value = tasks
    mocked_client.seen_tasks()
    generated = filter(None, capsys.readouterr().out.split('\n'))
    assert all(any(re.search(re.escape(t), x) for x in generated) for t in inner_tasks)


# noinspection PyProtectedMember
def test_client_capture_task(tristate, bool1, bool2, mocked_display):
    task = clearly_pb2.TaskMessage(
        name='name', routing_key='routing_key', uuid='uuid', retries=2,
        args='args', kwargs='kwargs', result='result', traceback='traceback',
        timestamp=123.1, state='ANY', created=False,
    )
    mocked_display._stub.capture_realtime.return_value = \
        (clearly_pb2.RealtimeEventMessage(task=task),)
    mocked_display.capture(params=tristate, success=bool1, error=bool2)
    mocked_display._display_task.assert_called_once_with(task, tristate, bool1, bool2)


# noinspection PyProtectedMember
def test_client_capture_ignore_unknown(mocked_display):
    mocked_display._stub.capture_realtime.return_value = (clearly_pb2.RealtimeEventMessage(),)
    mocked_display.capture()
    mocked_display._display_task.assert_not_called()


# noinspection PyProtectedMember
def test_client_capture_worker(bool1, mocked_display):
    worker = clearly_pb2.WorkerMessage(
        hostname='hostname', pid=12000, sw_sys='sw_sys', sw_ident='sw_ident',
        sw_ver='sw_ver', loadavg=[1.0, 2.0, 3.0], processed=5432, state='state',
        alive=True, freq=5, last_heartbeat=234.2,
    )
    mocked_display._stub.capture_realtime.return_value = \
        (clearly_pb2.RealtimeEventMessage(worker=worker),)
    mocked_display.capture(stats=bool1)
    mocked_display._display_worker.assert_called_once_with(worker, bool1)


# noinspection PyProtectedMember
@pytest.mark.parametrize('method, stub, params', [
    ('capture_tasks', 'capture_realtime', 0),
    ('capture_workers', 'capture_realtime', 0),
    ('capture', 'capture_realtime', 0),
    ('stats', 'get_stats', 0),
    ('tasks', 'filter_tasks', 0),
    ('workers', 'filter_workers', 0),
    ('task', 'find_task', 1),
    ('seen_tasks', 'seen_tasks', 0),
    ('reset', 'reset_tasks', 0),
])
def test_client_methods_have_user_friendly_errors(method, stub, params, mocked_display, capsys):
    exc = grpc.RpcError()
    exc.code, exc.details = lambda: 'StatusCode', lambda: 'details'
    getattr(mocked_display._stub, stub).side_effect = exc

    getattr(mocked_display, method)(*('x',) * params)
    # NOTE: the day I have a method with a non-string param, this will break.

    generated = capsys.readouterr().out
    assert 'Server communication error' in generated
    assert 'StatusCode' in generated
    assert 'details' in generated


# noinspection PyProtectedMember
@pytest.mark.parametrize('method, stub, params', [
    ('capture_tasks', 'capture_realtime', 0),
    ('capture_workers', 'capture_realtime', 0),
    ('capture', 'capture_realtime', 0),
    ('stats', 'get_stats', 0),
    ('tasks', 'filter_tasks', 0),
    ('workers', 'filter_workers', 0),
    ('task', 'find_task', 1),
    ('seen_tasks', 'seen_tasks', 0),
    ('reset', 'reset_tasks', 0),
])
def test_client_methods_trigger_errors_when_debugging(method, stub, params, mocked_display):
    getattr(mocked_display._stub, stub).side_effect = grpc.RpcError()
    mocked_display.debug = True

    with pytest.raises(grpc.RpcError):
        getattr(mocked_display, method)(*('x',) * params)
        # NOTE: the day I have a method with a non-string param, this will break.


def test_client_capture_tasks(mocked_client):
    with mock.patch.object(mocked_client, 'capture') as mocked_capture:
        mocked_client.capture_tasks()
        mocked_capture.assert_called_once_with(
            workers='.', negate_workers=True, stats=False,
            pattern=mock.ANY, negate=mock.ANY, params=mock.ANY, success=mock.ANY, error=mock.ANY,
        )


def test_client_capture_workers(mocked_client):
    with mock.patch.object(mocked_client, 'capture') as mocked_capture:
        mocked_client.capture_workers()
        mocked_capture.assert_called_once_with(
            pattern='.', negate=True, params=False, success=False, error=False,
            workers=mock.ANY, negate_workers=mock.ANY, stats=mock.ANY,
        )


# noinspection PyProtectedMember
def test_client_stats_do_print(mocked_client, capsys):
    data = dict(task_count=1234, event_count=5678, len_tasks=2244, len_workers=333)
    mocked_client._stub.get_stats.return_value = clearly_pb2.StatsMessage(**data)
    mocked_client.stats()
    generated = capsys.readouterr().out
    assert all(re.search(str(x), generated) for x in data.values())


# noinspection PyProtectedMember
def test_client_tasks(tristate, bool1, bool2, mocked_display):
    task = clearly_pb2.TaskMessage(
        name='name', routing_key='routing_key', uuid='uuid', retries=2,
        args='args', kwargs='kwargs', result='result', traceback='traceback',
        timestamp=123.1, state='ANY', created=False,
    )
    mocked_display._stub.filter_tasks.return_value = (task,)
    mocked_display.tasks(params=tristate, success=bool1, error=bool2)
    mocked_display._display_task.assert_called_once_with(task, tristate, bool1, bool2)


# noinspection PyProtectedMember
def test_client_workers(bool1, mocked_display):
    worker = clearly_pb2.WorkerMessage(
        hostname='hostname', pid=12000, sw_sys='sw_sys', sw_ident='sw_ident',
        sw_ver='sw_ver', loadavg=[1.0, 2.0, 3.0], processed=5432, state='state',
        alive=True, freq=5, last_heartbeat=234.2,
    )
    mocked_display._stub.filter_workers.return_value = (worker,)
    mocked_display.workers(stats=bool1)
    mocked_display._display_worker.assert_called_once_with(worker, bool1)


# noinspection PyProtectedMember
def test_client_task(bool1, mocked_display):
    task = clearly_pb2.TaskMessage(
        name='name', routing_key='routing_key', uuid='uuid', retries=2,
        args='args', kwargs='kwargs', result='result', traceback='traceback',
        timestamp=123.1, state='state', created=False,
    )
    mocked_display._stub.find_task.return_value = task if bool1 else clearly_pb2.TaskMessage()
    mocked_display.task('uuid')
    if bool1:
        mocked_display._display_task.assert_called_once_with(task, True, True, True)
    else:
        mocked_display._display_task.assert_not_called()


@pytest.fixture(params=(None, 'traceback'))
def task_tb(request):
    yield request.param


@pytest.fixture(params=(None, '', 'False', '0', "'nice'"))
def task_result(request):
    yield request.param


# noinspection PyProtectedMember
def test_client_display_task(task_result, tristate, bool1, bool2, bool3,
    task = clearly_pb2.TaskMessage(
                             task_state_type, task_tb, mocked_client, capsys, strip_colors):
        name='name', routing_key='routing_key', uuid='uuid', retries=2,
        args='args123', kwargs='kwargs', result=task_result, traceback=task_tb,
        timestamp=123.1, state=task_state_type, created=bool3,
    )

    with mock.patch('clearly.client.ClearlyClient._task_state') as m_task_state:
        mocked_client._display_task(task, params=tristate, success=bool1, error=bool2)
    generated = strip_colors(capsys.readouterr().out)

    assert task.name in generated
    assert task.uuid in generated

    if bool3:
        assert task.routing_key in generated
        m_task_state.assert_not_called()
    else:
        m_task_state.assert_called_once_with(task.state)

    show_result = (task.state in states.PROPAGATE_STATES and bool2) \
        or (task.state == states.SUCCESS and bool1)

    # params
    first_seen = bool(tristate) and task.created
    result = tristate is not False and show_result
    tristate = first_seen or result
    assert tristate == (task.args in generated)
    assert tristate == (task.kwargs in generated)

    # result
    if show_result:
        assert '==> ' + (task_result or task_tb or ':)') in generated


@pytest.fixture(params=(None, 123456789))
def worker_heartbeat(request):
    yield request.param


# noinspection PyProtectedMember
def test_client_display_worker(bool1, bool2, worker_state_type, worker_heartbeat,
    worker = clearly_pb2.WorkerMessage(
                               mocked_client, capsys, strip_colors):
        hostname='hostname', pid=12000, sw_sys='sw_sys', sw_ident='sw_ident',
        sw_ver='sw_ver', loadavg=[1.0, 2.0, 3.0], processed=5432, alive=bool2,
        state=worker_state_type, freq=5, last_heartbeat=worker_heartbeat,
    )

    with mock.patch('clearly.client.ClearlyClient._worker_state') as m_worker_state:
        mocked_client._display_worker(worker, stats=bool1)
    generated = strip_colors(capsys.readouterr().out)

    m_worker_state.assert_called_once_with(worker_state_type)
    assert worker.hostname in generated
    assert str(worker.pid) in generated

    # stats
    assert bool1 == ('sw_sys' in generated)
    assert bool1 == ('sw_ident' in generated)
    assert bool1 == ('sw_ver' in generated)
    assert bool1 == ('[1.0, 2.0, 3.0]' in generated)

    # alive
    assert (bool1 and bool2) == ('heartbeat:' in generated)


# noinspection PyProtectedMember
def test_client_task_state(task_state_type, mocked_client):
    result = mocked_client._task_state(task_state_type)
    assert task_state_type in result


# noinspection PyProtectedMember
def test_client_worker_state(worker_state_type, mocked_client):
    result = mocked_client._worker_state(worker_state_type)
    assert worker_state_type in result
