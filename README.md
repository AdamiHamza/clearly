# clearly
## Simple and accurate real-time monitor for celery

I like [flower](https://github.com/mher/flower).
But in the last couple of weeks, it's not been _that_ useful to me.
What do I need? _Actual_ real-time monitoring, filter multiple tasks simultaneously and whole thorough full utter complete results.
And _that_ other project needs page refreshes, filter only one task at a time and truncates results.

But wait, `clearly` does not have a server nor persists any data nor listens for celery events, so it does not aim to substitute flower whatsoever. I think `clearly` complements it nicely.
It's great to actually _see_ what's going on in your celery tasks, and in real-time, so it's great for debugging.
See what `clearly` can do:
<fig>


## Requirements

You can use this framework if your asynchronous system with celery:
- uses a RabbitMQ broker to decouple and persist messages;
- publishes the messages to one unique exchange of type "topic";
- and has a Redis result backend configured.


## How `clearly` works

This tool creates a non durable exclusive queue in the broker, and connects itself to it, dynamically binding any routing keys you wish.
Now it begins collecting all async tasks being triggered with matching criteria, and starts fetching the outcome and result of those tasks as soon as they finish. It's like flower on the shell!


## Features

`clearly` enables you to:
- Be notified of any and all tasks being run now, in real-time;
- Filter the async calls any way you'd like;
- Discover the actual parameters the tasks were called with;
- See and analyse the outcome of said tasks, such as success results or fail exceptions;
- _Clearly_ see types and representations of the parameters and results of the tasks with an advanced print system, similar to what REPL tools do.


## Get `clearly`

1. `pip install -U clearly`
2. there's no step 2.


## How to use

### initialize it

```python
BROKER_URL = 'amqp://guest:guest@localhost:5672//'
EXCHANGE_NAME = 'mysystem'

from clearly import Clearly
monitor = Clearly(BROKER_URL, EXCHANGE_NAME)
```

### grab them

```python
In [1]: monitor.capture('#')
```

### be enlightened
```html

```


## Documentation

```python
def capture(self, routing_keys,
            show_params=False, show_success=False, show_error=True):
    """Captures all tasks being sent to celery which matches routing keys.
    
    Args:
        routing_keys (str): a string to be split into routing keys.
           use * as exactly one part or # as zero or more parts.
           e.g., 'dispatch.# email.#' to filter messages with those prefixes;
             or 'dispatch.#.123456.#' to filter that exact id in dispatch
             or even '#.123456.#' to filter that exact id anywhere.
    """

def fetch(self, show_success=False, show_error=True):
    """Fetches results of captured tasks, blocking if necessary.
    """

def pending(self, show_params=False):
    """Prints all captured tasks which are not completed yet.
    """

def results(self, show_success=False, show_error=True):
    """Prints all captured tasks which have a success, failure or revoked status.
    """

def reset(self):
    """Resets data.
    """
```


## Hints

- write a small [celery router](http://docs.celeryproject.org/en/latest/userguide/routing.html#routers) and in there generate dynamic routing keys, based on the actual arguments of the async call in place.
That way, you'll be able to filter tasks based on any of those constraints.
- if you're using [django](https://www.djangoproject.com/) and [django-extensions](https://github.com/django-extensions/django-extensions), put in your settings a `SHELL_PLUS_POST_IMPORT` with this!
Now you just have to create an instance of it and you're good to go.
- put together a python module in your project to already initialize an instance of `clearly` and configure it.
Now you have a tool always ready to be used, pluggable even in production, to actually see what's going on in your tasks, and figure out that pesky bug.


## To do

- support python 3;
- implement a weak reference in tasks data, to be able to keep it running live 24/7, without jeopardizing the host;
- include a plugin system, to be able to print representations of custom objects;
- any other ideas welcome!
