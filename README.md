consensual_http
===============

[![](https://dev.azure.com/lycantropos/consensual_http/_apis/build/status/lycantropos.consensual_http?branchName=master)](https://dev.azure.com/lycantropos/consensual_http/_build/latest?definitionId=41&branchName=master "Azure Pipelines")
[![](https://codecov.io/gh/lycantropos/consensual_http/branch/master/graph/badge.svg)](https://codecov.io/gh/lycantropos/consensual_http "Codecov")
[![](https://img.shields.io/github/license/lycantropos/consensual_http.svg)](https://github.com/lycantropos/consensual_http/blob/master/LICENSE "License")
[![](https://badge.fury.io/py/consensual-http.svg)](https://badge.fury.io/py/consensual-http "PyPI")

In what follows `python` is an alias for `python3.7`
or any later version (`python3.8` and so on).

Installation
------------

Install the latest `pip` & `setuptools` packages versions
```bash
python -m pip install --upgrade pip setuptools
```

### User

Download and install the latest stable version from `PyPI` repository
```bash
python -m pip install --upgrade consensual_http
```

### Developer

Download the latest version from `GitHub` repository
```bash
git clone https://github.com/lycantropos/consensual_http.git
cd consensual_http
```

Install dependencies
```bash
python -m pip install -r requirements.txt
```

Install
```bash
python setup.py install
```

Usage
-----

```python
>>> from consensual.raft import Node
>>> from consensual_http import communication
>>> from yarl import URL
>>> node_url = URL.build(scheme='http',
...                      host='localhost',
...                      port=6000)
>>> heartbeat = 0.1
>>> from typing import Any
>>> processed_parameters = []
>>> def dummy_processor(parameters: Any) -> None:
...     processed_parameters.append(parameters)
>>> def stop(parameters: Any = None) -> None:
...     receiver.stop()
>>> processors = {'dummy': dummy_processor, 'stop': stop}
>>> sender = communication.Sender(heartbeat=heartbeat,
...                               urls=[node_url])
>>> from asyncio import Event, get_event_loop
>>> loop = get_event_loop()
>>> node = Node.from_url(node_url,
...                      heartbeat=heartbeat,
...                      loop=loop,
...                      processors=processors,
...                      sender=sender)
>>> node_is_running = Event()
>>> receiver = communication.Receiver(node,
...                                   on_run=node_is_running.set)
>>> from aiohttp.client import ClientSession
>>> def validate_response(response: Any) -> None:
...     assert isinstance(response, dict)
...     assert response.keys() == {'error'}
...     assert response['error'] is None
>>> async def run() -> None:
...     await node_is_running.wait()
...     async with ClientSession(node.url) as session:
...         validate_response(await (await session.post('/')).json())
...         validate_response(await (await session.post('/dummy',
...                                                     json=42)).json())
...         validate_response(await (await session.delete('/',
...                                                       json=[str(node.url)])).json())
...         validate_response(await (await session.delete('/')).json())
>>> _ = loop.create_task(run())
>>> _ = loop.call_later(2, stop, None)
>>> receiver.start()
>>> all(parameters == 42 for parameters in processed_parameters)
True

```

Development
-----------

### Bumping version

#### Preparation

Install
[bump2version](https://github.com/c4urself/bump2version#installation).

#### Pre-release

Choose which version number category to bump following [semver
specification](http://semver.org/).

Test bumping version
```bash
bump2version --dry-run --verbose $CATEGORY
```

where `$CATEGORY` is the target version number category name, possible
values are `patch`/`minor`/`major`.

Bump version
```bash
bump2version --verbose $CATEGORY
```

This will set version to `major.minor.patch-alpha`. 

#### Release

Test bumping version
```bash
bump2version --dry-run --verbose release
```

Bump version
```bash
bump2version --verbose release
```

This will set version to `major.minor.patch`.

### Running tests

Install dependencies
```bash
python -m pip install -r requirements-tests.txt
```

Plain
```bash
pytest
```

Inside `Docker` container:
```bash
docker-compose up
```

`Bash` script:
```bash
./run-tests.sh
```

`PowerShell` script:
```powershell
.\run-tests.ps1
```
