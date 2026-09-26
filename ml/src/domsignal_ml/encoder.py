"""Shared BERT encoder with class, gate, utterance and safety heads."""
from __future__ import annotations

import torch
from torch import nn
from transformers import AutoModel


class MultiHead(nn.Module):
    def __init__(self, pretrained: str, class_count: int, utt_count: int):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(pretrained)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(hidden, class_count)
        self.gate = nn.Linear(hidden, 2)
        self.utterance = nn.Linear(hidden, utt_count)
        self.safety = nn.Linear(hidden, 2)

    def forward(self, input_ids, attention_mask, token_type_ids=None):
        kwargs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if token_type_ids is not None:
            kwargs["token_type_ids"] = token_type_ids
        output = self.encoder(**kwargs)
        pooled = self.dropout(output.last_hidden_state[:, 0, :])
        return (self.classifier(pooled), self.gate(pooled),
                self.utterance(pooled), self.safety(pooled))
