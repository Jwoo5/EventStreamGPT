from __future__ import annotations

import dataclasses, numpy as np, polars as pl

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Sequence, Tuple, Union

from ..utils import JSONableMixin

import plotly.express as px
from plotly.graph_objs._figure import Figure

@dataclasses.dataclass
class Visualizer(JSONableMixin):
    """
    This class helps visualize `EventStreamDataset` objects. It is both a configuraiton object and performs
    the actual data manipulations for final visualization, interfacing only with the `EventStreamDataset`
    object to obtain appropriately sampled and processed cuts of the data to visualize. It currently produces
    the following plots. All plots are broken down by `static_covariates`, which are covariates that are
    constant for each subject.

    ## Analyzing the data over time (only produced if `plot_by_time` is True)
    Given an $x$-axis of time $t$, the following plots are produced:
        - "Active Subjects": $y$ = the number of active subjects at time $x$ (i.e. the number of subjects who
          have at least one event before $t$ and have not yet had their last event at $t$).
        - "Cumulative Subjects": $y$ = the number of cumulative subjects at time $t$ (i.e., the number of
          subjects who have at least one event before $t$).
        - "Cumulative Events": $y$ = the number of events the dataset would obtain were it to be terminated
          at time $t$.
        - "Events / Subject": $y$ = the average number of events per subject as would be observed were the
          dataset to be terminated at time $t$.
        - "Events / (Subject, Time)": $y$ = the average rate of events per unit time per subject at time
          $t$
        - "Age Distribution over Time": A 2D Density Heatmap plot showing the distributions of the ages of
          active subjects in the dataset at time $t$. Only produced if `age_col` is specified. Age is binned
          into `n_age_buckets` buckets.

    ## Analyzing the data over age (only produced if `plot_by_age` is True)
    Given an $x$-axis of age bucket $a$, the following plots are produced:
        - "Cumulative Subjects": $y$ = the number of subjects in the dataset who have an event in the age
          bucket $a$.
        - "Cumulative Events": $y$ = the number of events included in the dataset that occur at an age up to
          or before $a$.
        - "Events / Subject": $y$ = the average number of events per subject that occur when the subject is at
          age bucket $a$.
    """

    subset_size: Optional[int] = None
    subset_random_seed: Optional[int] = None

    static_covariates: List[str] = dataclasses.field(default_factory=list)

    plot_by_time: bool = True
    time_unit: Optional[str] = '1y'

    plot_by_age: bool = False
    age_col: Optional[str] = None
    dob_col: Optional[str] = None
    n_age_buckets: Optional[int] = 200

    def to_dict(self) -> dict:
        """Represents this configuation object as a plain dictionary."""
        as_dict = dataclasses.asdict(self)
        dynamic_last_seen = []
        for e in self.split_subject_plots_by_dynamic_last_seen_covariates:
            if type(e) is tuple:
                if len(e) != 2: raise ValueError(f"Malformed covariate spec: {e}!")
                e = [e[0], {k: list(v) for k, v in e[1].items()}]
            elif type(e) is not str: raise ValueError(f"Malformed covariate spec: {e}!")
            dynamic_last_seen.append(e)
        as_dict['split_subject_plots_by_dynamic_last_seen_covariates'] = dynamic_last_seen
        return as_dict

    @classmethod
    def from_dict(cls, as_dict: dict) -> 'EventStreamPytorchDatasetConfig':
        """Creates a new instance of this class from a plain dictionary."""
        dynamic_last_seen = []
        for e in as_dict['split_subject_plots_by_dynamic_last_seen_covariates']:
            if type(e) is list:
                if len(e) != 2: raise ValueError(f"Malformed covariate spec: {e}!")
                e = (e[0], {k: set(v) for k, v in e[1].items()})
            elif type(e) is not str:
                raise ValueError(f"Malformed covariate spec: {e}!")
            dynamic_last_seen.append(e)
        as_dict['split_subject_plots_by_dynamic_last_seen_covariates'] = dynamic_last_seen
        return cls(**as_dict)

    def __post_init__(self):
        if self.subset_size is not None and self.subset_random_seed is None:
            raise ValueError("subset_size is specified, but subset_random_seed is not!")
        if self.plot_by_age:
            if self.age_col is None:
                raise ValueError("plot_by_age is True, but age_col is unspecified!")
            if self.n_age_buckets is None:
                raise ValueError("plot_by_age is True, but n_age_buckets is unspecified!")
        if self.age_col is not None and self.dob_col is None:
            raise ValueError("age_col is specified, but dob_col is not!")
        if self.plot_by_time and self.time_unit is None:
            raise ValueError("Can't plot by time if time_unit is unspecified!")

    def plot_counts_over_time(self, events_df: pl.DataFrame) -> List[Figure]:
        figures = []
        if not self.plot_by_time: return figures

        events_df = events_df.sort(
            'timestamp', descending=False
        ).with_columns(
            pl.when(
                (pl.col('timestamp') == pl.col('start_time')) & (pl.col('timestamp') == pl.col('end_time'))
            ).then(
                0
            ).when(
                pl.col('timestamp') == pl.col('start_time')
            ).then(
                1
            ).when(
                pl.col('timestamp') == pl.col('end_time')
            ).then(
                -1
            ).otherwise(
                0
            ).alias('active_subj_increment'),
            pl.when(
                pl.col('timestamp') == pl.col('start_time')
            ).then(
                1
            ).otherwise(
                0
            ).alias('cumulative_subj_increment'),
        ).groupby_dynamic(
            index_column='timestamp',
            every=self.time_unit,
            by=self.static_covariates,
        ).agg(
            pl.col('subject_id').n_unique().alias('n_subjects'),
            pl.col('event_id').n_unique().alias('n_events'),
            pl.col('active_subj_increment').sum().alias('active_subjects_delta'),
            pl.col('cumulative_subj_increment').sum().alias('cumulative_subjects_delta'),
        ).sort('timestamp', descending=False)

        for static_covariate in self.static_covariates:
            plt_kwargs = {'x': 'timestamp', 'color': static_covariate}

            events_df = events_df.groupby(
                'timestamp', static_covariate
            ).agg(
                pl.col('n_subjects').sum(),
                pl.col('n_events').sum(),
                pl.col('active_subjects_delta').sum(),
                pl.col('cumulative_subjects_delta').sum(),
            ).with_columns(
                (pl.col('n_events') / pl.col('n_subjects')).alias('events_per_subject_per_time'),
            ).sort('timestamp', descending=False)

            # "Active Subjects": $y$ = the number of active subjects at time $x$ (i.e. the number of subjects
            # who have at least one event before $t$ and have not yet had their last event at $t$).
            # "Cumulative Subjects": $y$ = the number of cumulative subjects at time $t$ (i.e., the number of
            # subjects who have at least one event before $t$).
            subjects_as_of_time = events_df.select(
                'timestamp', static_covariate,
                pl.col('active_subjects_delta').cumsum().over(static_covariate).alias('Active Subjects'),
                pl.col('cumulative_subjects_delta').cumsum().over(static_covariate).alias(
                    'Cumulative Subjects'
                ),
            ).to_pandas()
            figures.extend([
                px.line(subjects_as_of_time, y='Active Subjects', **plt_kwargs),
                px.line(subjects_as_of_time, y='Cumulative Subjects', **plt_kwargs),
            ])

            # "Cumulative Events": $y$ = the number of events the dataset would obtain were it to be
            # terminated at time $t$.
            # "Events / Subject": $y$ = the average number of events per subject as would be observed were the
            # dataset to be terminated at time $t$.
            # "Events / (Subject, Time)": $y$ = the average rate of events per unit time per subject at time
            # $t$

            events_as_of_time = events_df.select(
                'timestamp', static_covariate,
                pl.col('n_events').cumsum().over(static_covariate).alias('Cumulative Events'),
                (
                    pl.col('n_events').cumsum().over(static_covariate) /
                    pl.col('cumulative_subjects_delta').cumsum().over(static_covariate)
                ).alias('Average Events / Subject'),
                pl.col('events_per_subject_per_time').alias('New Events / Subject / time'),
            ).to_pandas()
            figures.extend([
                px.line(events_as_of_time, y='Cumulative Events', **plt_kwargs),
                px.line(events_as_of_time, y='Average Events / Subject', **plt_kwargs),
                px.line(events_as_of_time, y='New Events / Subject / time', **plt_kwargs),
            ])

        return figures

    def plot_age_distribution_over_time(
        self, subjects_df: pl.DataFrame, subj_ranges: pl.DataFrame
    ) -> List[Figure]:
        figures = []
        if not self.plot_by_time: return figures
        if self.dob_col is None: return figures

        start_time = subj_ranges['start_time'].min()
        end_time = subj_ranges['end_time'].max()

        subj_ranges = subj_ranges.join(
            subjects_df.select('subject_id', self.dob_col, *self.static_covariates), on='subject_id'
        ).drop('subject_id')

        time_points = pl.DataFrame({
            'timestamp': pl.date_range(start_time, end_time, interval=self.time_unit)
        })
        n_time_bins = len(time_points)+1

        cross_df = subj_ranges.join(
            time_points, how='cross'
        ).filter(
	    (pl.col('start_time') <= pl.col('timestamp')) & (pl.col('timestamp') <= pl.col('end_time'))
        ).select(
            'timestamp', *self.static_covariates,
            (pl.col('timestamp') - pl.col(self.dob_col)).alias(self.age_col),
        ).to_pandas()

        for static_covariate in self.static_covariates:
            figures.append(px.density_heatmap(
                cross_df, x='timestamp', y=self.age_col, facet_col=static_covariate, nbinsy=self.n_age_buckets,
                nbinsx=n_time_bins, marginal_y='histogram',
            ))

        return figures

    def plot_counts_over_age(self, events_df: pl.DataFrame) -> List[Figure]:
        figures = []
        if not self.plot_by_age: return figures

        min_age = events_df[self.age_col].min()
        max_age = events_df[self.age_col].max()

        age_buckets = list(np.linspace(min_age, max_age, self.n_age_buckets + 1))

        events_df = events_df.with_columns(
            pl.lit(age_buckets).search_sorted(pl.col(self.age_col)).alias('age_bucket_idx'),
        ).groupby(
            'age_bucket_idx', *self.static_covariates
        ).agg(
            pl.col(self.age_col).mean(),
            pl.col('event_id').n_unique().alias('n_events'),
            pl.col('subject_id').n_unique().alias('n_subjects'),
        ).sort(
            self.age_col, descending=False
        ).with_columns(
            pl.col('n_events').cumsum().over(*self.static_covariates).alias('Cumulative Events'),
        )

        for static_covariate in self.static_covariates:
            plt_kwargs = {'x': self.age_col, 'color': static_covariate}

            counts_at_age = events_df.groupby(
                self.age_col, static_covariate
            ).agg(
                pl.col('n_subjects').sum().alias('Subjects with Event @ Age'),
                pl.col('n_events').sum().alias('Events @ Age'),
                pl.col('Cumulative Events').sum().alias('Events <= Age'),
            ).with_columns(
                (
                    pl.col('Events @ Age') / pl.col('Subjects with Event @ Age')
                ).alias('Events / Subject @ Age | has event'),
            ).sort(
                self.age_col, descending=False
            ).to_pandas()

            figures.extend([
                px.line(counts_at_age, y='Subjects with Event @ Age', **plt_kwargs),
                px.line(counts_at_age, y='Events @ Age', **plt_kwargs),
                px.line(counts_at_age, y='Events <= Age', **plt_kwargs),
                px.line(counts_at_age, y='Events / Subject @ Age | has event', **plt_kwargs),
            ])

        return figures

    def plot(
        self, subjects_df: pl.DataFrame, events_df: pl.DataFrame, dynamic_measurements_df: pl.DataFrame
    ) -> List[Figure]:
        subj_ranges = events_df.groupby('subject_id').agg(
            pl.col('timestamp').min().alias('start_time'),
            pl.col('timestamp').max().alias('end_time')
        )

        min_time = subj_ranges['start_time'].min()
        max_time = subj_ranges['end_time'].max()

        static_variables = subj_ranges.join(
            subjects_df.select('subject_id', *self.static_covariates), on='subject_id'
        )

        events_df = events_df.join(static_variables, on='subject_id')

        figs = []
        figs.extend(self.plot_counts_over_time(events_df))
        figs.extend(self.plot_age_distribution_over_time(subjects_df, subj_ranges))
        figs.extend(self.plot_counts_over_age(events_df))

        return figs
