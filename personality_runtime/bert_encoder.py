"""可选 BERT 大五人格编码器。

默认模型：Minej/bert-base-personality（BERT-base-uncased，英文为主）
标签顺序：Extroversion, Neuroticism, Agreeableness, Conscientiousness, Openness

未安装 torch/transformers、或权重下载失败时，调用方应回退到启发式。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from .traits import MINEJ_LABELS, clamp01

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "Minej/bert-base-personality"


class BertPersonalityEncoder:
    def __init__(self, model_id: str | None = None, autoload: bool | None = None):
        self.model_id = model_id or os.getenv("PERSONALITY_MODEL", DEFAULT_MODEL_ID)
        self.tokenizer = None
        self.model = None
        self.available = False
        self.error = ""
        self.torch = None
        self._tried = False
        disabled = os.getenv("PERSONALITY_DISABLE_BERT", "").strip() in {"1", "true", "yes"}
        if autoload is None:
            autoload = not disabled
        if autoload:
            self._load()

    def _load(self) -> None:
        self._tried = True
        if os.getenv("PERSONALITY_DISABLE_BERT", "").strip() in {"1", "true", "yes"}:
            self.error = "PERSONALITY_DISABLE_BERT=1，跳过 BERT"
            return
        if "unittest" in sys.modules and os.getenv("PERSONALITY_ENABLE_BERT", "").strip() not in {"1", "true", "yes"}:
            self.error = "测试环境默认跳过 BERT 权重下载"
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            self.error = f"未安装 transformers/torch: {exc}"
            logger.warning(self.error)
            return
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
            self.model.eval()
            self.torch = torch
            self.available = True
            logger.info("loaded personality encoder %s", self.model_id)
        except Exception as exc:  # network / cache / architecture
            self.error = f"无法加载 {self.model_id}: {exc}"
            logger.warning(self.error)

    def score(self, text: str) -> dict[str, float]:
        if not self._tried:
            self._load()
        if not self.available or not text.strip():
            return {}
        encoded = self.tokenizer(
            text,
            truncation=True,
            padding=True,
            max_length=256,
            return_tensors="pt",
        )
        with self.torch.no_grad():
            logits = self.model(**encoded).logits.squeeze()
        values = logits.detach().cpu().tolist()
        if not isinstance(values, list):
            values = [float(values)]
        result: dict[str, float] = {}
        for index, name in enumerate(MINEJ_LABELS):
            raw = float(values[index]) if index < len(values) else 0.5
            # 模型卡示例把 logits 当 0-1；若超出则做 sigmoid
            if raw < 0.0 or raw > 1.0:
                raw = 1.0 / (1.0 + pow(2.718281828, -raw))
            result[name] = round(clamp01(raw), 4)
        return result

    def info(self) -> dict[str, Any]:
        return {
            "backend": "bert" if self.available else "unavailable",
            "model_id": self.model_id,
            "available": self.available,
            "error": self.error,
            "labels": list(MINEJ_LABELS),
        }
