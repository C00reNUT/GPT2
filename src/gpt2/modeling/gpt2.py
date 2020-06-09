import torch
import torch.nn as nn
from .masking import PadMasking, FutureMasking
from .embedding import PositionalEmbedding, TokenEmbedding
from .attention import AttentionBlock
from .feedforward import PositionwiseFeedForward
from typing import Optional, Tuple, List


# Try to import `apex` library for using fused layer-norm. Note that if `apex`
# is installed, then ``FusedLayerNorm`` would be used automatically.
try:
    from apex.normalization import FusedLayerNorm as MyLayerNorm
except ModuleNotFoundError:
    from torch.nn import LayerNorm as MyLayerNorm


class DecoderBlock(nn.Module):
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
    def __init__(self, heads: int, dims: int, rate: int, dropout: float = 0.1):
        super().__init__()
        self.attn = AttentionBlock(heads, dims, dropout)
        self.ff = PositionwiseFeedForward(dims, rate, dropout)
        self.ln_attn = MyLayerNorm(dims)
        self.ln_ff = MyLayerNorm(dims)

    def forward(self,
                x: torch.Tensor,
                past: Optional[Tuple[torch.Tensor]] = None,
                mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        x = self.ln_attn(x)
        a, past = self.attn(x, x, x, past, mask)

        x = self.ln_ff(x + a)
        a = self.ff(x)

        return x + a, past


class GPT2(nn.Module):
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
                 dropout: float = 0.1):
        super().__init__()
        self.pad_masking = PadMasking(pad_idx)
        self.future_masking = FutureMasking()

        self.positional_embedding = PositionalEmbedding(seq_len, dims)
        self.token_embedding = TokenEmbedding(words, dims)
        self.dropout_embedding = nn.Dropout(dropout)

        self.decoders = nn.ModuleList([
            DecoderBlock(heads, dims, rate, dropout) for _ in range(layers)])
        self.ln_head = MyLayerNorm(dims)

    def forward(self,
                x: torch.Tensor,
                past: Optional[Tuple[torch.Tensor]] = None
                ) -> Tuple[torch.Tensor, List[Tuple[torch.Tensor]]]:
        # The past key-value pairs imply that input sequences are shifted.
        offset = past[0][0].size(-2) if past is not None else 0

        # Create masking tensor.
        mask = self.pad_masking(x, offset) + self.future_masking(x, offset)

        # Create embedding vectors with dropout layer.
        x = self.token_embedding(x) + self.positional_embedding(x, offset)
        x = self.dropout_embedding(x)

        # Apply transformer-based decoder layers sequentially.
        present = []
        for i, decoder in enumerate(self.decoders):
            x, p = decoder(x, past[i] if past is not None else None, mask)
            present.append(p)

        # Predict next words by projecting representations to vocabulary space.
        x = self.ln_head(x)
        x = self.token_embedding(x, transposed=True)

        return x, present
