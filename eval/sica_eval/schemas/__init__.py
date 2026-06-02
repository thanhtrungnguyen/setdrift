"""Experiment-level Pydantic schemas (manifest, F1 result).

Kept in its own package (not under telemetry/ or benchmark/) to avoid circular
imports with telemetry/scorer.py, which consumes these models.
"""
