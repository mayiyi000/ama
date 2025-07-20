#!/usr/bin/env python
import unittest
import numpy as np
from tinygrad.helpers import prod, all_same
from tinygrad.shape.shapetracker import ShapeTracker, View, merge_views, get_contraction
from tinygrad.codegen.cstyle import to_image_idx

def shapetracker_getitem(st, val):
  locals = {"idx": val, "valid": 1}
  idx, valid = st.expr_node()
  exec(f"valid={valid.render()};idx={idx.render()}", None, locals)
  return locals["idx"] if locals["valid"] else -1

class CheckingShapeTracker:
  def __init__(self, shape):
    self.st = ShapeTracker(shape)
    self.t = np.arange(prod(shape), dtype=np.int32).reshape(shape)

  @property
  def shape(self):
    return self.t.shape

  def simplify(self): self.st.simplify()

  def reshape(self, new_shape):
    self.st.reshape(new_shape)
    self.t = self.t.reshape(new_shape)

  def permute(self, axis):
    self.st.permute(axis)
    self.t = np.transpose(self.t, axis)

  def expand(self, new_shape):
    self.st.expand(new_shape)
    self.t = np.broadcast_to(self.t, new_shape)

  def flip(self, axis):
    self.st.stride(tuple(-1 if i in axis else 1 for i in range(len(self.shape))))
    self.t = np.flip(self.t, axis)

  def shrink(self, arg):
    self.st.shrink(arg)
    self.t = self.t[tuple([slice(x[0], x[1]) for x in arg])]

  def pad(self, arg):
    self.st.pad(arg)
    self.t = np.pad(self.t, arg, constant_values=-1)

  def stride(self, arg):
    self.st.stride(arg)
    self.t = self.t[tuple([slice(None, None, x) for x in arg])]

  def __getitem__(self, val):
    return self.t.flatten()[val]

  @property
  def views(self): return self.st.views

  @property
  def contiguous(self): return self.st.contiguous

  def assert_same(self):
    x = [shapetracker_getitem(self.st, i) for i in range(prod(self.st.shape))]
    y = [self[i] for i in range(prod(self.shape))]
    idx, valid = self.st.expr_node()
    print(x, y, self.st.shape, self.shape, idx.render(), valid.render(), self.st)
    assert self.st.shape == self.shape
    assert x == y, f"mismatch shapetracker:{x} real:{y}"

class TestSimplifyingShapeTracker(unittest.TestCase):
  def setUp(self):
    self.st = CheckingShapeTracker((1, 10))

  def tearDown(self):
    self.st.assert_same()

  # multiview simplify
  def test_expand_contract_simple(self):
    self.st.expand((10, 10))
    self.st.reshape((100,))
    print(self.st.views)
    assert(len(self.st.views) == 2)
    self.st.reshape((10, 10))
    print(self.st.views)

    self.st.simplify()
    print(self.st.views)
    assert(len(self.st.views) == 1)

  # multiview simplify
  def test_expand_contract_different_shape(self):
    self.st.expand((10, 10))
    self.st.reshape((100,))
    print(self.st.views)
    assert(len(self.st.views) == 2)
    self.st.reshape((2, 5, 2, 5))
    print(self.st.views)

    self.st.simplify()
    print(self.st.views)
    assert(len(self.st.views) == 1)

  # multiview simplify
  def test_expand_contract_still_complex(self):
    self.st.expand((10, 10))
    self.st.reshape((100,))
    print(self.st.views)
    assert(len(self.st.views) == 2)
    self.st.reshape((5, 20))

    self.st.simplify()
    print(self.st.views)
    assert(len(self.st.views) == 2)

# Tensor.zeros(2, 4).permute(1,0).reshape(2, 4)
# (d1*4 + d0%4), d1=x//4, d0=x%4 = ((x//4)*4) + (x%4)%4

class TestComplexShapeTracker(unittest.TestCase):
  def test_add_1s(self):
    self.st = CheckingShapeTracker((4, 4))
    self.st.permute((1,0))
    self.st.reshape((1,4,1,4,1))
    assert not self.st.contiguous
    self.st.permute((0,3,2,1,4))
    assert self.st.contiguous

  def test_permute_1s_simple(self):
    self.st = CheckingShapeTracker((1, 16, 9,9))
    self.st.permute((1,0,2,3))
    assert self.st.contiguous
    self.st = CheckingShapeTracker((2, 16, 9,9))
    self.st.permute((1,0,2,3))
    assert not self.st.contiguous

  def test_remove_1s_simple(self):
    self.st = CheckingShapeTracker((1, 16, 1, 1))
    self.st.reshape((16,))
    assert self.st.contiguous

  def test_remove_1s(self):
    self.st = CheckingShapeTracker((1, 4, 1, 4, 1))
    self.st.permute((0,3,2,1,4))
    self.st.reshape((4,4))
    assert not self.st.contiguous
    self.st.permute((1,0))
    assert self.st.contiguous

  def test_permute_reshape(self):
    self.st = CheckingShapeTracker((4, 4))
    self.st.permute((1,0))
    self.st.reshape((2, 2, 2, 2))
    # TODO: should also be tested by test_super_complex
    assert len(self.st.views) == 1

  def test_factorize_split(self):
    self.st = CheckingShapeTracker((4, 4))
    self.st.permute((1,0))
    self.st.reshape((2, 2, 2, 2))
    self.st.permute((2,3,0,1))
    assert self.st.contiguous

  def test_factorize_combine(self):
    self.st = CheckingShapeTracker((4, 4, 4))
    self.st.permute((2, 0, 1))
    self.st.reshape((4, 16))
    self.st.permute((1, 0))
    assert self.st.contiguous

  def test_factorize_combine_add_ones(self):
    self.st = CheckingShapeTracker((4, 4, 4))
    self.st.permute((2, 0, 1))
    self.st.reshape((4, 16, 1, 1))
    self.st.permute((1, 0, 2, 3))
    assert self.st.contiguous

  def test_fancy_factorize(self):
    self.st = CheckingShapeTracker((32, 3, 3, 1))
    self.st.reshape((8, 4, 3, 3))
    assert len(self.st.views) == 1

  def test_super_complex_2_fail(self):
    self.st = CheckingShapeTracker((4, 4, 4))
    self.st.permute((2, 0, 1))
    self.st.reshape((16, 4))
    assert len(self.st.views) != 1

  def test_work(self):
    self.st = CheckingShapeTracker((64, 1024, 4))
    self.st.reshape((1, 64, 128, 32))
    self.st.permute((0, 3, 1, 2))
    self.st.reshape((1, 32, 1, 64, 128))
    self.st.permute((0, 3, 4, 1, 2))
    assert self.st.contiguous

  def test_work2(self):
    self.st = CheckingShapeTracker((64, 1024, 4))
    self.st.reshape((1, 64, 128, 32))
    self.st.permute((0, 3, 1, 2))
    self.st.reshape((1, 1, 32, 64, 128))
    self.st.permute((0, 3, 4, 1, 2))
    self.st.reshape((64, 1024, 4))
    print(self.st.views)
    assert self.st.contiguous

class TestSingleShapeTracker(unittest.TestCase):
  def setUp(self):
    self.st = CheckingShapeTracker((7,4))

  def tearDown(self):
    self.st.assert_same()

  def test_reshape(self):
    self.st.reshape((7,1,4))
    assert self.st.contiguous

  def test_permute(self):
    self.st.permute((1,0))
    assert not self.st.contiguous

  def test_shrink(self):
    self.st.shrink(((1,2), (0,4)))
    assert not self.st.contiguous

  def test_double_permute(self):
    self.st.permute((1,0))
    self.st.permute((1,0))
    assert self.st.contiguous

  def test_reshape_permute(self):
    self.st.reshape((7,1,4))
    self.st.permute((0,1,2))
    assert self.st.contiguous

  def test_reshape_permute_yes(self):
    self.st.reshape((7,1,4))
    self.st.permute((0,2,1))
    assert self.st.contiguous

  def test_reshape_permute_no(self):
    self.st.reshape((4,7))
    self.st.permute((1,0))
    assert not self.st.contiguous

class TestShapeTrackerFuzzFailures(unittest.TestCase):
  def setUp(self):
    self.st = CheckingShapeTracker((3,3,3))
  def tearDown(self):
    self.st.assert_same()
  @unittest.skip("simplify doesn't work in this case")
  def test_case_1(self):
    self.st.shrink(((1, 2), (1, 3), (1, 3)))
    self.st.reshape((1, 4))
    self.st.shrink(((0, 1), (1, 3)))
    print(self.st.st)
    self.st.simplify()
    print(self.st.st)
  def test_case_2(self):
    self.st.stride( (1, 1, -2) )
    self.st.reshape( (3, 6) )
    self.st.shrink( ((1, 2), (1, 5)) )
    self.st.stride( (1, -1) )
  def test_case_3(self):
    self.st.shrink( ((0, 2), (0, 2), (0, 1)) )
    self.st.permute( (1, 0, 2) )
    self.st.reshape( (4,) )
    self.st.shrink( ((0, 3),) )
    self.st.stride( (-1,) )
  def test_case_4(self):
    self.st.reshape( (3, 3, 3, 1) )
    self.st.pad( ((0, 0), (0, 0), (0, 0), (1, 1)) )
    self.st.shrink( ((0, 2), (1, 2), (0, 2), (0, 1)) )
    self.st.expand( (2, 1, 2, 3) )

class TestMaskedShapeTracker(unittest.TestCase):
  def test_pad_1x1(self):
    self.st = CheckingShapeTracker((1,1))
    self.st.pad(((1,1), (1,1)))
    self.st.assert_same()

  def test_pad_2x2(self):
    self.st = CheckingShapeTracker((2,2))
    self.st.pad(((1,1), (1,1)))
    self.st.assert_same()

class TestShapeTracker(unittest.TestCase):
  def setUp(self):
    self.st = CheckingShapeTracker((7,4))
    self.apply = lambda fxn: [fxn(x) for x in [self.st]]

  def tearDown(self):
    self.st.assert_same()

  def test_noop(self):
    pass

  def test_simple_split(self):
    self.test_permute()
    self.apply(lambda x: x.reshape((prod(self.st.shape), )))

  def test_simple_pad(self):
    self.st.pad(((1,1), (1,1)))

  def test_pad_shrink(self):
    self.st.pad(((1,1), (1,1)))
    self.st.shrink(((0,4), (0,4)))

  def test_pad_one_sided(self):
    self.st.pad(((0,1), (0,0)))

  def test_pad_reshape(self):
    self.st.pad(((0,1), (0,0)))
    self.st.reshape((8*4,))

  def test_pad_pad(self):
    self.st.pad(((1,1), (1,1)))
    self.st.pad(((1,1), (1,1)))

  def test_pad_permute(self):
    self.st.pad(((1,1), (2,2)))
    self.st.permute((1,0))

  def test_pad_expand(self):
    self.st.reshape((7,4,1))
    self.st.pad(((1,1), (1,1), (0,0)))
    self.st.expand((9,6,4))

  def test_pad_expand_alt(self):
    self.st.pad(((1,1), (1,1)))
    self.st.reshape((9,6,1))
    self.st.expand((9,6,4))

  def test_pad_stride(self):
    self.st.pad(((1,4), (1,3)))
    self.st.stride((2,2))

  def test_pad_stride_neg(self):
    self.st.pad(((1,2), (1,0)))
    self.st.stride((-1,-1))

  def test_pad_stride_both(self):
    self.st.pad(((1,2), (1,0)))
    self.st.stride((-2,-2))

  def test_shrink_pad(self):
    self.st.shrink(((0,4), (0,4)))
    self.st.pad(((1,1), (1,1)))

  def test_reshape(self):
    new_shape = self.st.shape[::-1]
    self.apply(lambda x: x.reshape(new_shape))

  def test_permute(self):
    if len(self.st.shape) == 2: self.apply(lambda x: x.permute((1,0)))
    elif len(self.st.shape) == 3: self.apply(lambda x: x.permute((2,0,1)))

  def test_reshape_with_1(self):
    new_shape = (self.st.shape[0], 1, self.st.shape[1])
    self.apply(lambda x: x.reshape(new_shape))

  def test_expand(self):
    self.test_reshape_with_1()
    new_shape = list(self.st.shape)
    new_shape[1] = 2
    self.apply(lambda x: x.expand(tuple(new_shape)))

  def test_flip_0(self):
    self.apply(lambda x: x.flip((0,)))

  def test_flip_1(self):
    self.apply(lambda x: x.flip((1,)))

  def test_flip_01(self):
    self.apply(lambda x: x.flip((0,1)))

  def test_slice_0(self):
    self.apply(lambda x: x.shrink(((1, x.shape[0]), (0, x.shape[1]))))

  def test_slice_1(self):
    self.apply(lambda x: x.shrink(((0, x.shape[0]), (1, x.shape[1]))))

  def test_slice_1c1(self):
    self.apply(lambda x: x.shrink(((0, 1), (0, 1))))

  def test_slice_1c2(self):
    self.apply(lambda x: x.shrink(((1, 2), (1, 2))))

  def test_double_permute(self):
    self.apply(lambda x: x.permute((1, 0)))
    self.apply(lambda x: x.permute((1, 0)))

  def test_slice_permute(self):
    self.apply(lambda x: x.shrink(((0, 2), (2, 4))))
    self.apply(lambda x: x.permute((1, 0)))

  def test_slice_expand(self):
    self.apply(lambda x: x.shrink(((0, 2), (3, 4))))
    self.apply(lambda x: x.expand((2, 10)))

  def test_double_stride(self):
    self.apply(lambda x: x.stride((1, 2)))
    self.apply(lambda x: x.stride((2, 1)))

  def test_stride(self): self.apply(lambda x: x.stride((2,1)))
  def test_stride_int(self): self.apply(lambda x: x.stride((1,2)))
  def test_stride_2(self): self.apply(lambda x: x.stride((2,2)))
  def test_stride_n(self): self.apply(lambda x: x.stride((-2,1)))
  def test_stride_int_n(self): self.apply(lambda x: x.stride((-1,2)))
  def test_stride_2_n(self): self.apply(lambda x: x.stride((-2,-2)))

  def test_reshape_then_permute(self):
    self.test_reshape()
    self.test_permute()

  def test_reshape_then_expand(self):
    self.test_reshape()
    self.test_expand()

  def test_permute_then_reshape(self):
    self.test_permute()
    self.test_reshape()

  def test_expand_then_reshape(self):
    self.test_expand()
    self.test_reshape()

  def test_combo(self):
    self.test_permute()
    self.test_reshape()
    self.test_slice_1()
    self.test_expand()
    self.test_permute()

class TestGetContraction(unittest.TestCase):
  def test_contraction(self):
    r = get_contraction((1,2,3,4), (2,3,4))
    self.assertEqual(r, [[0, 1], [2], [3]])

    r = get_contraction((2,1,3,4), (2,3,4))
    self.assertEqual(r, [[0], [1, 2], [3]])

    r = get_contraction((1,2,3,1,4), (1,2,3,4))
    self.assertEqual(r, [[0], [1], [2], [3, 4]])

    r = get_contraction((1,2,3,1,4,1,1), (2,3,4))
    self.assertEqual(r, [[0, 1], [2], [3, 4, 5, 6]])

    r = get_contraction((1,2,3,4), (1,2,3*4))
    self.assertEqual(r, [[0], [1], [2, 3]])

    r = get_contraction((1,2,3,4), (2,1,3,4))
    self.assertEqual(r, [[0, 1], [], [2], [3]])

    r = get_contraction((1,2,3,4), (1,1,2*3*4,1))
    self.assertEqual(r, [[0], [], [1,2,3], []])

    r = get_contraction((2,1,3,4), (1,2,3,4))
    self.assertEqual(r, [[], [0], [1, 2], [3]])

    r = get_contraction((1,2,3,4), (2*3*4,1,1,1))
    self.assertEqual(r, [[0, 1, 2, 3], [], [], []])

    r = get_contraction((4,4,4,4), (16,1,16))
    self.assertEqual(r, [[0, 1], [], [2, 3]])

    r = get_contraction((1,2,3,4,1,1,1), (2,3,4))
    self.assertEqual(r, [[0, 1], [2], [3, 4, 5, 6]])

    r = get_contraction((1,2,3,4), (1,2,3,4,1))
    self.assertEqual(r, [[0], [1], [2], [3], []])

    r = get_contraction((14,1,384,14,1,1,1,1), (1,14,384,14))
    self.assertEqual(r, [[], [0], [1,2], [3,4,5,6,7]])

    r = get_contraction((14,1,384,1,14,1,1,1,1), (1,14,384,14))
    self.assertEqual(r, [[], [0], [1,2], [3,4,5,6,7,8]])

    r = get_contraction((512, 512), (1, 1, 512, 1, 1, 1, 1, 512))
    self.assertEqual(r, [[], [], [0], [], [], [], [], [1]])

    r = get_contraction((1,2,3,4), (1,2,6,2))
    self.assertEqual(r, None)

if __name__ == '__main__':
  unittest.main()
