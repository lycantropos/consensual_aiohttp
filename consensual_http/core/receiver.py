import json
import signal
from typing import (Awaitable,
                    Callable)

from aiohttp import (web,
                     web_ws)
from consensual.raft import (MessageKind,
                             Node,
                             Receiver as BaseReceiver)
from reprit.base import generate_repr
from yarl import URL

from .consts import HTTP_METHOD
from .sender import Sender


class Receiver(BaseReceiver):
    __slots__ = '_app', '_is_running', '_node', '_on_run'

    def __new__(cls, _node: Node) -> 'Receiver':
        if not isinstance(_node.sender, Sender):
            raise TypeError(f'node supposed to have sender of type {Sender}, '
                            f'but found {type(_node.sender)}')
        self = super().__new__(cls)
        self._node = _node
        self._is_running = False
        app = self._app = web.Application()

        async def close_sender_session(_: web.Application) -> None:
            await _node.sender._session.close()

        app.on_shutdown.append(close_sender_session)

        @web.middleware
        async def error_middleware(
                request: web.Request,
                handler: Callable[[web.Request],
                                  Awaitable[web.StreamResponse]],
                log: Callable[[str], None] = _node.logger.exception
        ) -> web.StreamResponse:
            try:
                result = await handler(request)
            except web.HTTPException:
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

    __repr__ = generate_repr(__new__)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError('Already running')
        url = self._node.url
        web.run_app(self._app,
                    host=url.host,
                    port=url.port,
                    loop=self._node.loop,
                    print=lambda message: self._set_running(True))

    def stop(self) -> None:
        if self._is_running:
            try:
                signal.raise_signal(signal.SIGINT)
            finally:
                self._set_running(False)

    async def _handle_communication(self, request: web.Request
                                    ) -> web_ws.WebSocketResponse:
        websocket = web_ws.WebSocketResponse()
        await websocket.prepare(request)
        async for message in websocket:
            message: web_ws.WSMessage
            contents = message.json()
            reply = await self._node.receive(
                    kind=MessageKind(contents['kind']),
                    message=contents['message']
            )
            await websocket.send_json(reply)
        return websocket

    async def _handle_delete(self, request: web.Request) -> web.Response:
        text = await request.text()
        if text:
            raw_nodes_urls = json.loads(text)
            assert isinstance(raw_nodes_urls, list)
            nodes_urls = [URL(raw_url) for raw_url in raw_nodes_urls]
            error_message = await self._node.detach_nodes(nodes_urls)
        else:
            error_message = await self._node.detach()
        result = {'error': error_message}
        return web.json_response(result)

    async def _handle_post(self, request: web.Request) -> web.Response:
        text = await request.text()
        if text:
            raw_urls = json.loads(text)
            assert isinstance(raw_urls, list)
            nodes_urls = [URL(raw_url) for raw_url in raw_urls]
            error_message = await self._node.attach_nodes(nodes_urls)
        else:
            error_message = await self._node.solo()
        return web.json_response({'error': error_message})

    async def _handle_record(self, request: web.Request) -> web.Response:
        parameters = await request.json()
        error_message = await self._node.enqueue(request.path[1:], parameters)
        return web.json_response({'error': error_message})

    def _set_running(self, value: bool) -> None:
        self._is_running = value
