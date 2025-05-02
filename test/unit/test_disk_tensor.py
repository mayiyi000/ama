import pathlib
import unittest
import numpy as np
from tinygrad.tensor import Tensor

class TestDiskTensor(unittest.TestCase):
  def test_empty(self):
    pathlib.Path("/tmp/dt1").unlink(missing_ok=True)
    Tensor.empty(100, 100, device="disk:/tmp/dt1")

  def test_write_ones(self):
    pathlib.Path("/tmp/dt2").unlink(missing_ok=True)

    out = Tensor.ones(10, 10, device="CPU")
    outdisk = out.to("disk:/tmp/dt2")
    print(outdisk)
    outdisk.realize()
    del out, outdisk

    # test file
    with open("/tmp/dt2", "rb") as f:
      assert f.read() == b"\x00\x00\x80\x3F" * 100

    # test load alt
    reloaded = Tensor.empty(10, 10, device="disk:/tmp/dt2")
    out = reloaded.numpy()
    assert np.all(out == 1.)

  def test_slice(self):
    pathlib.Path("/tmp/dt3").unlink(missing_ok=True)
    Tensor.arange(10, device="disk:/tmp/dt3").realize()

    slice_me = Tensor.empty(10, device="disk:/tmp/dt3")
    print(slice_me)
    is_3 = slice_me[3:4].cpu()
    assert is_3.numpy()[0] == 3

  def test_slice_2d(self):
    pathlib.Path("/tmp/dt5").unlink(missing_ok=True)
    Tensor.arange(100, device="CPU").to("disk:/tmp/dt5").realize()
    slice_me = Tensor.empty(10, 10, device="disk:/tmp/dt5")
    tst = slice_me[1].numpy()
    print(tst)
    np.testing.assert_allclose(tst, np.arange(10, 20))

  def test_assign_slice(self):
    pathlib.Path("/tmp/dt4").unlink(missing_ok=True)
    cc = Tensor.arange(10, device="CPU").to("disk:/tmp/dt4").realize()
    #cc.assign(np.ones(10)).realize()
    print(cc[3:5].numpy())
    cc[3:5].assign([13, 12]).realize()
    print(cc.numpy())

if __name__ == "__main__":
  unittest.main()
