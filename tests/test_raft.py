from typing import (Any,
                    Dict,
                    Iterable,
                    List,
                    Sequence,
                    Tuple)

from consensual.raft import Processor
from hypothesis.stateful import (Bundle,
                                 RuleBasedStateMachine,
                                 consumes,
                                 multiple,
                                 precondition,
                                 rule)
from hypothesis.strategies import DataObject

from . import strategies
from .raft_node import RaftNode
from .utils import MAX_RUNNING_NODES_COUNT


class RaftNetwork(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.active_nodes: List[RaftNode] = []
        self.deactivated_nodes: List[RaftNode] = []

    running_nodes = Bundle('running_nodes')
    shutdown_nodes = Bundle('shutdown_nodes')

    @rule(source_node=running_nodes,
          target_node=running_nodes)
    def add_nodes(self,
                  target_node: RaftNode,
                  source_node: RaftNode) -> None:
        error = target_node.attach(source_node)
        assert is_valid_error_message(error)

    def is_not_full(self) -> bool:
        return (len(self.active_nodes) + len(self.deactivated_nodes)
                < MAX_RUNNING_NODES_COUNT)

    @precondition(is_not_full)
    @rule(target=running_nodes,
          heartbeat=strategies.heartbeats,
          nodes_parameters=strategies.running_nodes_parameters_lists)
    def create_nodes(self,
                     heartbeat: float,
                     nodes_parameters: List[Tuple[str, Sequence[int],
                                                  Dict[str, Processor], int]]
                     ) -> Iterable[RaftNode]:
        max_new_nodes_count = (MAX_RUNNING_NODES_COUNT
                               - (len(self.active_nodes)
                                  + len(self.deactivated_nodes)))
        nodes_parameters = nodes_parameters[:max_new_nodes_count]
        nodes = [RaftNode.running_from_one_of_ports(*node_parameters,
                                                    heartbeat=heartbeat)
                 for node_parameters in nodes_parameters]
        self.active_nodes.extend(nodes)
        return multiple(*nodes)

    @rule(node=running_nodes)
    def detach_node(self, node: RaftNode) -> None:
        error = node.detach()
        assert is_valid_error_message(error)

    @rule(source_node=running_nodes,
          target_node=running_nodes)
    def detach_nodes(self,
                     source_node: RaftNode,
                     target_node: RaftNode) -> None:
        error_message = target_node.detach_node(source_node)
        assert is_valid_error_message(error_message)

    @rule(data=strategies.data_objects,
          node=running_nodes)
    def log(self, data: DataObject, node: RaftNode) -> None:
        arguments = data.draw(strategies.to_log_arguments_lists(node))
        assert all(is_valid_error_message(node.log(action, parameters))
                   for action, parameters in arguments)

    @rule(target=running_nodes,
          node=consumes(shutdown_nodes))
    def restart_node(self, node: RaftNode) -> RaftNode:
        if node.restart():
            self.active_nodes.append(node)
            self.deactivated_nodes = [candidate
                                      for candidate in self.deactivated_nodes
                                      if candidate is not node]
            return node
        return multiple()

    @rule(target=shutdown_nodes,
          node=consumes(running_nodes))
    def shutdown_node(self, node: RaftNode) -> RaftNode:
        node.stop()
        self.active_nodes = [candidate
                             for candidate in self.active_nodes
                             if candidate is not node]
        self.deactivated_nodes.append(node)
        return node

    @rule(node=running_nodes)
    def solo_node(self, node: RaftNode) -> None:
        error_message = node.solo()
        assert error_message is None

    def is_not_empty(self) -> bool:
        return bool(self.active_nodes)

    def teardown(self) -> None:
        for node in self.active_nodes:
            node.stop()


def is_valid_error_message(error_message: Any) -> bool:
    return error_message is None or isinstance(error_message, str)


TestCluster = RaftNetwork.TestCase
