import atexit
import logging.config
import multiprocessing.synchronize
import sys
import time
from random import Random
from typing import (Any,
                    Dict,
                    Optional,
                    Sequence)

import requests
from consensual.raft import (Node,
                             Processor)
from reprit.base import generate_repr
from requests import Session
from yarl import URL

from consensual_http import communication


class RaftClusterNode:
    def __init__(self,
                 url: URL,
                 processors: Dict[str, Processor],
                 *,
                 heartbeat: float) -> None:
        self.heartbeat, self.processors, self.url = heartbeat, processors, url
        self._url_string = str(url)
        self._event = multiprocessing.Event()
        self._process = multiprocessing.Process(
                target=run_node,
                args=(self.url, self.processors, self.heartbeat, self._event)
        )
        self._session = Session()

    __repr__ = generate_repr(__init__)

    @classmethod
    def running_from_one_of_ports(cls,
                                  host: str,
                                  ports: Sequence[int],
                                  processors: Dict[str, Processor],
                                  random_seed: int,
                                  *,
                                  heartbeat: float) -> 'RaftClusterNode':
        candidates = list(ports)
        generate_index = Random(random_seed).randrange
        while candidates:
            candidate_index = generate_index(0, len(candidates))
            candidate = candidates[candidate_index]
            url = URL.build(scheme='http',
                            host=host,
                            port=candidate)
            self = cls(url, processors,
                       heartbeat=heartbeat)
            if self.start():
                break
        else:
            raise RuntimeError(f'all ports from {ports} are occupied')
        return self

    def attach(self, node: 'RaftClusterNode', *rest: 'RaftClusterNode'
               ) -> Optional[str]:
        response = requests.post(self._url_string,
                                 json=[str(node.url)
                                       for node in [node, *rest]])
        response.raise_for_status()
        return response.json()['result']['error']

    def detach(self) -> Optional[str]:
        response = requests.delete(self._url_string)
        response.raise_for_status()
        return response.json()['result']['error']

    def detach_node(self, node: 'RaftClusterNode') -> Optional[str]:
        response = requests.delete(self._url_string,
                                   json=[str(node.url)])
        response.raise_for_status()
        return response.json()['result']['error']

    def log(self, action: str, parameters: Any) -> Optional[str]:
        response = requests.post(str(self.url.with_path(action)),
                                 json=parameters)
        response.raise_for_status()
        return response.json()['result']['error']

    def solo(self) -> Optional[str]:
        response = requests.post(self._url_string)
        response.raise_for_status()
        return response.json()['result']['error']

    def restart(self) -> bool:
        assert self._process is None
        self._event = multiprocessing.Event()
        self._process = multiprocessing.Process(
                target=run_node,
                args=(self.url, self.processors, self.heartbeat, self._event)
        )
        return self.start()

    def start(self) -> bool:
        self._process.start()
        self._event.wait()
        del self._event
        time.sleep(1)
        if not self._process.is_alive():
            return False
        return True

    def stop(self) -> None:
        self._session.close()
        assert self._process is not None
        for _ in range(5):
            if not self._process.is_alive():
                break
            self._process.terminate()
            time.sleep(1)
        else:
            self._process.kill()
            time.sleep(5)
        self._process = None


class FilterRecordsWithGreaterLevel:
    def __init__(self, max_level: int) -> None:
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level


def run_node(url: URL,
             processors: Dict[str, Processor],
             heartbeat: float,
             event: multiprocessing.synchronize.Event) -> None:
    atexit.register(event.set)
    sender = communication.Sender(heartbeat=heartbeat,
                                  urls=[url])
    node = Node.from_url(url,
                         heartbeat=heartbeat,
                         logger=to_logger(url.authority),
                         processors=processors,
                         sender=sender)
    receiver = communication.Receiver(node,
                                      on_run=event.set)
    receiver.start()


def to_logger(name: str,
              *,
              version: int = 1) -> logging.Logger:
    console_formatter = {'format': '[%(levelname)-8s %(name)s] %(msg)s'}
    formatters = {'console': console_formatter}
    stderr_handler_config = {
        'class': 'logging.StreamHandler',
        'level': logging.WARNING,
        'formatter': 'console',
        'stream': sys.stderr,
    }
    stdout_handler_config = {
        'class': 'logging.StreamHandler',
        'level': logging.DEBUG,
        'formatter': 'console',
        'stream': sys.stdout,
        'filters': ['stdout']
    }
    handlers = {'stdout': stdout_handler_config,
                'stderr': stderr_handler_config}
    loggers = {name: {'level': logging.DEBUG,
                      'handlers': ('stderr', 'stdout')}}
    config = {'formatters': formatters,
              'handlers': handlers,
              'loggers': loggers,
              'version': version,
              'filters': {
                  'stdout': {
                      '()': FilterRecordsWithGreaterLevel,
                      'max_level': logging.WARNING,
                  }
              }}
    logging.config.dictConfig(config)
    return logging.getLogger(name)
