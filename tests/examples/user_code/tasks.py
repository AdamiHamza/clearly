from celery import Celery

app = Celery('tasks', broker='amqp://localhost', backend='redis://localhost')
app.conf.task_send_sent_event = True


@app.task(bind=True, max_retries=20)
def function_value(self, retries, **kwargs):
    if retries > self.request.retries:
        raise self.retry(countdown=1)
    return kwargs.get('value', -1)


@app.task(bind=True)
def function_kwargs(self, retries, **kwargs):
    if retries > self.request.retries:
        raise self.retry(countdown=1)
    return kwargs


@app.task(bind=True)
def function_none(self, retries, **kwargs):
    if retries > self.request.retries:
        raise self.retry(countdown=1)


@app.task(bind=True, ignore_result=True)
def function_ignore(self, retries, **kwargs):
    if retries > self.request.retries:
        raise self.retry(countdown=1)
    return kwargs


@app.task
def function_any(*args, **kwargs):
    return dict(result=args, extra=kwargs)
