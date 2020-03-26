import functools
from datetime import datetime
from typing import Any, Callable, Iterable, Optional

import grpc
from about_time import about_time
from about_time.core import HandleStats
from celery import states as task_states

from .code_highlighter import traceback_highlighter_factory, typed_code
from .protos.clearly_pb2 import CaptureRequest, Empty, FilterTasksRequest, FilterWorkersRequest, \
    FindTaskRequest, PatternFilter, TaskMessage, WorkerMessage
from .protos.clearly_pb2_grpc import ClearlyServerStub
from .safe_compiler import safe_compile_text
from .utils import worker_states
from .utils.colors import Colors

HEADER_SIZE = 8
HEADER_PADDING = ' ' * HEADER_SIZE
EMPTY = Colors.DIM(':)')
DIM_NONE = Colors.CYAN_DIM('None')
TRACEBACK_HIGHLIGHTER = traceback_highlighter_factory()


def set_user_friendly_errors(fn: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(fn)
    def inner(self: 'ClearlyClient', *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except grpc.RpcError as e:
            if self._debug:
                raise
            # noinspection PyUnresolvedReferences
            print('{}: {} ({})'.format(
                Colors.BOLD('Server communication error'),
                Colors.RED(e.details()),
                Colors.DIM(e.code())
            ))
        except UserWarning as e:
            print(Colors.RED(e))

    return inner


class ClearlyClient:
    """Main client object, which interfaces with the Clearly server backend, sends
    commands and displays captured events.

    Attributes:
        debug: if True, let the ugly  errors be seen, humanizes them otherwise
        _stub: the rpc communication stub instance

    """

    def __init__(self, host: str = 'localhost', port: int = 12223, debug: bool = False):
        """Construct a Clearly Client instance.
        
        Args:
            host: the hostname of the server
            port: the port of the server

        """
        self._debug = debug
        channel = grpc.insecure_channel('{}:{}'.format(host, port))
        self._stub = ClearlyServerStub(channel)

    def capture_tasks(self, tasks: Optional[str] = None, params: Optional[bool] = None,
                      success: bool = False, error: bool = True) -> None:
        """Start capturing task events in real time, so you can instantly see exactly
        what your publishers and workers are doing. Filter as much as you can to find
        what you need, and don't worry as the Clearly Server will still seamlessly
        handle all tasks updates.

        Currently you can filter tasks by name, routing key or state.
        Insert an '!' in the first position to select those that do not match criteria.

        This runs in the foreground. Press CTRL+C at any time to stop it.

        Args:
            Filter args:
            ------------

            tasks: a simple pattern to filter tasks.
                ex.: 'email' to find values containing that word anywhere
                     'failure|rejected|revoked' to find tasks with problem
                     '^trigger|^email' to find values starting with any of those words
                     'trigger.*123456' to find values with those words in that sequence
                     '!^trigger|^email' to filter values not starting with both those words

            Display args:
            -------------

            params: if True shows args and kwargs in the first and
                last seen states, if False never shows, and if None follows the
                success and error arguments.
                default is None
            success: if True shows successful tasks' results.
                default is False
            error: if True shows failed and retried tasks' tracebacks.
                default is True, as you're monitoring to find errors, right?

        """
        self.capture(tasks=tasks, params=params, success=success, error=error, workers='!')

    def capture_workers(self, workers: Optional[str] = None, stats: bool = False) -> None:
        """Start capturing worker events in real time, so you can instantly see exactly
        what your workers states are. Filter as much as you can to find
        what you need, and don't worry as the Clearly Server will still seamlessly
        handle all tasks and workers updates.

        Currently you can filter workers by hostname.
        Insert an '!' in the first position to select those that do not match criteria.

        This runs in the foreground. Press CTRL+C at any time to stop it.

        Args:
            Filter args:
            ------------

            workers: a simple pattern to filter workers.
                ex.: 'email' to find values containing that word anywhere
                     'service|priority' to find values containing any of those words
                     '!service|priority' to find values not containing both those words

            Display args:
            -------------

            stats: if True shows complete workers' stats, default is False

        """
        self.capture(workers=workers, stats=stats, tasks='!')

    @set_user_friendly_errors
    def capture(self, tasks: Optional[str] = None, workers: Optional[str] = None,
                params: Optional[bool] = None, success: bool = False, error: bool = True,
                stats: bool = False) -> None:
        """Start capturing all events in real time, so you can instantly see exactly
        what your publishers and workers are doing. Filter as much as you can to find
        what you need, and don't worry as the Clearly Server will still seamlessly
        handle all tasks and workers updates.

        This runs in the foreground. Press CTRL+C at any time to stop it.

        See Also:
            ClearlyClient#capture_tasks()
            ClearlyClient#capture_workers()

        """

        tasks_filter = ClearlyClient._parse_pattern(tasks)
        workers_filter = ClearlyClient._parse_pattern(workers)
        if not tasks_filter and not workers_filter:
            raise UserWarning('Nothing would be selected.')

        request = CaptureRequest(
            tasks_capture=tasks_filter, workers_capture=workers_filter,
        )
        try:
            for realtime in self._stub.capture_realtime(request):
                if realtime.HasField('task'):
                    ClearlyClient._display_task(realtime.task, params, success, error)
                elif realtime.HasField('worker'):
                    ClearlyClient._display_worker(realtime.worker, stats)
                else:
                    print('unknown event:', realtime)
                    break
        except KeyboardInterrupt:
            pass

    @set_user_friendly_errors
    def stats(self) -> None:
        """List some metrics about the capturing system itself, which of course
        reflects the actual celery pool being monitored.

        Shows:
            Tasks processed: number of tasks processed, including retries
            Events processed: number of events processed, including workers and heartbeats
            Tasks stored: number of unique tasks processed
            Workers stored: number of unique workers seen

        """
        stats = self._stub.get_stats(Empty())
        print(Colors.DIM('Processed:'),
              '\ttasks', Colors.RED(stats.task_count),
              '\tevents', Colors.RED(stats.event_count))
        print(Colors.DIM('Stored:'),
              '\ttasks', Colors.RED(stats.len_tasks),
              '\tworkers', Colors.RED(stats.len_workers))

    @set_user_friendly_errors
    def tasks(self, tasks: Optional[str] = None, limit: Optional[int] = None, reverse: bool = True,
              params: Optional[bool] = None, success: bool = False, error: bool = True) -> None:
        """Fetch current data from past tasks.

        Note that the `limit` field is just a hint, it may not be accurate.
        Even the total number of tasks fetched may be slightly different than
        the server `max_tasks` setting.

        Args:
            Filter args:
            ------------

            tasks: a simple pattern to filter tasks.
                ex.: 'email' to find values containing that word anywhere
                     'failure|rejected|revoked' to find tasks with problem
                     '^trigger|^email' to find values starting with any of those words
                     'trigger.*123456' to find values with those words in that sequence
                     '!^trigger|^email' to filter values not starting with both those words
            limit: the maximum number of events to fetch, fetches all if None or 0 (default).
            reverse: if True (default), shows the most recent first

            Display args:
            -------------

            params: if True shows args and kwargs in the first and
                last seen states, if False never shows, and if None follows the
                success and error arguments.
                default is None
            success: if True shows successful tasks' results.
                default is False
            error: if True shows failed and retried tasks' tracebacks.
                default is True, as you're monitoring to find errors, right?

        """
        tasks_filter = ClearlyClient._parse_pattern(tasks)
        if not tasks_filter:
            raise UserWarning('Nothing would be selected.')

        request = FilterTasksRequest(
            tasks_filter=tasks_filter, limit=limit, reverse=reverse
        )

        at = about_time(self._stub.filter_tasks(request))
        for task in at:
            ClearlyClient._display_task(task, params, success, error)
        ClearlyClient._fetched_info(at)

    @set_user_friendly_errors
    def workers(self, workers: Optional[str] = None, stats: bool = True) -> None:
        """Fetch current data from known workers.
        
        Args:
            Filter args:
            ------------

            workers: a simple pattern to filter workers.
                ex.: 'email' to find values containing that word anywhere
                     'service|priority' to find values containing any of those words
                     '!service|priority' to find values not containing both those words

            Display args:
            -------------

            stats: if True shows complete workers' stats, default is False

        """
        workers_filter = ClearlyClient._parse_pattern(workers)
        if not workers_filter:
            raise UserWarning('Nothing would be selected.')

        request = FilterWorkersRequest(workers_filter=workers_filter)

        at = about_time(self._stub.filter_workers(request))
        for worker in at:
            ClearlyClient._display_worker(worker, stats)
        ClearlyClient._fetched_info(at)

    @set_user_friendly_errors
    def seen_tasks(self) -> None:
        """Fetch a list of seen task types."""
        print('\n'.join(self._stub.seen_tasks(Empty()).task_types))

    @set_user_friendly_errors
    def reset(self) -> None:
        """Reset all captured tasks."""
        self._stub.reset_tasks(Empty())

    @staticmethod
    def _fetched_info(at: HandleStats) -> None:  # pragma: no cover
        print('{} {} in {} ({})'.format(
            Colors.DIM('fetched:'), Colors.BOLD(at.count),
            Colors.GREEN(at.duration_human), Colors.GREEN(at.throughput_human)
        ))

    @staticmethod
    def _parse_pattern(pattern: str) -> PatternFilter:
        pattern = pattern or ''
        if not isinstance(pattern, str):
            raise UserWarning('Invalid pattern.')

        pattern = pattern.strip() or '.'
        if pattern in ('!', '!.'):
            return
        negate = pattern.startswith('!')
        return PatternFilter(pattern=pattern[negate:], negate=negate)

    @staticmethod
    def _display_task(task: TaskMessage, params: bool,
                      success: bool, error: bool) -> None:
        ts = datetime.fromtimestamp(task.timestamp)
        print(Colors.DIM(ts.strftime('%H:%M:%S.%f')[:-3]), end=' ')
        if not task.state:
            routing_key = task.routing_key or EMPTY
            print(Colors.BLUE(task.name),
                  Colors.MAGENTA(routing_key[len(task.name):] or '-'
                                 if routing_key.startswith(task.name)
                                 else routing_key),
                  Colors.DIM(task.uuid))
        else:
            print(ClearlyClient._task_state(task.state),
                  Colors.BLUE_DIM(task.retries),
                  end=' ')
            print(Colors.BLUE(task.name), Colors.DIM(task.uuid))

        show_result = (task.state in task_states.PROPAGATE_STATES and error) \
            or (task.state == task_states.SUCCESS and success)

        first_seen = bool(params) and not task.state
        result = params is not False and show_result
        if first_seen or result:
            print(Colors.DIM('{:>{}}'.format('args:', HEADER_SIZE)),
                  typed_code(safe_compile_text(task.args),
                             wrap=False) or EMPTY)
            print(Colors.DIM('{:>{}}'.format('kwargs:', HEADER_SIZE)),
                  typed_code(safe_compile_text(task.kwargs),
                             wrap=False) or EMPTY)

        if show_result:
            if task.result:
                output = typed_code(safe_compile_text(task.result))
            elif task.traceback:
                output = TRACEBACK_HIGHLIGHTER(task.traceback) \
                    .replace('\n', '\n' + HEADER_PADDING).strip()
            else:
                output = EMPTY
            print(Colors.DIM('{:>{}}'.format('==>', HEADER_SIZE)), output)

    @staticmethod
    def _display_worker(worker: WorkerMessage, stats: bool) -> None:
        if worker.timestamp:
            ts = datetime.fromtimestamp(worker.timestamp)
            print(Colors.DIM(ts.strftime('%H:%M:%S.%f')[:-3]), end=' ')
        print(ClearlyClient._worker_state(worker.state),
              Colors.CYAN_DIM(worker.hostname),
              Colors.YELLOW_DIM(str(worker.pid)))

        if stats:
            print(Colors.DIM('{:>{}}'.format('sw:', HEADER_SIZE)),
                  Colors.CYAN_DIM(' '.join((worker.sw_sys, worker.sw_ident))),
                  Colors.ORANGE(worker.sw_ver))
            print(Colors.DIM('{:>{}}'.format('load:', HEADER_SIZE)),
                  ClearlyClient._item_list(worker.loadavg),
                  Colors.DIM('processed:'), worker.processed or DIM_NONE)
            heartbeats = [datetime.fromtimestamp(x).strftime('%H:%M:%S.%f')[:-3]
                          for x in worker.heartbeats or []]
            print(Colors.DIM('{:>{}}'.format('heartb:', HEADER_SIZE)),
                  '{}{}'.format(Colors.ORANGE(worker.freq),
                                Colors.DIM('s')),
                  ClearlyClient._item_list(heartbeats))

    @staticmethod
    def _item_list(items: Iterable[Any], color: Callable[[str], str] = str) -> str:
        return '{}{}{}'.format(
            Colors.MAGENTA('['),
            Colors.MAGENTA(', ').join(map(color, items)),
            Colors.MAGENTA(']'),
        )

    @staticmethod
    def _task_state(state: str) -> None:
        result = '{:>{}}'.format(state, HEADER_SIZE)
        if state == task_states.SUCCESS:  # final state in BOLD
            return Colors.GREEN_BOLD(result)
        if state in (task_states.FAILURE, task_states.REVOKED, task_states.REJECTED):  # final too
            return Colors.RED_BOLD(result)
        return Colors.YELLOW(result)  # transient states

    @staticmethod
    def _worker_state(state: str) -> None:
        result = state
        if state == worker_states.HEARTBEAT:
            return Colors.GREEN(result)
        if state == worker_states.ONLINE:
            return Colors.GREEN_BOLD(result)
        return Colors.RED_BOLD(result)
