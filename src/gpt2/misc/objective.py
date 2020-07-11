import torch
import torch.nn as nn
from typing import Dict, Any


class Objective(object):
    def __init__(self, model: nn.Module):
        self.model = model

    def loss(self, inputs: torch.Tensor, outputs: torch.Tensor
             ) -> torch.Tensor:
        raise NotImplementedError()

    def state_dict(self) -> Dict[str, Any]:
        return {}

    def load_state_dict(self, state_dict: Dict[str, Any]):
        pass


class LMObjective(Objective):
    def __init__(self, model: nn.Module, pad_idx: int = 0):
        super().__init__(model)
        self.criterion = nn.CrossEntropyLoss(ignore_index=pad_idx,
                                             reduction='mean')

    def loss(self, inputs: torch.Tensor, outputs: torch.Tensor
             ) -> torch.Tensor:
        logits, _ = self.model(inputs, None)
        return self.criterion(logits.transpose(1, 2), outputs)
