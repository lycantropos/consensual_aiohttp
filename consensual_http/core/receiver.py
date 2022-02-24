import json as _json
import signal
from typing import (Awaitable as _Awaitable,
                    Callable as _Callable)

from aiohttp import (web as _web,
                     web_ws as _web_ws)
from consensual.raft import (MessageKind as _MessageKind,
                             Node as _Node,
                             Receiver as _Receiver)
from reprit.base import generate_repr as _generate_repr
from yarl import URL as _URL

from .sender import Sender
from .consts import HTTP_METHOD


class Receiver(_Receiver):
    __slots__ = '_app', '_is_running', '_node'

    def __new__(cls, _node: _Node) -> 'Receiver':
        if not isinstance(_node.sender, Sender):
            raise TypeError('node supposed to have compatible sender type, '
                            f'but found {type(_node.sender)}')
        self = super().__new__(cls)
        self._node = _node
        self._is_running = False
        app = self._app = _web.Application()

        @_web.middleware
        async def error_middleware(
                request: _web.Request,
                handler: _Callable[[_web.Request],
                                   _Awaitable[_web.StreamResponse]],
                log: _Callable[[str], None] = _node.logger.exception
        ) -> _web.StreamResponse:
            try:
                result = await handler(request)
            except _web.HTTPException:
                raise
            except Exception:
                log('Something unexpected happened:')
                raise
            else:
                return result

        app.middlewares.append(error_middleware)
        app.router.add_delete('/', self._handle_delete)
        app.router.add_post('/', self._handle_post)
        app.router.add_route(HTTP_METHOD, '/', self._handle_communication)
        for action in _node.processors.keys():
            route = app.router.add_post(f'/{action}', self._handle_record)
            resource = route.resource
            _node.logger.debug(f'registered resource {resource.canonical}')
        return self

    __repr__ = _generate_repr(__new__)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError('Already running')
        url = self._node.url
        _web.run_app(self._app,
                     host=url.host,
                     port=url.port,
                     loop=self._node.loop,
                     print=lambda message: (self._set_running(True)
                                            or print(message)))

    def stop(self) -> None:
        if self._is_running:
            try:
                signal.raise_signal(signal.SIGINT)
            finally:
                self._set_running(False)

    async def _handle_communication(self, request: _web.Request
                                    ) -> _web_ws.WebSocketResponse:
        websocket = _web_ws.WebSocketResponse()
        await websocket.prepare(request)
        async for message in websocket:
            message: _web_ws.WSMessage
            contents = message.json()
            reply = await self._node.receive(
                    kind=_MessageKind(contents['kind']),
                    message=contents['message']
            )
            await websocket.send_json(reply)
        return websocket

    async def _handle_delete(self, request: _web.Request) -> _web.Response:
        text = await request.text()
        if text:
            raw_nodes_urls = _json.loads(text)
            assert isinstance(raw_nodes_urls, list)
            nodes_urls = [_URL(raw_url) for raw_url in raw_nodes_urls]
            error_message = await self._node.detach_nodes(nodes_urls)
        else:
            error_message = await self._node.detach()
        result = {'error': error_message}
        return _web.json_response(result)

    async def _handle_post(self, request: _web.Request) -> _web.Response:
        text = await request.text()
        if text:
            raw_urls = _json.loads(text)
            assert isinstance(raw_urls, list)
            nodes_urls = [_URL(raw_url) for raw_url in raw_urls]
            error_message = await self._node.attach_nodes(nodes_urls)
        else:
            error_message = await self._node.solo()
        return _web.json_response({'error': error_message})

    async def _handle_record(self, request: _web.Request) -> _web.Response:
        parameters = await request.json()
        error_message = await self._node.enqueue(request.path[1:], parameters)
        return _web.json_response({'error': error_message})

    def _set_running(self, value: bool) -> None:
        self._is_running = value
