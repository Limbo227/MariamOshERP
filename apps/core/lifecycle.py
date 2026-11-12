import contextvars
from contextlib import contextmanager

_lifecycle = contextvars.ContextVar("erp_document_lifecycle", default=False)


def lifecycle_open():
    return _lifecycle.get()


@contextmanager
def lifecycle():
    token = _lifecycle.set(True)
    try:
        yield
    finally:
        _lifecycle.reset(token)
