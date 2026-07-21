"""PrecisionGateReport schema — structural gate for precision/kappa reports (FIX-04).

What this module does: defines PrecisionGateReport (Pydantic, extra="forbid"),
matching corpus/precision_gate.py::check_gate + write_report's REAL output
field-for-field (per_source precision/kappa/n/label_distribution/passed_precision/
passed_kappa, negatives_fraction, n_total, passed_negatives, passed, thresholds,
provenance). Range validators enforce precision/negatives_fraction in [0, 1] and
kappa in [-1, 1] (Cohen's kappa's real bound).

What it does NOT do: it never loosens field names or ranges to accommodate a
badly-shaped report — extra="forbid" + required fields are the whole point
(T-06-07). A hand-typed synthetic report (overall_precision, n_verified/n_correct,
negative_fraction, notes) is REJECTED by construction, not by a special-cased
check.

Requirements: FIX-04 (schema-validate precision-gate reports).
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceMetrics(BaseModel):
    """Per-source precision/kappa/n/label_distribution + pass flags.

    Mirrors corpus/precision_gate.py::compute_precision_and_kappa +
    check_gate's per-source dict shape exactly.
    """

    model_config = ConfigDict(extra="forbid")

    precision: float = Field(description="Strict-set positive precision for this source, in [0, 1]")
    kappa: float = Field(description="Cohen's kappa for this source, in [-1, 1]")
    n: int = Field(description="Number of verified rows for this source")
    label_distribution: dict[str, int] = Field(
        description="Count of verified labels by taxonomy value for this source"
    )
    passed_precision: bool = Field(description="Whether precision >= precision_threshold")
    passed_kappa: bool = Field(description="Whether kappa >= kappa_threshold")

    @field_validator("precision")
    @classmethod
    def precision_in_unit_interval(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"precision must be in [0, 1], got {v}")
        return v

    @field_validator("kappa")
    @classmethod
    def kappa_in_bounds(cls, v: float) -> float:
        if not (-1.0 <= v <= 1.0):
            raise ValueError(f"kappa must be in [-1, 1], got {v}")
        return v

    @field_validator("n")
    @classmethod
    def n_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"n must be non-negative, got {v}")
        return v


class GateThresholds(BaseModel):
    """Thresholds applied by check_gate — mirrors its final report['thresholds']."""

    model_config = ConfigDict(extra="forbid")

    precision: float = Field(description="Per-source precision threshold used by this gate run")
    kappa: float = Field(description="Per-source kappa threshold used by this gate run")
    min_negatives_fraction: float = Field(
        description="Batch-wide minimum fraction of verified-negative rows required"
    )


class GateProvenance(BaseModel):
    """Provenance block stamped by write_report (D6-06): proves the report traces to a real
    verification CSV, without embedding any raw verification content (data wall intact)."""

    model_config = ConfigDict(extra="forbid")

    verify_csv_sha256: str = Field(description="sha256 hex digest of the verification CSV bytes")
    row_count: int = Field(description="Number of data rows read from the verification CSV")
    gate_run_date: str = Field(description="ISO-8601 UTC timestamp when the gate was run")

    @field_validator("row_count")
    @classmethod
    def row_count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"row_count must be non-negative, got {v}")
        return v


class PrecisionGateReport(BaseModel):
    """Structural schema for a precision-gate report (T-06-07 mitigation).

    extra="forbid" + required fields reject any shape mismatch, including the
    fabricated experiments/001-mining-precision.json (wrong field names:
    overall_precision, n_verified/n_correct, negative_fraction, plus a notes
    field admitting fakery — none of which are valid fields here).
    """

    model_config = ConfigDict(extra="forbid")

    per_source: dict[str, SourceMetrics] = Field(
        description="Per-source precision/kappa/n/label_distribution + pass flags"
    )
    negatives_fraction: float = Field(
        description="Batch-wide fraction of verified rows labeled negative (none), in [0, 1]"
    )
    n_total: int = Field(description="Total number of verified rows across all sources")
    passed_negatives: bool = Field(description="Whether negatives_fraction >= min_negatives_fraction")
    passed: bool = Field(description="Overall gate result: all per-source checks AND passed_negatives")
    thresholds: GateThresholds = Field(description="Thresholds applied by this gate run")
    provenance: GateProvenance = Field(
        description="Provenance stamp (verify-CSV sha256, row count, gate-run date) (D6-06)"
    )

    @field_validator("negatives_fraction")
    @classmethod
    def negatives_fraction_in_unit_interval(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"negatives_fraction must be in [0, 1], got {v}")
        return v

    @field_validator("n_total")
    @classmethod
    def n_total_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"n_total must be non-negative, got {v}")
        return v
