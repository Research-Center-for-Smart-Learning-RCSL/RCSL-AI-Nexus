"""Stable evaluation facade."""

from .entities import (
    DISCRIMINATION_THRESHOLD,
    EvaluationModelScore,
    EvaluationReport,
    EvaluationRun,
    EvaluationSample,
    EvaluationTaskScore,
    TaskVerdict,
)
from .scoring import aggregate

__all__ = [
    "DISCRIMINATION_THRESHOLD",
    "EvaluationModelScore",
    "EvaluationReport",
    "EvaluationRun",
    "EvaluationSample",
    "EvaluationTaskScore",
    "TaskVerdict",
    "aggregate",
]
