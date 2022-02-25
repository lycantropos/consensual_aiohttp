from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import (Dict,
                    Iterable,
                    Iterator,
                    List,
                    Sequence,
                    Tuple)

from consensual.core.raft.role import RoleKind
from consensual.raft import Processor
from hypothesis.stateful import (Bundle,
                                 RuleBasedStateMachine,
                                 consumes,
                                 multiple,
                                 precondition,
                                 rule)
from hypothesis.strategies import DataObject

from . import strategies
from .raft_cluster_node import RaftClusterNode
from .utils import (MAX_RUNNING_NODES_COUNT,
                    implication,
                    transpose)


class RaftNetwork(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self._executor = ThreadPoolExecutor()
        self._nodes: List[RaftClusterNode] = []

    running_nodes = Bundle('running_nodes')
    shutdown_nodes = Bundle('shutdown_nodes')

    @rule(source_node=running_nodes,
          target_node=running_nodes)
    def add_nodes(self,
                  target_node: RaftClusterNode,
                  source_node: RaftClusterNode) -> None:
        error = target_node.add(source_node)
        assert implication(
                error is None,
                target_node.old_node_state.leader_node_id is not None
                and (source_node.old_node_state.id
                     not in target_node.old_cluster_state.nodes_ids)
                and implication(target_node.old_node_state.role_kind
                                is RoleKind.LEADER,
                                target_node.old_cluster_state.stable)
        )

    def is_not_full(self) -> bool:
        return len(self._nodes) < MAX_RUNNING_NODES_COUNT

    @precondition(is_not_full)
    @rule(target=running_nodes,
          heartbeat=strategies.heartbeats,
          nodes_parameters=strategies.running_nodes_parameters_lists)
    def create_nodes(self,
                     heartbeat: float,
                     nodes_parameters: List[Tuple[str, Sequence[int],
                                                  Dict[str, Processor], int]]
                     ) -> Iterable[RaftClusterNode]:
        max_new_nodes_count = MAX_RUNNING_NODES_COUNT - len(self._nodes)
        nodes_parameters = nodes_parameters[:max_new_nodes_count]
        nodes = list(self._executor.map(
                partial(RaftClusterNode.running_from_one_of_ports,
                        heartbeat=heartbeat),
                *transpose(nodes_parameters)))
        self._nodes.extend(nodes)
        return multiple(*nodes)

    @rule(node=running_nodes)
    def delete_nodes(self, node: RaftClusterNode) -> None:
        error = node.delete()
        assert (
                implication(
                        error is None,
                        len(node.old_cluster_state.nodes_ids) == 1
                        or (node.old_node_state.leader_node_id is not None
                            and implication(node.old_node_state.role_kind
                                            is RoleKind.LEADER,
                                            node.old_cluster_state.stable))
                )
                and implication((node.old_cluster_state.nodes_ids
                                 == [node.old_node_state.id])
                                or ((node.old_node_state.role_kind
                                     is RoleKind.LEADER)
                                    and node.old_cluster_state.stable),
                                error is None)
        )

    @rule(source_node=running_nodes,
          target_node=running_nodes)
    def delete_many_nodes(self,
                          source_node: RaftClusterNode,
                          target_node: RaftClusterNode) -> None:
        error = target_node.delete(source_node)
        assert (implication(
                error is None,
                (source_node.old_node_state.id
                 == target_node.old_node_state.id)
                if len(target_node.old_cluster_state.nodes_ids) == 1
                else
                (target_node.old_node_state.leader_node_id is not None
                 and implication(target_node.old_node_state.role_kind
                                 is RoleKind.LEADER,
                                 target_node.old_cluster_state.stable)
                 and (source_node.new_node_state.id
                      in target_node.old_cluster_state.nodes_ids)))
                and implication(
                        (source_node.old_node_state.id
                         == target_node.old_node_state.id)
                        if (target_node.old_cluster_state.nodes_ids
                            == [target_node.old_node_state.id])
                        else
                        ((target_node.old_node_state.role_kind
                          is RoleKind.LEADER)
                         and target_node.old_cluster_state.stable
                         and (source_node.new_node_state.id
                              in target_node.old_cluster_state.nodes_ids)),
                        error is None
                )
                )

    @rule(data=strategies.data_objects,
          node=running_nodes)
    def log(self, data: DataObject, node: RaftClusterNode) -> None:
        arguments = data.draw(strategies.to_log_arguments_lists(node))
        if not arguments:
            return
        errors = list(self._executor.map(node.log, arguments))
        assert all(implication(error is None,
                               node.old_node_state.leader_node_id is not None
                               and (node.old_node_state.id
                                    in node.old_cluster_state.nodes_ids))
                   and implication(node.old_node_state.role_kind
                                   is RoleKind.LEADER,
                                   error is None)
                   for error in errors)

    @rule(target=running_nodes,
          node=consumes(shutdown_nodes))
    def restart_node(self, node: RaftClusterNode) -> RaftClusterNode:
        if node.restart():
            self._nodes += [node]
            return node
        return multiple()

    @rule(target=shutdown_nodes,
          node=consumes(running_nodes))
    def shutdown_node(self, node: RaftClusterNode) -> RaftClusterNode:
        node.stop()
        self._nodes = [candidate
                       for candidate in self._nodes
                       if candidate is not node]
        return node

    @rule(node=running_nodes)
    def solo_node(self, node: RaftClusterNode) -> None:
        error = node.solo()
        assert error is None
        assert (
                node.new_cluster_state.id
                and node.new_node_state.id in node.new_cluster_state.nodes_ids
                and len(node.new_cluster_state.nodes_ids) == 1
                and node.new_node_state.role_kind is RoleKind.LEADER
        )

    def is_not_empty(self) -> bool:
        return bool(self._nodes)

    def teardown(self) -> None:
        _exhaust(self._executor.map(RaftClusterNode.stop, self._nodes))
        self._executor.shutdown()


def _exhaust(iterator: Iterator) -> None:
    deque(iterator,
          maxlen=0)


TestCluster = RaftNetwork.TestCase
