# coding=utf-8
from __future__ import absolute_import, print_function, unicode_literals

import operator
import re
# noinspection PyCompatibility
from concurrent import futures

import grpc
from celery import Celery
from celery.events.state import Task, Worker

from event_core.events import WorkerData
from .event_core.event_listener import EventListener
from .event_core.events import TaskData
from .event_core.streaming_dispatcher import StreamingDispatcher
from .protos import clearly_pb2, clearly_pb2_grpc
from .utils.data import accepts

try:
    # noinspection PyCompatibility
    from queue import Queue, Empty
except:
    # noinspection PyCompatibility
    from Queue import Queue, Empty

CAPTURE_PARAMS_OP = operator.attrgetter('pattern', 'negate')


class ClearlyServer(clearly_pb2_grpc.ClearlyServerServicer):
    """Simple and real-time monitor for celery.
    Server object, to capture events and handle tasks and workers.
    
    Attributes:
        listener (EventListener): the object that listens and keeps celery events
        dispatcher (StreamingDispatcher): the mechanism to dispatch data to clients
    """

    def __init__(self, listener, dispatcher):
        """Constructs a server instance.
        
        Args:
            listener (EventListener): the object that listens and keeps celery events
            dispatcher (StreamingDispatcher): the mechanism to dispatch data to clients
        """
        self.listener = listener
        self.dispatcher = dispatcher

    def capture_realtime(self, request, context):
        """

        Args:
            request (clearly_pb2.CaptureRequest):
            context:

        Returns:

        """
        print('request:', request)
        tasks_pattern, tasks_negate = CAPTURE_PARAMS_OP(request.tasks_capture)
        workers_pattern, workers_negate = CAPTURE_PARAMS_OP(request.workers_capture)

        with self.dispatcher.streaming_client(tasks_pattern, tasks_negate,
                                              workers_pattern, workers_negate) as q:  # type: Queue
            while True:
                try:
                    event_data = q.get(timeout=1)
                except Empty:
                    continue

                key, obj = ClearlyServer._event_to_pb(event_data)
                yield clearly_pb2.RealtimeEventMessage(**{key: obj})

    @staticmethod
    def _event_to_pb(event):
        """Supports converting internal TaskData and WorkerData, as well as
        celery Task and Worker to proto buffers messages.

        Args:
            event (Union[TaskData|Task|WorkerData|Worker]):

        Returns:
            ProtoBuf object

        """
        if isinstance(event, (TaskData, Task)):
            key, klass = 'task', clearly_pb2.TaskMessage
        elif isinstance(event, (WorkerData, Worker)):
            key, klass = 'worker', clearly_pb2.WorkerMessage
        else:
            raise ValueError('unknown event')
        keys = klass.DESCRIPTOR.fields_by_name.keys()
        data = {k: v for k, v in getattr(event, '_asdict',
                                         event.as_dict)().items() if k in keys}
        return key, klass(**data)

    def filter_tasks(self, request, context):
        """Filter task by matching a pattern and a state."""
        tasks_pattern, tasks_negate = CAPTURE_PARAMS_OP(request.tasks_filter)
        state_pattern = request.state_pattern

        pcondition = scondition = lambda task: True
        if tasks_pattern:
            regex = re.compile(tasks_pattern)
            pcondition = lambda task: accepts(regex, tasks_negate, task.name, task.routing_key)

        if state_pattern:
            regex = re.compile(state_pattern)
            scondition = lambda task: accepts(regex, tasks_negate, task.state)

        found_tasks = (task for _, task in self.listener.memory.itertasks()
                       if pcondition(task) and scondition(task))
        for task in found_tasks:
            yield ClearlyServer._event_to_pb(task)[1]

    def filter_workers(self, request, context):
        """Filter task by matching a pattern and a state."""
        workers_pattern, workers_negate = CAPTURE_PARAMS_OP(request.workers_filter)

        hcondition = lambda worker: True
        if workers_pattern:
            regex = re.compile(workers_pattern)
            hcondition = lambda worker: accepts(regex, workers_negate, worker.hostname)

        op = operator.attrgetter('hostname')
        found_workers = (worker for worker in sorted(self.listener.memory.workers, key=op)
                         if hcondition)
        for worker in found_workers:
            yield ClearlyServer._event_to_pb(worker)[1]

    def task(self, request, context):
        """Finds one specific task."""
        task = self.listener.memory.tasks.get(request.task_uuid)
        if task:
            return ClearlyServer._event_to_pb(task)[1]

    def seen_tasks(self, request, context):
        """Returns all seen task types."""
        return clearly_pb2.SeenTasksMessage().task_types \
            .extend(self.listener.memory.task_types())

    def reset_tasks(self, request, context):
        """Resets all captured tasks."""
        self.listener.memory.clear_tasks()

    def stats(self, request, context):
        """Returns the server statistics."""
        m = self.listener.memory
        return m.task_count, m.event_count, len(m.tasks), len(m.workers)


def serve(instance):  # pragma: no cover
    server = grpc.server(futures.ThreadPoolExecutor())
    clearly_pb2_grpc.add_ClearlyServerServicer_to_server(instance, server)
    server.add_insecure_port('[::]:12223')
    server.start()

    import time
    ONE_DAY_IN_SECONDS = 24 * 60 * 60
    try:
        while True:
            time.sleep(ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        server.stop(None)


if __name__ == '__main__':
    app = Celery(broker='amqp://localhost', backend='redis://localhost')
    queue_listener_dispatcher = Queue()
    listener = EventListener(app, queue_listener_dispatcher)
    dispatcher = StreamingDispatcher(queue_listener_dispatcher)
    clearlysrv = ClearlyServer(listener, dispatcher)
    serve(clearlysrv)
