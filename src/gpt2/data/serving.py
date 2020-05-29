import torch
from .vocabulary import Vocabulary
from typing import Optional, Union, List, Dict


class DataLoader(object):
    """Simple data loader from file.

    DataLoader loads sequences by reading file and encodes them through the
    given vocabulary. Special tokens are added to each sequence.

    Arguments:
        vocab (Vocabulary): The vocabulary object.
        corpus (str): Corpus file path.
        seq_len (int): The maximum length of each sequence.
    """
    def __init__(self, vocab: Vocabulary, corpus: str, seq_len: int):
        self.vocab = vocab
        self.corpus_fp = open(corpus, 'r', encoding='utf-8')
        self.seq_len = seq_len

    def close(self):
        """Close resources."""
        self.corpus_fp.close()

    def _fetch_one(self) -> Dict[str, torch.Tensor]:
        while True:
            # Get sequence by reading file.
            line = self.corpus_fp.readline()

            # If current position is end of file, move to first and read again.
            if not line:
                self.corpus_fp.seek(0)
                continue

            # Map each subword to its index.
            indices = [self.vocab[t] for t in line.split()]

            # Skip if the sequence is too long.
            if len(indices) > self.seq_len - 2:
                continue

            # Add speical tokens.
            indices = [self.vocab.bos_idx] + indices + [self.vocab.eos_idx]
            indices += ([self.vocab.pad_idx]
                        * (self.seq_len - len(indices) + 1))

            return {'input': indices[:-1], 'output': indices[1:]}

    def fetch(self,
              batch: Optional[int] = None
              ) -> Union[Dict[str, torch.Tensor],
                         List[Dict[str, torch.Tensor]]]:
        """Fetch sequences from the corpus.

        Arguments:
            batch (int): The number of sequences in batch.

        Returns:
            A tensor of shape `(seq_len)` is ``batch=None`` else a list of
            tensor of shape `(batch, seq_len)`.
        """
        if batch is None:
            data = self._fetch_one()
        else:
            data = {}
            for _ in range(batch):
                for k, v in self._fetch_one().items():
                    if k not in data:
                        data[k] = []
                    data[k].append(v)

        # Cast each sequence to tensor.
        return {k: torch.tensor(v, dtype=torch.long) for k, v in data.items()}

    def seek(self, offset: int):
        """Set current position of the corpus file at the given offset."""
        self.corpus_fp.seek(offset)

    def tell(self) -> int:
        """Return the current position of the corpus file."""
        return self.corpus_fp.tell()
