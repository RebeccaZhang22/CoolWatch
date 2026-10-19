"""One fused gather/add/copy per selected layer; graph selection lives on GPU."""
import triton
import triton.language as tl


@triton.jit
def capture_decode(H, R, Table, Out, LAYER: tl.constexpr, CAP: tl.constexpr,
                   WIDTH: tl.constexpr, HS: tl.constexpr, RS: tl.constexpr,
                   HAS_RESIDUAL: tl.constexpr, BLOCK: tl.constexpr):
    row = tl.program_id(0)
    ffn_dst = tl.load(Table + (LAYER * 2) * CAP + row)
    block_dst = tl.load(Table + (LAYER * 2 + 1) * CAP + row)
    if (ffn_dst >= 0) | (block_dst >= 0):
        col = tl.arange(0, BLOCK)
        h = tl.load(H + row * HS + col, col < WIDTH, 0)
        if ffn_dst >= 0:
            tl.store(Out + ffn_dst * WIDTH + col, h, col < WIDTH)
        if block_dst >= 0:
            value = h.to(tl.float32)
            if HAS_RESIDUAL:
                value += tl.load(R + row * RS + col, col < WIDTH, 0).to(tl.float32)
            tl.store(Out + block_dst * WIDTH + col, value, col < WIDTH)


@triton.jit
def capture_extend(H, R, Rows, Sites, Out, WIDTH: tl.constexpr,
                   HS: tl.constexpr, RS: tl.constexpr, HAS_RESIDUAL: tl.constexpr,
                   BLOCK: tl.constexpr):
    dest = tl.program_id(0)
    row = tl.load(Rows + dest)
    site = tl.load(Sites + dest)
    col = tl.arange(0, BLOCK)
    value = tl.load(H + row * HS + col, col < WIDTH, 0).to(tl.float32)
    if HAS_RESIDUAL:
        if site == 1:
            value += tl.load(R + row * RS + col, col < WIDTH, 0).to(tl.float32)
    tl.store(Out + dest * WIDTH + col, value, col < WIDTH)
