"""時系列 split: 直近 ``valid_days`` 日を valid に、それ以前を train に。

ML パイプラインのデータリークを構造的に防ぐため、ランダム split は使わない。
"""
from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def time_split(
    df: pd.DataFrame,
    *,
    valid_days: int = 7,
    date_col: str = "date_dt",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """train / valid に時系列 split する。

    valid_days = 7 なら、最大日付 d_max を含めて [d_max-6 .. d_max] が valid。
    train は date_dt < (d_max - 6) の行。
    """
    if df.empty or date_col not in df.columns:
        return df.copy(), df.iloc[0:0].copy()

    dates = pd.to_datetime(df[date_col], errors="coerce")
    valid_max = dates.max()
    if pd.isna(valid_max):
        return df.copy(), df.iloc[0:0].copy()
    valid_min = valid_max - timedelta(days=valid_days - 1)

    valid_mask = dates >= valid_min
    train_mask = dates < valid_min

    train = df.loc[train_mask].copy()
    valid = df.loc[valid_mask].copy()

    logger.info(
        "time_split: train=%d (date<%s), valid=%d (date>=%s, max=%s)",
        len(train), valid_min.date(), len(valid), valid_min.date(), valid_max.date(),
    )
    return train, valid
