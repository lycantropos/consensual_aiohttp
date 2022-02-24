from asyncio import (Queue,
                     get_event_loop)
from typing import (Any,
                    Collection,
                    Dict,
                    Union)

from aiohttp import (ClientError,
                     ClientSession,
                     hdrs,
                     web_ws)
from consensual.raft import (MessageKind,
                             ReceiverUnavailable,
                             Sender as BaseSender)
from reprit.base import generate_repr
from yarl import URL

from .result import (Error,
                     Ok,
                     Result)


class Sender(BaseSender):
    HTTP_METHOD = hdrs.METH_PATCH
    assert (HTTP_METHOD is not hdrs.METH_POST
            and HTTP_METHOD is not hdrs.METH_DELETE)

    def __init__(self,
                 *,
                 heartbeat: Union[int, float],
                 urls: Collection[URL]) -> None:
        self._heartbeat, self._urls = heartbeat, urls
        self._loop = get_event_loop()
        self._messages: Dict[URL, Queue] = {url: Queue() for url in self._urls}
        self._results = {url: {kind: Queue() for kind in MessageKind}
                         for url in self._urls}
        self._session = ClientSession(loop=self._loop)
        self._channels = {url: self._loop.create_task(self._channel(url))
                          for url in self._urls}

    __repr__ = generate_repr(__init__)

    @property
    def heartbeat(self) -> Union[int, float]:
        return self._heartbeat

    @property
    def urls(self) -> Collection[URL]:
        return self._urls

    @urls.setter
    def urls(self, value: Collection[URL]) -> None:
        new_urls, old_urls = set(value), set(self._urls)
        for removed_url in old_urls - new_urls:
            self._disconnect(removed_url)
        self._urls = value
        for added_url in new_urls - old_urls:
            self._connect(added_url)

    async def send(self, *, kind: MessageKind, message: Any, url: URL) -> Any:
        assert kind in MessageKind, kind
        try:
            messages = self._messages[url]
        except KeyError:
            raise ReceiverUnavailable(url)
        messages.put_nowait((kind, message))
        result: Result = await self._results[url][kind].get()
        try:
            return result.value
        except (ClientError, OSError):
            raise ReceiverUnavailable(url)

    async def _channel(self, url: URL) -> None:
        messages, results = self._messages[url], self._results[url]
        kind, message = await messages.get()
        while True:
            try:
                async with self._session.ws_connect(
                        url,
                        heartbeat=self.heartbeat,
                        method=self.HTTP_METHOD,
                        timeout=self.heartbeat
                ) as connection:
                    try:
                        await connection.send_json({'kind': kind,
                                                    'message': message})
                    except (ClientError, OSError):
                        continue
                    async for reply in connection:
                        reply: web_ws.WSMessage
                        results[kind].put_nowait(Ok(reply.json()))
                        kind, message = await messages.get()
                        try:
                            await connection.send_json({'kind': kind,
                                                        'message': message})
                        except (ClientError, OSError):
                            continue
            except (ClientError, OSError) as exception:
                results[kind].put_nowait(Error(exception))
                kind, message = await messages.get()

    def _connect(self, url: URL) -> None:
        self._messages[url] = Queue()
        self._results[url] = {kind: Queue() for kind in MessageKind}
        self._channels[url] = self._loop.create_task(self._channel(url))

    def _disconnect(self, url: URL) -> None:
        self._channels.pop(url).cancel()
        del self._messages[url], self._results[url]
