"""Stable evaluation facade."""

from .entities import (
    DISCRIMINATION_THRESHOLD,
    EvaluationModelScore,
    EvaluationReport,
    EvaluationRun,
    EvaluationSample,
    EvaluationTaskDefinition,
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
    "EvaluationTaskDefinition",
    "EvaluationTaskScore",
    "TaskVerdict",
    "aggregate",
]
