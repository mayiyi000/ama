#!/usr/bin/env python
import unittest
import networkx as nx  # type: ignore
from tinygrad.tensor import Tensor
from tinygrad.graph import G, log_op, prune_graph
from tinygrad.ops import BinaryOps, LazyOp, MovementOps, ReduceOps

def buf(*shp): return Tensor.ones(*shp, device="CPU").lazydata

class TestGraph(unittest.TestCase):
  def setUp(self):
    G.clear()

  def helper_compare_graph(self, RG: nx.DiGraph):
    assert nx.is_isomorphic(G, RG, node_match=lambda x,y: x["label"] == y["label"], edge_match=lambda x,y: x["label"] == y["label"] if "label" in y else True)

  def test_add_graph(self):
    a = buf(4,4)
    b = buf(4,4)
    ast = LazyOp(BinaryOps.ADD, (a,b))
    ret = buf(4,4)

    RG = nx.DiGraph()
    RG.add_node(0, label="(4, 4)")
    RG.add_node(1, label="(4, 4)")
    RG.add_node(2, label="(4, 4)")
    RG.add_edge(0, 2, label="ADD")
    RG.add_edge(1, 2, label="ADD")

    log_op(ret, ast, show_graph=True)
    self.helper_compare_graph(RG)

  def test_add_sum_graph(self):
    a = buf(4,4)
    b = buf(1,1)
    op0 = LazyOp(MovementOps.RESHAPE, (b,), (4, 4))
    op1 = LazyOp(BinaryOps.ADD, (a,op0))
    ast = LazyOp(ReduceOps.SUM, (op1,), (1,1))
    ret = buf(1,1)

    RG = nx.DiGraph()
    RG.add_node(0, label="(4, 4)")
    RG.add_node(1, label="(1, 1)")
    RG.add_node(2, label="{(4, 4), (1, 1)}\n(1, 1)")
    RG.add_edge(0, 2, label="RES.ADD.SUM")
    RG.add_edge(1, 2, label="RES.ADD.SUM")

    log_op(ret, ast, show_graph=True)
    self.helper_compare_graph(RG)

  def test_add_graph_prune(self):
    a = buf(1,1)
    ast = LazyOp(MovementOps.RESHAPE, (a,), (4, 4))
    ret = buf(4,4)
    log_op(ret, ast, show_graph=True)

    b = buf(4,4)
    ast = LazyOp(BinaryOps.ADD, (ret,b))
    ret = buf(4,4)
    log_op(ret, ast, show_graph=True)
    prune_graph()

    RG = nx.DiGraph()
    RG.add_node(0, label="(1, 1)")
    RG.add_node(1, label="(4, 4)")
    RG.add_node(2, label="(4, 4)")
    RG.add_edge(0, 2) # edge connecting pruned nodes
    RG.add_edge(1, 2, label="ADD")

    self.helper_compare_graph(RG)

if __name__ == "__main__":
  unittest.main()
