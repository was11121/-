"""在全量 PANDORA（~1500+ 作者）上做迁移学习微调大五回归模型。

相比 `train_personality_transfer.py`（99 作者子集）的本质提升：
1. 数据：`prepare_pandora_full.py` 产出的按作者重切 / 70-15-15 / 1500+ 作者。
2. 动态 bag：每个 epoch 从该作者的全部评论里**重新随机抽**一个 bag，
   而非一次切好固定 bag —— 等效数据增强，作者级更稳定（P0）。
3. 分组 AdamW + **warmup + cosine** 调度（P0）：Stage 2 解冻时会重新 warmup。
4. 明确 Stage 1→2 切换条件（P0）：Stage 1 val 平均 r（Fisher-z）连续
   `STAGE_PATIENCE` 个 epoch 不提升就进入 Stage 2，而不是无脑等跑满。
5. 梯度裁剪 max_grad_norm=1.0（P0）。
6. 冒烟区分度**量化闸门**（P0）：反差句子预测差 |Δ|<0.05 立即中止。
7. 分维度监控（P1）：早停看 Fisher-z 平均 r，同时每维 r 都记进 log。
8. 双基线（P1）：(a) 训练集各维均值常量预测；(b) 平均 embedding 线性探针。
   最终模型打不赢基线 (a) 时明确标记失败。
9. best-checkpoint 规则写死（P1）：按 val 作者级 Fisher-z 平均 r 存最优，
   评测只跑最优，不跑 last。
10. 多 seed + bootstrap 置信区间（P1）：作者级指标在作者块上 bootstrap 重采样。

用法：
    python scripts/prepare_pandora_full.py          # 先准备数据（按作者重切）
    python scripts/train_pandora_full.py --seeds 42,7,123
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_cosine_schedule_with_warmup,
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from personality_runtime.pandora_prep import split_by_author  # noqa: E402
from personality_runtime.scoring import (  # noqa: E402
    TRAIT_ORDER,
    fisher_z_mean,
    inverse_std_weights,
    pearson_r,
    regression_report,
    sigmoid_np,
)

DATA_DIR = os.path.join(PROJECT_ROOT, "data", "psych_eval", "splits")
TRAIN_SPLIT = os.path.join(DATA_DIR, "pandora_full_train.parquet")
VAL_SPLIT = os.path.join(DATA_DIR, "pandora_full_val.parquet")
TEST_SPLIT = os.path.join(DATA_DIR, "pandora_full_test.parquet")
SPLIT_META = os.path.join(DATA_DIR, "split_meta_full.json")

BASE_MODEL_ID = os.path.join(PROJECT_ROOT, "models", "minej-bert-personality")
OUT_DIR = os.path.join(PROJECT_ROOT, "models", "psych-personality-bert-full")
WORK_DIR = os.path.join(PROJECT_ROOT, "models", "psych-personality-bert-full-work")

APOS = "extraversion", "neuroticism", "agreeableness", "conscientiousness", "openness"

# ---- 超参 ----
# 英文 BERT 约 4 字符/token：256 token ≈ 1024 字符，覆盖 p95(802)~p99(1810) 之间。
# 必须与线上推理 `bert_encoder.score()` 的 max_length=256 保持一致（训练=推理对齐）。
MAX_LENGTH = 256
HUBER_DELTA = 0.1
BAG_SIZE = 16
HEAD_LR = 5e-4
BACKBONE_LR = 2e-5
WEIGHT_DECAY = 0.01
CLASSIFIER_DROPOUT = 0.2
WARMUP_RATIO = 0.1
MAX_GRAD_NORM = 1.0
STAGE_PATIENCE = 2  # Stage 1 val 平均 r 连续 N epoch 不提升 → 进 Stage 2
EARLY_STOP_PATIENCE = 4  # 每阶段内部早停
SMOKE_DELTA_THRESHOLD = 0.05  # 反差句子预测差低于此 → 判定退化，中止

# 冒烟反差句子（用于检测模型是否又退化为常量预测）
SMOKE_PAIRS = [
    (
        "I cannot wait to go to the big party and meet everyone there, it is going to be so much fun.",
        "I would rather stay home alone tonight than go to a crowded party and make small talk.",
        "extraversion",
    ),
    (
        "I lie awake at night worrying about everything that could go wrong tomorrow.",
        "I feel calm and rarely worry about what might happen next.",
        "neuroticism",
    ),
    (
        "I made a detailed plan, finished the report early, and double-checked every detail.",
        "I keep putting things off and struggle to finish what I start.",
        "conscientiousness",
    ),
]


def seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


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


# --------------------------------------------------------------------------
# 动态 bag 数据集：每个 epoch 重新抽 bag
# --------------------------------------------------------------------------
class AuthorBagDataset(Dataset):
    """每作者所有评论按 index 存好，`__getitem__` 时按 epoch 内随机重抽 bag。

    `reshuffle(seed)` 在每个 epoch 开始时调用，重新决定每个作者的 bag 成员。
    """

    def __init__(self, df: pd.DataFrame, tokenizer, bag_size: int = BAG_SIZE, max_length: int = MAX_LENGTH):
        self.tokenizer = tokenizer
        self.bag_size = bag_size
        self.max_length = max_length
        self.author_ids = []
        self.texts_by_author: list[list[str]] = []
        self.labels_by_author: list[np.ndarray] = []
        self._bags: list[tuple[list[str], int, np.ndarray]] = []

        for author_id, group in df.groupby("author_id", sort=True):
            self.author_ids.append(int(author_id))
            self.texts_by_author.append(group["text"].astype(str).tolist())
            self.labels_by_author.append(group[TRAIT_ORDER].iloc[0].to_numpy(dtype=np.float32))
        self.reshuffle(seed=0)

    def reshuffle(self, seed: int) -> None:
        rng = np.random.RandomState(seed)
        self._bags = []
        for texts, aid, labels in zip(self.texts_by_author, self.author_ids, self.labels_by_author):
            n = len(texts)
            if n <= self.bag_size:
                chosen = list(texts)
                if chosen:
                    # 采样回填到 bag_size（有放回），保证 batch 维度一致
                    chosen = chosen + [texts[i] for i in rng.randint(0, n, size=self.bag_size - n)]
            else:
                idx = rng.choice(n, size=self.bag_size, replace=False)
                chosen = [texts[int(i)] for i in idx]
            chosen = chosen[: self.bag_size]
            if not chosen:
                continue
            self._bags.append((chosen, int(aid), labels.astype(np.float32)))

    def __len__(self) -> int:
        return len(self._bags)

    def __getitem__(self, idx: int):
        texts, aid, labels = self._bags[idx]
        enc = self.tokenizer(
            texts,
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )
        return {
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
            "labels": torch.tensor(labels, dtype=torch.float32),
            "author_id": torch.tensor(aid, dtype=torch.long),
        }


def collate_batch(features):
    batch = len(features)
    length = int(features[0]["input_ids"].shape[1])
    bag = int(features[0]["input_ids"].shape[0])
    input_ids = torch.zeros(batch, bag, length, dtype=torch.long)
    attention_mask = torch.zeros(batch, bag, length, dtype=torch.long)
    for i, feat in enumerate(features):
        input_ids[i] = feat["input_ids"]
        attention_mask[i] = feat["attention_mask"]
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": torch.stack([f["labels"] for f in features]),
        "author_id": torch.stack([f["author_id"] for f in features]),
    }


def _freeze_backbone(model, freeze_below: int) -> None:
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
    print(f"  冻结 embeddings + layer < {freeze_below}；可训练参数 {n_train}/{n_all}")


def _build_model():
    config = AutoConfig.from_pretrained(BASE_MODEL_ID)
    config.num_labels = len(TRAIT_ORDER)
    config.problem_type = "regression"
    config.id2label = {i: name for i, name in enumerate(TRAIT_ORDER)}
    config.label2id = {name: i for i, name in enumerate(TRAIT_ORDER)}
    if hasattr(config, "classifier_dropout"):
        config.classifier_dropout = CLASSIFIER_DROPOUT
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL_ID, config=config)
    print("warm-start：已加载 minej-bert-personality 全部权重（含分类头，标签 E,N,A,C,O 对齐）")
    return model


# --------------------------------------------------------------------------
# 训练循环（手写，为了控制动态 bag + 分组 LR + 两阶段 + 切换条件）
# --------------------------------------------------------------------------
class Trainer:
    def __init__(self, model, trait_weights: torch.Tensor, device: torch.device, use_bf16: bool):
        self.model = model
        self.trait_weights = trait_weights.to(device)
        self.device = device
        self.use_bf16 = use_bf16

    def forward_bag(self, input_ids, attention_mask):
        batch, bag, length = input_ids.shape
        input_ids = input_ids.view(batch * bag, length)
        attention_mask = attention_mask.view(batch * bag, length)
        logits = self.model(input_ids=input_ids, attention_mask=attention_mask).logits
        scores = torch.sigmoid(logits).view(batch, bag, -1)
        valid = (attention_mask.view(batch, bag, length).sum(dim=-1) > 0).to(scores.dtype).unsqueeze(-1)
        preds = (scores * valid).sum(dim=1) / valid.sum(dim=1).clamp(min=1.0)
        return preds

    def huber(self, preds, labels):
        diff = preds - labels
        abs_diff = torch.abs(diff)
        huber = torch.where(
            abs_diff <= HUBER_DELTA,
            0.5 * diff ** 2,
            HUBER_DELTA * (abs_diff - 0.5 * HUBER_DELTA),
        )
        return (huber * self.trait_weights.view(1, -1)).mean()

    def evaluate(self, loader: DataLoader):
        self.model.eval()
        preds_all, labels_all, aids_all = [], [], []
        with torch.no_grad():
            for batch in loader:
                input_ids = batch["input_ids"].to(self.device)
                attention_mask = batch["attention_mask"].to(self.device)
                labels = batch["labels"].to(self.device)
                aids = batch["author_id"].numpy()
                preds = self.forward_bag(input_ids, attention_mask)
                preds_all.append(preds.detach().cpu().numpy())
                labels_all.append(labels.detach().cpu().numpy())
                aids_all.append(aids)
        preds = np.vstack(preds_all)
        labels = np.vstack(labels_all)
        aids = np.concatenate(aids_all)
        report = regression_report(preds, labels, aids, TRAIT_ORDER)
        # Fisher-z 平均 r（P1）
        zr = fisher_z_mean([report["author_pearson"][t] for t in TRAIT_ORDER])
        report["fisher_z_mean_r"] = float(zr)
        return report


def _build_baseline_mean(train_df: pd.DataFrame, test_df: pd.DataFrame, dataset) -> dict:
    """基线 (a)：永远预测训练集各维均值。返回测试集上的作者级指标。"""
    means = train_df[TRAIT_ORDER].mean().to_numpy(dtype=np.float64)
    n = len(test_df)
    preds = np.tile(means, (n, 1))
    labels = test_df[TRAIT_ORDER].to_numpy(dtype=np.float64)
    aids = test_df["author_id"].to_numpy()
    report = regression_report(preds, labels, aids, TRAIT_ORDER)
    report["kind"] = "mean_baseline"
    return report


def _build_baseline_linear_probe(train_df, test_df, model, tokenizer, device) -> dict:
    """基线 (b)：冻结 BERT，取平均 embedding（CLS）做线性探针回归。

    用分类头前一层（bert pooler）的输出作为特征，fit 一个 Ridge 线性回归。
    """
    from sklearn.linear_model import Ridge

    def embed(df, batch=32):
        feats = []
        for i in range(0, len(df), batch):
            texts = df["text"].astype(str).iloc[i : i + batch].tolist()
            enc = tokenizer(texts, truncation=True, padding=True, max_length=MAX_LENGTH, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.no_grad():
                out = model.bert(**enc)
                cls = out.pooler_output if hasattr(out, "pooler_output") and out.pooler_output is not None else out.last_hidden_state[:, 0]
            feats.append(cls.detach().cpu().numpy())
        return np.vstack(feats)

    X_train = embed(train_df)
    y_train = train_df[TRAIT_ORDER].to_numpy(dtype=np.float64)
    X_test = embed(test_df)
    y_test = test_df[TRAIT_ORDER].to_numpy(dtype=np.float64)
    aids = test_df["author_id"].to_numpy()

    preds = np.zeros_like(y_test)
    for i in range(len(TRAIT_ORDER)):
        clf = Ridge(alpha=1.0)
        clf.fit(X_train, y_train[:, i])
        preds[:, i] = clf.predict(X_test)
    preds = np.clip(preds, 0.0, 1.0)
    report = regression_report(preds, y_test, aids, TRAIT_ORDER)
    report["kind"] = "linear_probe"
    return report


def _smoke_check(model, tokenizer, device) -> tuple[bool, dict]:
    """量化冒烟闸门：反差句子的预测差是否 >= 阈值。

    返回 (是否全部通过, 每维 delta 明细)。训前只记录不作为中止条件（minej 单句
    方向本就弱，尤其 neuroticism），训后才作为硬闸门：主要用来检测「训练后是否
    退化成了均值预测」——若某维 delta 掉到阈值以下，说明该维被练没了。
    """
    model.eval()
    detail = {}
    with torch.no_grad():
        for pos, neg, trait in SMOKE_PAIRS:
            enc = tokenizer([pos, neg], truncation=True, padding=True, max_length=MAX_LENGTH, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = model(**enc).logits
            scores = torch.sigmoid(logits).detach().cpu().numpy()
            idx = TRAIT_ORDER.index(trait)
            delta = abs(float(scores[0, idx]) - float(scores[1, idx]))
            detail[trait] = {"delta": delta, "pos": float(scores[0, idx]), "neg": float(scores[1, idx])}
            mark = "✓" if delta >= SMOKE_DELTA_THRESHOLD else "✗"
            print(f"  {mark} 冒烟 {trait}: 差 {delta:.3f}（{scores[0, idx]:.3f} vs {scores[1, idx]:.3f}）")
    passed = all(detail[t]["delta"] >= SMOKE_DELTA_THRESHOLD for t in detail)
    return passed, detail


def _build_optimizer(model, total_steps: int, warmup_steps: int):
    head_params = [p for n, p in model.named_parameters() if p.requires_grad and n.startswith("classifier")]
    backbone_params = [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith("classifier")]
    groups = []
    if head_params:
        groups.append({"params": head_params, "lr": HEAD_LR, "weight_decay": 0.0})
    if backbone_params:
        groups.append({"params": backbone_params, "lr": BACKBONE_LR, "weight_decay": WEIGHT_DECAY})
    optimizer = torch.optim.AdamW(groups)
    scheduler = get_cosine_schedule_with_warmup(optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps)
    return optimizer, scheduler


def _val_loader(val_dataset: AuthorBagDataset) -> DataLoader:
    return DataLoader(val_dataset, batch_size=2, collate_fn=collate_batch, shuffle=False, num_workers=0)


def _train_stage(
    model,
    train_dataset: AuthorBagDataset,
    val_dataset: AuthorBagDataset,
    tokenizer,
    device,
    use_bf16,
    freeze_below: int,
    epochs: int,
    stage_name: str,
    seed: int,
    record: dict,
) -> tuple[float, dict]:
    """训练一个阶段，返回 (该阶段最佳 val Fisher-z r, 最佳模型 state_dict)。

    optimizer/scheduler 在阶段开始时构建一次，跨 epoch 持续；每 epoch 重抽 bag。
    当 val Fisher-z 连续 `STAGE_PATIENCE` 个 epoch 未创新高时提前停（这也是
    Stage 1 → Stage 2 的切换条件）。
    """
    _freeze_backbone(model, freeze_below=freeze_below)

    # 训练 batch 先行构建一次（每 epoch 重抽 bag 但每个作者的 bag 数恒定，DataLoader 长度不变）。
    train_loader_kwargs = dict(batch_size=2, collate_fn=collate_batch, shuffle=True, num_workers=0)
    train_loader = DataLoader(train_dataset, **train_loader_kwargs)
    steps_per_epoch = len(train_loader)
    total_steps = steps_per_epoch * epochs
    warmup_steps = max(1, int(total_steps * WARMUP_RATIO))
    optimizer, scheduler = _build_optimizer(model, total_steps, warmup_steps)
    print(f"  [{stage_name}] steps_per_epoch={steps_per_epoch} total_steps={total_steps} warmup={warmup_steps}")

    t = Trainer(model, trait_weights=torch.tensor(inverse_std_weights(np.vstack(
        [a for _, _, a in train_dataset._bags])), dtype=torch.float32), device=device, use_bf16=use_bf16)

    val_loader = _val_loader(val_dataset)

    log = []
    best_zr = -1.0
    best_state = None
    no_improve = 0

    for epoch in range(epochs):
        # 每 epoch 重抽 bag（P0 动态 bag）
        train_dataset.reshuffle(seed=seed * 1000 + epoch)
        train_loader = DataLoader(train_dataset, **train_loader_kwargs)

        model.train()
        running_loss = 0.0
        for batch in train_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            with torch.autocast(device_type="cuda", enabled=use_bf16 and torch.cuda.is_available(), dtype=torch.bfloat16):
                preds = t.forward_bag(input_ids, attention_mask)
                loss = t.huber(preds, labels)

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), MAX_GRAD_NORM)  # P0 梯度裁剪
            optimizer.step()
            scheduler.step()
            running_loss += float(loss.item())

        val_report = t.evaluate(val_loader)
        zr = val_report["fisher_z_mean_r"]
        print(f"  [{stage_name}] epoch {epoch} loss={running_loss/max(1, steps_per_epoch):.4f} "
              f"val_fisherZ_r={zr:+.4f} val_author_mae={val_report['author_mae_mean']:.4f} "
              f"per-trait r={ {k: round(v,3) for k,v in val_report['author_pearson'].items()} }")
        log.append({
            "epoch": epoch,
            "loss": running_loss / max(1, steps_per_epoch),
            "val_fisher_z_mean_r": zr,
            "val_author_mae": val_report["author_mae_mean"],
            "val_author_pearson": val_report["author_pearson"],
        })

        if zr > best_zr + 1e-6:
            best_zr = zr
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= STAGE_PATIENCE:
                print(f"  [{stage_name}] 连续 {STAGE_PATIENCE} epoch 未提升，提前结束 Stage")
                break

    # 载回最佳 state（不是 last）
    if best_state is not None:
        model.load_state_dict(best_state)

    record[stage_name] = {"best_fisher_z_r": float(best_zr), "epochs_ran": epoch + 1, "log": log}
    return float(best_zr), best_state


def _bootstrap_author_pearson(preds: np.ndarray, labels: np.ndarray, aids: np.ndarray, seed: int, n_boot: int = 400) -> dict:
    """P1：对作者块重采样 bootstrap，估计 Fisher-z 平均 r 的置信区间。"""
    from personality_runtime.scoring import author_means

    ap, al, unique = author_means(preds, labels, aids)
    rng = np.random.RandomState(seed)
    zrs = []
    n = len(unique)
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        sub_ap, sub_al = ap[idx], al[idx]
        rs = [pearson_r(sub_al[:, i], sub_ap[:, i]) for i in range(len(TRAIT_ORDER))]
        zrs.append(fisher_z_mean(rs))
    zrs = np.asarray(zrs)
    return {
        "mean": float(zrs.mean()),
        "lo": float(np.percentile(zrs, 2.5)),
        "hi": float(np.percentile(zrs, 97.5)),
        "n_boot": n_boot,
    }


def _fit_one_seed(seed: int, dfs: dict, out_dir: str) -> dict:
    seed_everything(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    cap = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
    use_bf16 = cap[0] >= 12
    print(f"\n{'=' * 60}\nseed={seed} device={device} bf16={use_bf16}\n{'=' * 60}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, use_fast=False)
    train_df, val_df, test_df = dfs["train"], dfs["val"], dfs["test"]

    train_dataset = AuthorBagDataset(train_df, tokenizer)
    val_dataset = AuthorBagDataset(val_df, tokenizer)

    model = _build_model()
    model.to(device)

    # ---- 基线 (a)：均值预测，训前先算 ----
    baseline_mean = _build_baseline_mean(train_df, test_df, None)
    print(f"基线 (a) 均值预测 作者级 r(fisherZ均值)="
          f"{fisher_z_mean([baseline_mean['author_pearson'][t] for t in TRAIT_ORDER]):+.4f} "
          f"MAE={baseline_mean['author_mae_mean']:.4f}")

    # ---- 线性探针基线 (b)（冻结 BERT，用当前 minej 表示）----
    _freeze_backbone(model, freeze_below=12)
    baseline_lp = _build_baseline_linear_probe(train_df, test_df, model, tokenizer, device)
    print(f"基线 (b) 线性探针 作者级 r(fisherZ均值)="
          f"{fisher_z_mean([baseline_lp['author_pearson'][t] for t in TRAIT_ORDER]):+.4f} "
          f"MAE={baseline_lp['author_mae_mean']:.4f}")

    record: dict = {"seed": seed, "baselines": {"mean": baseline_mean, "linear_probe": baseline_lp}}

    # ---- 训练前冒烟闸门：只记录，不作为中止条件（minej 单句方向本就弱）----
    pretrain_smoke_ok, pretrain_smoke = _smoke_check(model, tokenizer, device)
    record["smoke_pretrain"] = pretrain_smoke
    record["smoke_pretrain_ok"] = bool(pretrain_smoke_ok)
    print(f"训前冒烟：{'全部通过' if pretrain_smoke_ok else '部分维 delta<阈值（记录，不中止）'}")
    if not pretrain_smoke_ok:
        print("  → 说明：minej 单句方向本身弱；此基线仅作参考，训后必须回升。")

    # ---- Stage 1：只训分类头 ----
    stage1_zr, _ = _train_stage(
        model, train_dataset, val_dataset, tokenizer, device, use_bf16,
        freeze_below=12, epochs=6, stage_name="stage1-head", seed=seed, record=record,
    )

    # ---- Stage 2：解冻后两层（Stage 1 已按 no-improve 早停，这里无条件进入解冻精调）----
    stage2_zr, _ = _train_stage(
        model, train_dataset, val_dataset, tokenizer, device, use_bf16,
        freeze_below=10, epochs=8, stage_name="stage2-backbone", seed=seed, record=record,
    )

    # ---- 训后冒烟：硬闸门。若某维 delta 掉到阈值以下，说明该维被练没了（退化）----
    posttrain_smoke_ok, posttrain_smoke = _smoke_check(model, tokenizer, device)
    record["smoke_posttrain"] = posttrain_smoke
    record["smoke_posttrain_ok"] = bool(posttrain_smoke_ok)
    degraded_dims = [t for t in posttrain_smoke if posttrain_smoke[t]["delta"] < SMOKE_DELTA_THRESHOLD]
    if degraded_dims:
        record["degraded_dims"] = degraded_dims
        print(f"⚠ 训后冒烟：{degraded_dims} 维 delta < {SMOKE_DELTA_THRESHOLD}，已退化（不达标也不上线）")
    else:
        print("训后冒烟：全部维度仍有区分度 ✓")

    # ---- 测试集评测（只跑当前最优 model = 两阶段后的最终状态）----
    test_dataset = AuthorBagDataset(test_df, tokenizer)
    test_loader = _val_loader(test_dataset)
    t = Trainer(model, trait_weights=torch.tensor(inverse_std_weights(np.vstack(
        [a for _, _, a in train_dataset._bags])), dtype=torch.float32), device=device, use_bf16=use_bf16)
    test_report = t.evaluate(test_loader)
    test_report["fisher_z_mean_r"] = float(fisher_z_mean([test_report["author_pearson"][t_] for t_ in TRAIT_ORDER]))

    # bootstrap 置信区间（P1）：需要测试集逐作者预测，重新跑一遍拿到原始 preds
    preds_all, labels_all, aids_all = [], [], []
    model.eval()
    with torch.no_grad():
        for batch in test_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)
            aids = batch["author_id"].numpy()
            preds = t.forward_bag(input_ids, attention_mask)
            preds_all.append(preds.detach().cpu().numpy())
            labels_all.append(labels.detach().cpu().numpy())
            aids_all.append(aids)
    preds_test = np.vstack(preds_all)
    labels_test = np.vstack(labels_all)
    aids_test = np.concatenate(aids_all)
    test_report["bootstrap_ci"] = _bootstrap_author_pearson(preds_test, labels_test, aids_test, seed=seed)

    # 保存模型
    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir, state_dict=_remap_layernorm_keys(model.state_dict()))
    tokenizer.save_pretrained(out_dir)

    record["test_report"] = test_report
    record["final_model_dir"] = out_dir
    record["beat_mean_baseline"] = test_report["fisher_z_mean_r"] > fisher_z_mean(
        [baseline_mean["author_pearson"][t] for t in TRAIT_ORDER]
    )

    # 达标判定
    n_pass = sum(1 for t in TRAIT_ORDER if test_report["author_pearson"][t] >= 0.35)
    avg_mae = test_report["author_mae_mean"]
    record["pass"] = n_pass >= 3 and avg_mae < 0.12
    record["n_pass_r035"] = n_pass

    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=str, default="42", help="逗号分隔，例如 42,7,123")
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    for path in (TRAIN_SPLIT, VAL_SPLIT, TEST_SPLIT):
        if not os.path.isfile(path):
            print(f"缺少切分文件：{path}。先运行 scripts/prepare_pandora_full.py")
            return 1

    train_df = pd.read_parquet(TRAIN_SPLIT)
    val_df = pd.read_parquet(VAL_SPLIT)
    test_df = pd.read_parquet(TEST_SPLIT)
    print(f"数据：train {len(train_df)}/{train_df.author_id.nunique()}a | "
          f"val {len(val_df)}/{val_df.author_id.nunique()}a | "
          f"test {len(test_df)}/{test_df.author_id.nunique()}a")

    results = []
    for seed in seeds:
        out_dir = os.path.join(OUT_DIR, f"seed{seed}")
        rec = _fit_one_seed(seed, {"train": train_df, "val": val_df, "test": test_df}, out_dir)
        results.append(rec)
        print(json.dumps({k: rec[k] for k in ("seed", "test_report", "pass", "n_pass_r035", "beat_mean_baseline") if k in rec},
                         indent=2, ensure_ascii=False, default=lambda o: str(o)))

    summary = {
        "seeds": seeds,
        "results": results,
        "hyperparams": {
            "max_length": MAX_LENGTH,
            "huber_delta": HUBER_DELTA,
            "bag_size": BAG_SIZE,
            "head_lr": HEAD_LR,
            "backbone_lr": BACKBONE_LR,
            "weight_decay": WEIGHT_DECAY,
            "classifier_dropout": CLASSIFIER_DROPOUT,
            "warmup_ratio": WARMUP_RATIO,
            "max_grad_norm": MAX_GRAD_NORM,
            "stage_patience": STAGE_PATIENCE,
            "early_stop_patience": EARLY_STOP_PATIENCE,
        },
    }
    with open(os.path.join(OUT_DIR, "training_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=lambda o: str(o))
    print(f"\n结果已保存：{os.path.join(OUT_DIR, 'training_summary.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())