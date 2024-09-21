from typing import Callable, List, Tuple, Any, Dict, cast, Union
import functools, itertools
from tinygrad.helpers import DEBUG, DType

from tinygrad.lazy import Device
from tinygrad.tensor import Tensor
from tinygrad.ops import GlobalCounters, RawBuffer

class TinyJit:
  def __init__(self, fxn:Callable):
    self.fxn: Callable = fxn
    self.cnt: int = 0
    self.jit_cache: List[Tuple[Callable, Any]] = []  # TODO: Any should be List[RawBuffer], but this fails
    self.ret: Any = None
    self.input_replace: Dict[Tuple[int, int], Tuple[Union[int, str], int, DType]]= {}   # (kernel_number, buffer_number) -> (input_name, expected_size, expected_type)

  # add support for instance methods
  def __get__(self, obj, objtype): return functools.partial(self.__call__, obj)

  def __call__(self, *args, **kwargs) -> Any:
    if Device.DEFAULT not in ["GPU", "CLANG", "METAL", "CUDA"]: return self.fxn(*args, **kwargs)  # only jit on the GPU codegen
    # NOTE: this cast is needed since although we know realize will create a ".realized" DeviceBuffer, the type checker doesn't
    input_rawbuffers: Dict[Union[int, str], RawBuffer] = {cast(Union[int, str], k):cast(RawBuffer, v.realize().lazydata.realized) for k,v in itertools.chain(enumerate(args), kwargs.items()) if isinstance(v, Tensor)}
    assert len(input_rawbuffers) != 0, "no inputs to JIT"
    assert len(set(input_rawbuffers.values())) == len(input_rawbuffers), "duplicate inputs to JIT"
    if self.cnt >= 2:
      for (j,i),(input_name, expected_size, expected_type) in self.input_replace.items():
        assert input_rawbuffers[input_name].size == expected_size and input_rawbuffers[input_name].dtype == expected_type, f"size or type mismatch in JIT, {input_rawbuffers[input_name]} != <{expected_size}, {expected_type}>"
        self.jit_cache[j][1][i] = input_rawbuffers[input_name]
      for prg, args in self.jit_cache: prg(args, jit=True)
      for (j,i) in self.input_replace.keys(): self.jit_cache[j][1][i] = None
    elif self.cnt == 1:
      GlobalCounters.cache = []
      self.ret = self.fxn(*args, **kwargs)
      self.jit_cache = GlobalCounters.cache
      GlobalCounters.cache = None
      assert len(self.jit_cache) != 0, "didn't JIT anything!"
      if DEBUG >= 1: print(f"JIT captured {len(self.jit_cache)} kernels with {len(input_rawbuffers)} inputs")

      # get the inputs for replacement
      for j,(prg,args) in enumerate(self.jit_cache):  # pylint: disable=E1133
        for i,a in enumerate(args):
          if a in input_rawbuffers.values():
            self.input_replace[(j,i)] = [(k, v.size, v.dtype) for k,v in input_rawbuffers.items() if v == a][0]
        #if prg.local_size is None: prg.local_size = prg.optimize_local_size(args, preserve_output=True)  # the JIT can optimize local
      assert set([x[0] for x in self.input_replace.values()]) == set(input_rawbuffers.keys()), "some input tensors not found"
      for (j,i) in self.input_replace.keys(): self.jit_cache[j][1][i] = None
    elif self.cnt == 0:
      self.ret = self.fxn(*args, **kwargs)
    self.cnt += 1
    return self.ret
