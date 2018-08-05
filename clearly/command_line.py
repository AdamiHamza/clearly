# noinspection PyCompatibility
from concurrent import futures

import click
import grpc
from celery import Celery

from clearly.event_core.event_listener import EventListener
from clearly.event_core.streaming_dispatcher import StreamingDispatcher
from clearly.protos import clearly_pb2_grpc
from clearly.server import ClearlyServer

try:
    # noinspection PyCompatibility
    from queue import Queue, Empty
except ImportError:  # pragma: no cover
    # noinspection PyCompatibility,PyUnresolvedReferences
    from Queue import Queue, Empty


@click.group()
@click.version_option()
@click.option('--debug/--no-debug', help='Enables debug logging', default=False)
def clearly(debug):
    pass


@clearly.command()
@click.argument('broker')
@click.argument('backend', required=False)
def server(broker, backend):
    app = Celery(broker=broker, backend=backend)
    queue_listener_dispatcher = Queue()
    listener = EventListener(app, queue_listener_dispatcher)
    dispatcher = StreamingDispatcher(queue_listener_dispatcher)
    clearlysrv = ClearlyServer(listener, dispatcher)
    _serve(clearlysrv)


def _serve(instance):
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
