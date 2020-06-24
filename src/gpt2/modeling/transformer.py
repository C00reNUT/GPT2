import torch
import torch.nn as nn
from .masking import PadMasking, FutureMasking
from .embedding import PositionalEmbedding, TokenEmbedding
from .attention import AttentionLayer
from .feedforward import PositionwiseFeedForward
from typing import Optional, Tuple, List


# Try to import `apex` library for using fused layer-norm. Note that if `apex`
# is installed, then ``FusedLayerNorm`` would be used automatically.
try:
    from apex.normalization import FusedLayerNorm as LayerNorm
except ModuleNotFoundError:
    from torch.nn import LayerNorm


class TransformerLayer(nn.Module):
    """
    Tensor          Type            Shape
    ===========================================================================
    x               float           (..., seq_len, dims)
    past (*)        float           (..., past_len, dims)
    mask            bool            (..., seq_len, past_len + seq_len)
    ---------------------------------------------------------------------------
    output 1        float           (..., seq_len, dims)
    output 2 (*)    float           (..., past_len + seq_len, dims)
    ===========================================================================
    """
    def __init__(self,
                 heads: int,
                 dims: int,
                 rate: int,
                 dropout: float = 0.1):
        super().__init__()
        self.attn = AttentionLayer(heads, dims, dropout)
        self.ff = PositionwiseFeedForward(dims, rate, dropout)
        self.ln_attn = LayerNorm(dims)
        self.ln_ff = LayerNorm(dims)

    def forward(self,
                x: torch.Tensor,
                past: Optional[Tuple[torch.Tensor]] = None,
                mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        # Layer normalizations are performed before the layers respectively.
        a = self.ln_attn(x)
        a, past = self.attn(a, a, a, past, mask)

        x += a
        x += self.ff(self.ln_ff(x))

        return x, past


class Transformer(nn.Module):
    """
    Tensor          Type            Shape
    ===========================================================================
    x               long            (..., seq_len)
    past (**)       float           (..., past_len, dims)
    ---------------------------------------------------------------------------
    output 1        float           (..., seq_len, dims)
    output 2 (**)   float           (..., past_len + seq_len, dims)
    ===========================================================================
    """
    def __init__(self,
                 layers: int,
                 pad_idx: int,
                 words: int,
                 seq_len: int,
                 heads: int,
                 dims: int,
                 rate: int = 4,
                 dropout: float = 0.1,
                 bidirectional: bool = True):
        super().__init__()
        self.bidirectional = bidirectional
        self.pad_masking = PadMasking(pad_idx)
        self.future_masking = FutureMasking()

        self.positional_embedding = PositionalEmbedding(seq_len, dims)
        self.token_embedding = TokenEmbedding(words, dims)
        self.dropout_embedding = nn.Dropout(dropout)

        self.transformers = nn.ModuleList([
            TransformerLayer(heads, dims, rate, dropout)
            for _ in range(layers)])
        self.ln_head = LayerNorm(dims)

    def forward(self,
                x: torch.Tensor,
                past: Optional[Tuple[torch.Tensor]] = None
                ) -> Tuple[torch.Tensor, List[Tuple[torch.Tensor]]]:
        # The past key-value pairs imply that input sequences are shifted.
        offset = past[0][0].size(-2) if past is not None else 0

        # Create masking tensor.
        mask = self.pad_masking(x, offset)
        if not self.bidirectional:
            mask = mask + self.future_masking(x, offset)

        # Create embedding vectors with dropout layer.
        x = self.token_embedding(x) + self.positional_embedding(x, offset)
        x = self.dropout_embedding(x)

        # Apply transformer layers sequentially.
        present = []
        for i, transformer in enumerate(self.transformers):
            x, p = transformer(x, past[i] if past is not None else None, mask)
            present.append(p)

        # Project representations to vocabulary space.
        x = self.ln_head(x)
        x = self.token_embedding(x, transposed=True)

        return x, present
