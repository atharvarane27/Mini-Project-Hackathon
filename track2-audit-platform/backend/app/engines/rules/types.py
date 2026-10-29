"""Value types exposed by the custom audit rule language."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias


RuleNumber: TypeAlias = int | Decimal
RuleScalar: TypeAlias = RuleNumber | bool


class RuleValueType(StrEnum):
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    value_type: RuleValueType

    def __post_init__(self) -> None:
        if (
            not self.name
            or not ("A" <= self.name[0] <= "Z" or "a" <= self.name[0] <= "z" or self.name[0] == "_")
            or any(
                not (
                    "A" <= character <= "Z"
                    or "a" <= character <= "z"
                    or "0" <= character <= "9"
                    or character == "_"
                )
                for character in self.name[1:]
            )
        ):
            raise ValueError("field name must be a non-empty identifier")


_DEFAULT_FIELDS = {
    "Variance_Threshold": RuleValueType.NUMBER,
    "Allowed_Variance_Minor": RuleValueType.NUMBER,
    "Balance_Anomaly_Flag": RuleValueType.BOOLEAN,
    "Transaction_Velocity": RuleValueType.NUMBER,
    "Reconciliation_Variance_Minor": RuleValueType.NUMBER,
    "Circular_Flow_Detected": RuleValueType.BOOLEAN,
    "Cycle_Length": RuleValueType.NUMBER,
    "Cycle_Duration_Minutes": RuleValueType.NUMBER,
    "Splitting_Window_Sum_Minor": RuleValueType.NUMBER,
    "Splitting_Window_Count": RuleValueType.NUMBER,
    "Duplicate_Candidate_Flag": RuleValueType.BOOLEAN,
    "Severity": RuleValueType.NUMBER,
}

DEFAULT_FIELD_TYPES: Mapping[str, RuleValueType] = MappingProxyType(_DEFAULT_FIELDS)


def literal_type(value: RuleScalar) -> RuleValueType:
    """Return a rule type without treating bool as an integer."""

    if isinstance(value, bool):
        return RuleValueType.BOOLEAN
    return RuleValueType.NUMBER
