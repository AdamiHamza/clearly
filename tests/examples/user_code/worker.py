from celery import Celery

app = Celery('tasks', broker='amqp://localhost', backend='redis://localhost')
app.conf.task_send_sent_event = True


@app.task(bind=True)
def function_test(self, retries, **kwargs):
    if retries > self.request.retries:
        raise self.retry(countdown=1)
    return kwargs.get('value', -1)


@app.task
def function_aggregate(*args, **kwargs):
    return dict(input=args, extra=kwargs)
