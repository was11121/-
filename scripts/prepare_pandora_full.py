"""下载 PANDORA 全量（HuggingFace `jingjietan/pandora-big5`）并按作者重切。

官方的 train/val/test 是**按评论行随机切**的，作者级有严重泄漏（test 里
1481 个作者有 1455 个也出现在 train），不能直接用。本脚本：

1. 下载 4 个 parquet shard（train×2 / validation / test）到 data/psych_eval/hf_full/。
2. 把单字母标签列 O/C/E/A/N 映射到大五全名，重排到 scoring.TRAIT_ORDER 顺序。
3. 用五维分数元组当 author_id（PANDORA 无真实 author 列），按作者重切 70/15/15。
4. 写 train/val/test 到 data/psych_eval/splits/，并锁死测试集作者集合。
5. 输出 split_meta.json（作者数、每作者条数、评论长度分位数、ptype 分层统计等）。

与旧训练的数据差异：标签 scale=100（旧本地切片是 99），且标签是连续 0.1 精度。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from personality_runtime.pandora_prep import (  # noqa: E402
    LABEL_SCALE,
    MAX_COMMENTS_PER_AUTHOR,
    prepare_pandora_frame,
    rename_hf_columns,
    split_by_author,
)
from personality_runtime.scoring import TRAIT_ORDER  # noqa: E402

HF_REPO = "jingjietan/pandora-big5"
HF_FILES = [
    "data/train-00000-of-00002.parquet",
    "data/train-00001-of-00002.parquet",
    "data/validation-00000-of-00001.parquet",
    "data/test-00000-of-00001.parquet",
]
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "data", "psych_eval", "hf_full")
SPLIT_DIR = os.path.join(PROJECT_ROOT, "data", "psych_eval", "splits")
SPLIT_META_PATH = os.path.join(SPLIT_DIR, "split_meta_full.json")
AUTHOR_LOCK_PATH = os.path.join(SPLIT_DIR, "test_authors_lock.json")

# 切分：70/15/15，测试集约 228 作者 → 作者级 r 的标准误降到 ~0.03。
TEST_SIZE = 0.15
VAL_SIZE = 0.15


def _local_path(fname: str) -> str:
    # hf_hub_download 用 local_dir=DOWNLOAD_DIR 会保留仓库内相对结构（data/ 前缀）。
    return os.path.join(DOWNLOAD_DIR, fname.replace("/", os.sep))


def download_all(force: bool = False) -> list[str]:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    from huggingface_hub import hf_hub_download

    paths = []
    for fname in HF_FILES:
        local_path = _local_path(fname)
        if os.path.isfile(local_path) and not force:
            print(f"已存在：{local_path}")
            paths.append(local_path)
            continue
        print(f"下载 {fname} …")
        hf_hub_download(
            repo_id=HF_REPO,
            filename=fname,
            repo_type="dataset",
            local_dir=DOWNLOAD_DIR,
            local_dir_use_symlinks=False,
        )
        print(f"  → {local_path}")
        paths.append(local_path)
    return paths


def load_all(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        df = pd.read_parquet(p, columns=["O", "C", "E", "A", "N", "ptype", "text"])
        frames.append(df)
        print(f"  读入 {os.path.basename(p)}: {len(df)} 行")
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--min-comments", type=int, default=8, help="少于该评论数的作者剔除")
    parser.add_argument("--max-comments", type=int, default=MAX_COMMENTS_PER_AUTHOR)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    paths = download_all(force=args.force_download)
    print("下载/加载完成，开始合并与清洗…")
    raw = load_all(paths)
    print(f"合并后总量：{len(raw)} 行")

    # 列名映射 + 重排到 TRAIT_ORDER
    raw = rename_hf_columns(raw)
    print(f"列映射后：{list(raw.columns)}")

    # 记录原始评论长度分位数（供选 max_length 参考）
    text_len = raw["text"].astype(str).str.len()
    for q in [50, 90, 95, 99]:
        print(f"  评论长度 p{q} = {float(text_len.quantile(q / 100)):.0f} 字符")

    prepared, prep_stats = prepare_pandora_frame(
        raw,
        max_comments_per_author=args.max_comments,
        min_comments_per_author=args.min_comments,
        label_scale=100.0,
        seed=args.seed,
    )
    print(f"清洗统计：{json.dumps(prep_stats, ensure_ascii=False)}")

    # 按作者分层切分（用 ptype 分层，失败则退化为纯 GroupShuffleSplit）
    train, val, test, split_meta = split_by_author(
        prepared, seed=args.seed, test_size=TEST_SIZE, val_size=VAL_SIZE, stratify_col="ptype"
    )

    # 校验作者不交叉
    overlap = (
        split_meta["author_overlap_train_val"]
        + split_meta["author_overlap_train_test"]
        + split_meta["author_overlap_val_test"]
    )
    print(f"切分：train {split_meta['n_train']}/{split_meta['n_train_authors']}a | "
          f"val {split_meta['n_val']}/{split_meta['n_val_authors']}a | "
          f"test {split_meta['n_test']}/{split_meta['n_test_authors']}a | 作者重叠={overlap}")
    if overlap > 0:
        raise RuntimeError(f"作者级泄漏：{split_meta}")

    os.makedirs(SPLIT_DIR, exist_ok=True)
    train.to_parquet(os.path.join(SPLIT_DIR, "pandora_full_train.parquet"), index=False)
    val.to_parquet(os.path.join(SPLIT_DIR, "pandora_full_val.parquet"), index=False)
    test.to_parquet(os.path.join(SPLIT_DIR, "pandora_full_test.parquet"), index=False)

    # 记录各维度标签 std（供 Huber delta 和 trait_weights sanity check）
    label_std = prepared[TRAIT_ORDER].std().to_dict()
    label_mean = prepared[TRAIT_ORDER].mean().to_dict()

    # 锁死测试集作者集合（防以后重切漂移）
    test_authors = sorted(test["author_id"].unique().astype(int).tolist())
    with open(AUTHOR_LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": args.seed,
                "n_test_authors": len(test_authors),
                "test_author_ids": test_authors,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    meta = {
        "source": HF_REPO,
        "hf_files": HF_FILES,
        "label_scale": 100.0,
        "trait_order": TRAIT_ORDER,
        "prep": prep_stats,
        **split_meta,
        "label_std": {k: float(v) for k, v in label_std.items()},
        "label_mean": {k: float(v) for k, v in label_mean.items()},
        "test_authors_lock": AUTHOR_LOCK_PATH,
    }
    with open(SPLIT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"\n标签 std：{ {k: round(v, 4) for k, v in label_std.items()} }")
    print(f"标签 mean：{ {k: round(v, 4) for k, v in label_mean.items()} }")
    print(f"\n完成。split_meta → {SPLIT_META_PATH}")
    print(f"测试集锁：{test_authors[0]}…{test_authors[-1]}（{len(test_authors)} 作者）")
    return 0


if __name__ == "__main__":
    sys.exit(main())