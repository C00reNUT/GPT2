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
    """Transformer-based decoder layer.

    Arguments:
        heads (int): The number of attention heads.
        dims (int): The dimension of input tensor.
        rate (int): The increase rate of dimensionality in bottleneck.
        dropout (float): The probability that each element is dropped.

    Note:
        In case of GPT-2, layer normalizations are performed before the
        attention and feed-forward layer respectively.
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
        """Apply transformer-based decoder layer.

        Arguments:
            x (tensor): Input tensor of shape `(..., seq_len, dims)`.
            past (tuple): The tuple of previously calculated key-value tensors
                of shape `(..., past_len, dims)`.
            mask (tensor): Masking tensor of shape `(..., query_len, kv_len)`.

        Returns:
            * An output tensor which has same shape as ``q``.
            * A tuple of projected key-value tensors of shape
              `(..., past_len + kv_len, dims)`.
        """
        x = self.ln_attn(x)
        a, past = self.attn(x, x, x, past, mask)

        x = self.ln_ff(x + a)
        a = self.ff(x)

        return x + a, past


class GPT2(nn.Module):
    """Implementation of OpenAI GPT-2.

    Arguments:
        layers (int): The number of decoder layers.
        pad_idx (int): Index of pad token.
        words (int): The number of words in vocabulary.
        seq_len (int): The maximum length of input sequences.
        heads (int): The number of attention heads.
        dims (int): The dimension of representation tensor in each layer.
        rate (int): The increase rate of dimensionality in bottleneck.
        dropout (float): The probability that each element is dropped.
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
        """Predict next words from the given subsequences.

        Argument:
            x: Input tensor of shape `(..., seq_len)`.
            past: The list of tuples containing previously calculated key-value
                tensors of shape `(..., past_len, dims)`.

        Returns:
            * A logits of next-word distributions.
            * A list of tuples containing projected key-value tensors of shape
              `(..., past_len + seq_len, dims)`.
        """
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
