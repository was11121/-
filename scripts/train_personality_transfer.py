"""迁移学习微调：从 Minej/bert-base-personality warm-start，再校准到 PANDORA。

与前几轮的本质区别：
1. 基座不是冷启动 bert-base-uncased / MLM，而是已在大五任务上训练过的
   `Minej/bert-base-personality`（本地 models/minej-bert-personality）。
2. 分类头**不清零、不随机 init**，直接 warm-start。minej 标签顺序
   E,N,A,C,O 与 scoring.TRAIT_ORDER 完全一致，逐维对齐。
3. 两阶段训练：
   - 阶段 1：冻结整个 BERT，只训分类头，把 minej 的窄带输出校准到 PANDORA 的 0-1 尺度。
   - 阶段 2：解冻后两层 + 分类头，小 lr 微调表示。
4. 仍按作者切分 + bag-mean 损失（与线上多句 EMA 一致），锁定测试集不变。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import numpy as np
import pandas as pd
import torch
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from personality_runtime.pandora_prep import (  # noqa: E402
    MAX_COMMENTS_PER_AUTHOR,
    make_author_bags,
    prepare_pandora_frame,
    split_by_author,
)
from personality_runtime.scoring import (  # noqa: E402
    TRAIT_ORDER,
    inverse_std_weights,
    regression_report,
    sigmoid_np,
)

DATA_PATH = os.path.join(PROJECT_ROOT, "data", "psych_eval", "pandora_train.parquet")
SPLIT_DIR = os.path.join(PROJECT_ROOT, "data", "psych_eval", "splits")
TEST_PATH = os.path.join(SPLIT_DIR, "pandora_test.parquet")
SPLIT_META_PATH = os.path.join(SPLIT_DIR, "split_meta.json")
BASE_MODEL_ID = os.path.join(PROJECT_ROOT, "models", "minej-bert-personality")
OUT_DIR = os.path.join(PROJECT_ROOT, "models", "psych-personality-bert-transfer")
WORK_DIR = os.path.join(PROJECT_ROOT, "models", "psych-personality-bert-transfer-work")

SEED = 42
MAX_LENGTH = 256
HUBER_DELTA = 0.1
BAG_SIZE = 16
TRAIN_BAGS = 8
FREEZE_BELOW_LAYER = 10  # 阶段2解冻 layer 10-11
HEAD_LR = 5e-4
BACKBONE_LR = 2e-5


def seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_and_prepare():
    df = pd.read_parquet(DATA_PATH)
    prepared, prep_stats = prepare_pandora_frame(df, max_comments_per_author=MAX_COMMENTS_PER_AUTHOR, seed=SEED)
    train_c, val_c, test_c, split_meta = split_by_author(prepared, seed=SEED, test_size=0.1, val_size=0.1)

    # 校验重新生成的测试集与已锁定测试集一致（作者集合与行数）
    locked = pd.read_parquet(TEST_PATH)
    locked_authors = set(locked["author_id"].tolist())
    new_authors = set(test_c["author_id"].tolist())
    if locked_authors != new_authors or len(locked) != len(test_c):
        raise RuntimeError(
            f"重新切分与锁定测试集不一致：locked {len(locked)}/{len(locked_authors)}a vs new {len(test_c)}/{len(new_authors)}a"
        )
    print(f"测试集一致性校验通过：{len(locked)} 条 / {len(locked_authors)} 作者")

    train_bags = make_author_bags(train_c, bag_size=BAG_SIZE, n_bags=TRAIN_BAGS, seed=SEED)
    val_bags = make_author_bags(val_c, bag_size=BAG_SIZE, n_bags=1, seed=SEED)
    meta = {
        **prep_stats,
        **split_meta,
        "trait_order": TRAIT_ORDER,
        "label_scale": 99.0,
        "mode": "author_bag_mean_transfer",
        "base_model": BASE_MODEL_ID,
        "bag_size": BAG_SIZE,
        "train_bags": TRAIN_BAGS,
        "n_train_bags": int(len(train_bags)),
        "n_val_bags": int(len(val_bags)),
        "max_length": MAX_LENGTH,
        "head_lr": HEAD_LR,
        "backbone_lr": BACKBONE_LR,
    }
    with open(SPLIT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return train_bags, val_bags, locked, meta


class BagDataset(torch.utils.data.Dataset):
    def __init__(self, bags: list[dict], tokenizer, max_length: int = MAX_LENGTH):
        self.labels = torch.tensor(np.stack([b["labels"] for b in bags]), dtype=torch.float32)
        self.author_ids = torch.tensor([b["author_id"] for b in bags], dtype=torch.long)
        self.encs = [
            tokenizer(
                bag["texts"],
                truncation=True,
                padding="max_length",
                max_length=max_length,
                return_tensors="pt",
            )
            for bag in bags
        ]

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        enc = self.encs[idx]
        return {
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
            "labels": self.labels[idx],
            "author_id": self.author_ids[idx],
        }


def collate_batch(features):
    max_s = max(int(f["input_ids"].shape[0]) for f in features)
    length = int(features[0]["input_ids"].shape[1])
    batch = len(features)
    input_ids = torch.zeros(batch, max_s, length, dtype=torch.long)
    attention_mask = torch.zeros(batch, max_s, length, dtype=torch.long)
    for i, feat in enumerate(features):
        size = int(feat["input_ids"].shape[0])
        input_ids[i, :size] = feat["input_ids"]
        attention_mask[i, :size] = feat["attention_mask"]
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": torch.stack([f["labels"] for f in features]),
        "author_id": torch.stack([f["author_id"] for f in features]),
    }


def _remap_layernorm_keys(state_dict: dict) -> dict:
    remapped = {}
    for key, value in state_dict.items():
        new_key = key
        if new_key.endswith(".gamma"):
            new_key = new_key[: -len(".gamma")] + ".weight"
        elif new_key.endswith(".beta"):
            new_key = new_key[: -len(".beta")] + ".bias"
        remapped[new_key] = value.detach().cpu().contiguous() if torch.is_tensor(value) else value
    return remapped


class TransferTrainer(Trainer):
    def __init__(self, *args, trait_weights: torch.Tensor | None = None, head_lr: float = HEAD_LR,
                 backbone_lr: float = BACKBONE_LR, **kwargs):
        super().__init__(*args, **kwargs)
        self.trait_weights = trait_weights
        self.head_lr = head_lr
        self.backbone_lr = backbone_lr

    def _bag_mean_scores(self, model, inputs):
        input_ids = inputs["input_ids"]
        attention_mask = inputs["attention_mask"]
        batch, bag, length = input_ids.shape
        outputs = model(
            input_ids=input_ids.view(batch * bag, length),
            attention_mask=attention_mask.view(batch * bag, length),
        )
        scores = torch.sigmoid(outputs.logits).view(batch, bag, -1)
        valid = (attention_mask.sum(dim=-1) > 0).to(dtype=scores.dtype).unsqueeze(-1)
        preds = (scores * valid).sum(dim=1) / valid.sum(dim=1).clamp(min=1.0)
        return preds, outputs

    def _huber(self, preds, labels):
        diff = preds - labels
        abs_diff = torch.abs(diff)
        huber = torch.where(
            abs_diff <= HUBER_DELTA,
            0.5 * diff ** 2,
            HUBER_DELTA * (abs_diff - 0.5 * HUBER_DELTA),
        )
        if self.trait_weights is not None:
            weights = self.trait_weights.to(device=huber.device, dtype=huber.dtype)
            return (huber * weights.view(1, -1)).mean()
        return huber.mean()

    def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=None):
        inputs = dict(inputs)
        labels = inputs.pop("labels", None)
        inputs.pop("author_id", None)
        with torch.no_grad():
            preds, _outputs = self._bag_mean_scores(model, inputs)
            loss = self._huber(preds, labels) if labels is not None else None
        if prediction_loss_only:
            return (loss, None, None)
        return (
            loss.detach() if loss is not None else None,
            preds.detach(),
            labels.detach() if labels is not None else None,
        )

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        inputs.pop("author_id", None)
        preds, outputs = self._bag_mean_scores(model, inputs)
        loss = self._huber(preds, labels)
        return (loss, outputs) if return_outputs else loss

    def create_optimizer(self):
        opt_cls = torch.optim.AdamW
        head_params = [p for n, p in self.model.named_parameters() if p.requires_grad and n.startswith("classifier")]
        backbone_params = [p for n, p in self.model.named_parameters() if p.requires_grad and not n.startswith("classifier")]
        groups = []
        if head_params:
            groups.append({"params": head_params, "lr": self.head_lr})
        if backbone_params:
            groups.append({"params": backbone_params, "lr": self.backbone_lr})
        self.optimizer = opt_cls(groups, weight_decay=self.args.weight_decay)
        return self.optimizer

    def _load_best_model(self, *args, **kwargs):
        checkpoint = getattr(self.state, "best_model_checkpoint", None)
        if not checkpoint:
            return super()._load_best_model(*args, **kwargs)
        weight_path = os.path.join(checkpoint, "model.safetensors")
        if not os.path.isfile(weight_path):
            return super()._load_best_model(*args, **kwargs)
        from safetensors.torch import load_file

        state = _remap_layernorm_keys(load_file(weight_path))
        self.model.load_state_dict(state, strict=False)
        print(f"已从最佳 checkpoint 加载：{checkpoint}")


def _freeze_backbone(model, freeze_below: int = FREEZE_BELOW_LAYER) -> None:
    bert = getattr(model, "bert", None)
    if bert is None:
        return
    for param in bert.embeddings.parameters():
        param.requires_grad = False
    for index, layer in enumerate(bert.encoder.layer):
        trainable = index >= freeze_below
        for param in layer.parameters():
            param.requires_grad = trainable
    n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_all = sum(p.numel() for p in model.parameters())
    print(f"冻结 embeddings + layer < {freeze_below}；可训练参数 {n_train}/{n_all}")


def _build_model():
    config = AutoConfig.from_pretrained(BASE_MODEL_ID)
    config.num_labels = len(TRAIT_ORDER)
    config.problem_type = "regression"
    config.id2label = {i: name for i, name in enumerate(TRAIT_ORDER)}
    config.label2id = {name: i for i, name in enumerate(TRAIT_ORDER)}
    if hasattr(config, "classifier_dropout"):
        config.classifier_dropout = 0.2
    # warm-start：完整加载 minej 权重（含分类头），不做任何 reinit。
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL_ID, config=config)
    print("warm-start：已加载 minej-bert-personality 全部权重（含分类头，标签顺序 E,N,A,C,O 对齐）")
    return model


def _export_final_model(model, tokenizer, dest: str) -> str:
    staging = dest + ".staging"
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    state = _remap_layernorm_keys(model.state_dict())
    model.save_pretrained(staging, state_dict=state)
    tokenizer.save_pretrained(staging)
    os.makedirs(dest, exist_ok=True)
    try:
        for name in os.listdir(staging):
            src = os.path.join(staging, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dest, name)
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copy2(src, dst)
        written = dest
    except OSError as exc:
        written = dest + "-new"
        if os.path.isdir(written):
            shutil.rmtree(written, ignore_errors=True)
        shutil.copytree(staging, written)
        print(f"无法覆盖 {dest}（{exc}），完整模型已写到 {written}")
    shutil.rmtree(staging, ignore_errors=True)
    return written


def make_args(output_dir: str, num_epochs: int, batch_size: int, accum: int, eval_steps: int, lr: float,
              warmup_steps: int, use_bf16: bool) -> TrainingArguments:
    return TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=accum,
        per_device_eval_batch_size=2,
        learning_rate=lr,
        warmup_steps=warmup_steps,
        weight_decay=0.01,
        fp16=(not use_bf16),
        bf16=use_bf16,
        eval_strategy="steps",
        eval_steps=eval_steps,
        logging_steps=50,
        save_strategy="steps",
        save_steps=eval_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_pearson",
        greater_is_better=True,
        seed=SEED,
        report_to=[],
        dataloader_num_workers=0,
        remove_unused_columns=False,
    )


def main():
    seed_everything(SEED)
    train_bags, val_bags, test_df, meta = load_and_prepare()

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, use_fast=False)
    train_dataset = BagDataset(train_bags, tokenizer)
    val_dataset = BagDataset(val_bags, tokenizer)

    train_labels_np = np.stack([b["labels"] for b in train_bags])
    trait_weights_np = inverse_std_weights(train_labels_np)
    trait_weights = torch.tensor(trait_weights_np, dtype=torch.float32)
    val_author_np = np.array([b["author_id"] for b in val_bags], dtype=np.int64)

    def compute_metrics(eval_pred):
        preds, labels = eval_pred
        if isinstance(preds, tuple):
            preds = preds[0]
        scores = np.clip(np.asarray(preds, dtype=np.float64), 0.0, 1.0)
        report = regression_report(scores, np.asarray(labels), val_author_np, TRAIT_ORDER)
        return {
            "mae": report["comment_mae_mean"],
            "pearson": report["comment_pearson_mean"],
            "author_mae": report["author_mae_mean"],
            "author_pearson": report["author_pearson_mean"],
        }

    cap = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
    use_bf16 = cap[0] >= 12
    print(f"GPU capability={cap}，使用 {'bf16' if use_bf16 else 'fp16'} 混合精度")

    model = _build_model()
    checkpointed = None

    def run_stage(stage_name, freeze_below, num_epochs, eval_steps):
        nonlocal model
        _freeze_backbone(model, freeze_below=freeze_below)
        args = make_args(
            output_dir=os.path.join(WORK_DIR, stage_name),
            num_epochs=num_epochs,
            batch_size=2,
            accum=2,
            eval_steps=eval_steps,
            lr=BACKBONE_LR,  # 占位；实际 lr 由 create_optimizer 分组控制
            warmup_steps=20,
            use_bf16=use_bf16,
        )
        trainer = TransferTrainer(
            model=model,
            args=args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            compute_metrics=compute_metrics,
            data_collator=collate_batch,
            callbacks=[EarlyStoppingCallback(early_stopping_patience=4)],
            trait_weights=trait_weights,
            head_lr=HEAD_LR,
            backbone_lr=BACKBONE_LR,
        )
        try:
            trainer.train()
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower():
                raise
            print("OOM；本阶段跳过（模型保持未更新）")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return None
        model = trainer.model
        return trainer

    # 阶段1：只训分类头（freeze 全部 encoder）
    print("\n===== 阶段1：只训分类头 =====")
    t1 = run_stage("stage1-head", freeze_below=12, num_epochs=3, eval_steps=10)

    # 阶段2：解冻后两层 + 分类头
    print("\n===== 阶段2：解冻后两层微调 =====")
    t2 = run_stage("stage2-backbone", freeze_below=FREEZE_BELOW_LAYER, num_epochs=6, eval_steps=20)

    final_trainer = t2 or t1
    if final_trainer is None:
        print("两阶段均失败，无可用模型")
        return 1

    saved_to = _export_final_model(model, tokenizer, OUT_DIR)
    best_metric = getattr(final_trainer.state, "best_metric", None)
    log = {
        "base_model": BASE_MODEL_ID,
        "trait_order": TRAIT_ORDER,
        "split": meta,
        "trait_weights": {t: float(w) for t, w in zip(TRAIT_ORDER, trait_weights_np)},
        "use_bf16": use_bf16,
        "hyperparameters": {
            "mode": "transfer_learn_warm_start",
            "head_lr": HEAD_LR,
            "backbone_lr": BACKBONE_LR,
            "max_length": MAX_LENGTH,
            "huber_delta": HUBER_DELTA,
            "freeze_below_layer": FREEZE_BELOW_LAYER,
            "bag_size": BAG_SIZE,
            "train_bags": TRAIN_BAGS,
        },
        "best_metric": best_metric,
        "best_model_checkpoint": getattr(final_trainer.state, "best_model_checkpoint", None),
        "saved_to": saved_to,
    }
    with open(os.path.join(saved_to, "training_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    print(f"\n迁移学习完成：{saved_to} best_pearson={best_metric}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)