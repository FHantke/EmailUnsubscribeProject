"""
Code from https://stackoverflow.com/a/41408510/4822911
"""
from __future__ import annotations

from typing import Any

from timeit import default_timer as timer

class benchmark(object):

    def __init__(self, msg: str, fmt: str = "%0.3g") -> None:
        self.msg = msg
        self.fmt = fmt

    def __enter__(self) -> benchmark:
        self.start = timer()
        return self

    def __exit__(self, *args: Any) -> None:
        t = timer() - self.start
        print(("%s : " + self.fmt + " seconds") % (self.msg, t))
        self.time = t
