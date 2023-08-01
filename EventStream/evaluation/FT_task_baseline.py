"""Utilities for collecting baseline performance of fine-tuning tasks defined over ESGPT datasets."""

import copy
import json
from pathlib import Path

import polars as pl
import polars.selectors as cs

from ..data.dataset_polars import Dataset

pl.enable_string_cache(True)


def add_tasks_from(
    tasks_dir: Path, name_prefix: str = "", container: dict[str, pl.LazyFrame] | None = None
) -> dict[str, pl.LazyFrame]:
    """Collects all task dataframes (stored as parquet files) in a nested directory structure.

    Args:
        tasks_dir: The root directory for the tasks tree to be collected.
        name_prefix: What prefix should be prepended to task names when collecting tasks.
        container: Tasks will be added into this container. If `None` (the default), a new container will be
            created. This object **will** be modified.

    Returns:
        The updated (or newly created) container object mapping task names (as indexed by relative file paths)
        to polars lazy frame objects for those dataframes.

    Examples:
        >>> import tempfile, polars as pl
        >>> from datetime import datetime
        >>> from pathlib import Path
        >>> task_1_name = "task"
        >>> task_df_1 = pl.DataFrame({
        ...     'subject_id': [1, 1, 1, 2, 3],
        ...     'start_time': [datetime(2020, 1, 1), None, None, datetime(2020, 3, 2), None],
        ...     'end_time': [
        ...         datetime(2020, 1, 4), datetime(1980, 1, 2), datetime(1991, 2, 5),
        ...         datetime(2022, 1, 1), datetime(2022, 1, 1),
        ...     ],
        ...     'label': [1, 0, 0, 1, 0],
        ... })
        >>> task_2_name = "foobar/foo"
        >>> task_df_2 = pl.DataFrame({
        ...     'subject_id': [1, 2, 4, 2, 3],
        ...     'start_time': [None, None, None, None, None],
        ...     'end_time': [
        ...         datetime(2023, 1, 4), datetime(1984, 1, 2), datetime(1995, 3, 5),
        ...         datetime(2021, 1, 1), datetime(2012, 1, 1),
        ...     ],
        ...     'foo': [0, 5, 19, 2, 1],
        ... })
        >>> task_3_name = "foobar/bar"
        >>> task_df_3 = pl.DataFrame({
        ...     'subject_id': [1, 3, 3],
        ...     'start_time': [None, None, None],
        ...     'end_time': [datetime(2010, 1, 4), datetime(1985, 1, 2), datetime(1931, 2, 5)],
        ...     'bar': [3.12, 8.1, 1.0],
        ... })
        >>> tasks = {task_1_name: task_df_1, task_2_name: task_df_2, task_3_name: task_df_3}
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     base_path = Path(tmpdir)
        ...     for name, task_df in tasks.items():
        ...         task_fp = base_path / f"{name}.parquet"
        ...         task_fp.parent.mkdir(exist_ok=True, parents=True)
        ...         task_df.write_parquet(task_fp)
        ...     read_dfs = add_tasks_from(base_path)
        ...     read_dfs = {k: v.collect() for k, v in read_dfs.items()}
        >>> len(read_dfs)
        3
        >>> read_dfs["task"]
        shape: (5, 4)
        ┌────────────┬─────────────────────┬─────────────────────┬───────┐
        │ subject_id ┆ start_time          ┆ end_time            ┆ label │
        │ ---        ┆ ---                 ┆ ---                 ┆ ---   │
        │ i64        ┆ datetime[μs]        ┆ datetime[μs]        ┆ i64   │
        ╞════════════╪═════════════════════╪═════════════════════╪═══════╡
        │ 1          ┆ 2020-01-01 00:00:00 ┆ 2020-01-04 00:00:00 ┆ 1     │
        │ 1          ┆ null                ┆ 1980-01-02 00:00:00 ┆ 0     │
        │ 1          ┆ null                ┆ 1991-02-05 00:00:00 ┆ 0     │
        │ 2          ┆ 2020-03-02 00:00:00 ┆ 2022-01-01 00:00:00 ┆ 1     │
        │ 3          ┆ null                ┆ 2022-01-01 00:00:00 ┆ 0     │
        └────────────┴─────────────────────┴─────────────────────┴───────┘
        >>> read_dfs["foobar/foo"]
        shape: (5, 4)
        ┌────────────┬────────────┬─────────────────────┬─────┐
        │ subject_id ┆ start_time ┆ end_time            ┆ foo │
        │ ---        ┆ ---        ┆ ---                 ┆ --- │
        │ i64        ┆ f32        ┆ datetime[μs]        ┆ i64 │
        ╞════════════╪════════════╪═════════════════════╪═════╡
        │ 1          ┆ null       ┆ 2023-01-04 00:00:00 ┆ 0   │
        │ 2          ┆ null       ┆ 1984-01-02 00:00:00 ┆ 5   │
        │ 4          ┆ null       ┆ 1995-03-05 00:00:00 ┆ 19  │
        │ 2          ┆ null       ┆ 2021-01-01 00:00:00 ┆ 2   │
        │ 3          ┆ null       ┆ 2012-01-01 00:00:00 ┆ 1   │
        └────────────┴────────────┴─────────────────────┴─────┘
        >>> read_dfs["foobar/bar"]
        shape: (3, 4)
        ┌────────────┬────────────┬─────────────────────┬──────┐
        │ subject_id ┆ start_time ┆ end_time            ┆ bar  │
        │ ---        ┆ ---        ┆ ---                 ┆ ---  │
        │ i64        ┆ f32        ┆ datetime[μs]        ┆ f64  │
        ╞════════════╪════════════╪═════════════════════╪══════╡
        │ 1          ┆ null       ┆ 2010-01-04 00:00:00 ┆ 3.12 │
        │ 3          ┆ null       ┆ 1985-01-02 00:00:00 ┆ 8.1  │
        │ 3          ┆ null       ┆ 1931-02-05 00:00:00 ┆ 1.0  │
        └────────────┴────────────┴─────────────────────┴──────┘
    """

    if container is None:
        container = {}

    for sub_path in tasks_dir.iterdir():
        if sub_path.is_file() and sub_path.suffix == ".parquet":
            container[f"{name_prefix}{sub_path.stem}"] = pl.scan_parquet(sub_path)
        elif sub_path.is_dir():
            add_tasks_from(sub_path, f"{name_prefix}{sub_path.name}/", container)

    return container


KEY_COLS = ["subject_id", "start_time", "end_time"]


def summarize_binary_task(task_df: pl.LazyFrame):
    """Prints a summary dataframe describing binary tasks.

    Args:
        task_df: The task dataframe in question.

    Examples:
        >>> import polars as pl
        >>> from datetime import datetime
        >>> task_df = pl.DataFrame({
        ...     'subject_id': [1, 1, 1, 2, 3, 4, 4],
        ...     'start_time': [datetime(2020, 1, 1), None, None, datetime(2020, 3, 2), None, None, None],
        ...     'end_time': [
        ...         datetime(2020, 1, 4), datetime(1980, 1, 2), datetime(1991, 2, 5),
        ...         datetime(2022, 1, 1), datetime(2022, 1, 1), None, None,
        ...     ],
        ...     'label': [1, 0, 0, 1, 0, 0, 1],
        ... }).lazy()
        >>> pl.Config.set_tbl_width_chars(80)
        <class 'polars.config.Config'>
        >>> summarize_binary_task(task_df)
        shape: (1, 4)
        ┌───────────────────┬──────────────────────────┬────────────────────┬──────────┐
        │ n_samples_overall ┆ median_samples_per_subje ┆ label/subject Mean ┆ label    │
        │ ---               ┆ ct                       ┆ ---                ┆ ---      │
        │ u32               ┆ ---                      ┆ f64                ┆ f64      │
        │                   ┆ f64                      ┆                    ┆          │
        ╞═══════════════════╪══════════════════════════╪════════════════════╪══════════╡
        │ 7                 ┆ 1.5                      ┆ 0.458333           ┆ 0.428571 │
        └───────────────────┴──────────────────────────┴────────────────────┴──────────┘
    """
    label_cols = [c for c in task_df.columns if c not in KEY_COLS]
    print(
        task_df.groupby("subject_id")
        .agg(
            pl.count().alias("samples_per_subject"),
            *[pl.col(c).mean() for c in label_cols],
        )
        .select(
            pl.col("samples_per_subject").sum().alias("n_samples_overall"),
            pl.col("samples_per_subject").median().alias("median_samples_per_subject"),
            *[pl.col(c).mean().alias(f"{c}/subject Mean") for c in label_cols],
            *[
                (pl.col(c) * pl.col("samples_per_subject")).sum()
                / (pl.col("samples_per_subject").sum()).alias(f"{c} Mean")
                for c in label_cols
            ],
        )
        .collect()
    )


def load_flat_rep(
    ESD: Dataset,
    window_sizes: list[str],
    feature_inclusion_frequency: float | dict[str, float] | None = None,
    include_only_measurements: set[str] | None = None,
    do_update_if_missing: bool = True,
) -> pl.LazyFrame:
    flat_dir = ESD.config.save_dir / "flat_reps"

    feature_inclusion_frequency, include_only_measurements = ESD._resolve_flat_rep_cache_params(
        feature_inclusion_frequency, include_only_measurements
    )

    cache_kwargs = dict(
        feature_inclusion_frequency=feature_inclusion_frequency,
        window_sizes=window_sizes,
        include_only_measurements=include_only_measurements,
        do_overwrite=False,
        do_update=True,
    )

    params_fp = flat_dir / "params.json"
    if not params_fp.is_file():
        if not do_update_if_missing:
            raise FileNotFoundError("Flat representation files haven't been written!")
        else:
            ESD.cache_flat_representation(**cache_kwargs)

    with open(params_fp) as f:
        params = json.load(f)

    needs_more_measurements = not set(include_only_measurements).issubset(params["include_only_measurements"])
    needs_more_features = params["feature_inclusion_frequency"] is not None and (
        (feature_inclusion_frequency is None)
        or any(
            params["feature_inclusion_frequency"].get(m, float("inf")) > m_freq
            for m, m_freq in feature_inclusion_frequency.items()
        )
    )
    needs_more_windows = False
    for window_size in window_sizes:
        if not (flat_dir / "past" / "train" / window_size).is_dir():
            needs_more_windows = True

    if needs_more_measurements or needs_more_features or needs_more_windows:
        ESD.cache_flat_representation(**cache_kwargs)
        with open(params_fp) as f:
            params = json.load(f)

    allowed_features = []
    for meas, cfg in ESD.measurement_configs.items():
        if meas not in include_only_measurements:
            continue

        if cfg.vocabulary is None or feature_inclusion_frequency is None:
            allowed_features.append(meas)
            continue

        vocab = copy.deepcopy(cfg.vocabulary)
        vocab.filter(total_observations=None, min_valid_element_freq=feature_inclusion_frequency[meas])
        allowed_vocab = vocab.vocabulary
        for e in allowed_vocab:
            allowed_features.append(f"{meas}/{e}")

    by_split = {}
    for sp in ESD.split_subjects.keys():
        dfs = []
        for window_size in window_sizes:
            allowed_columns = cs.starts_with("static")
            for feat in allowed_features:
                allowed_columns = allowed_columns | cs.starts_with(f"{window_size}/{feat}")

            fp = flat_dir / "past" / sp / window_size / "*.parquet"
            dfs.append(pl.scan_parquet(fp).select("subject_id", "timestamp", allowed_columns))
        by_split[sp] = pl.concat(dfs, how="align")
    return by_split
