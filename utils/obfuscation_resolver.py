"""Resolve effective APK obfuscation from runner_config."""

from dataclasses import dataclass
from typing import Literal, get_args

ObfuscationRequest = Literal["off", "on"]

_VALID_REQUESTS: tuple[str, ...] = get_args(ObfuscationRequest)


@dataclass(frozen=True)
class ObfuscationDecision:
    effective: Literal["off", "on"]
    log_level: Literal["info", "warning"]
    log_message: str


def resolve_obfuscation(requested: ObfuscationRequest) -> ObfuscationDecision:
    """Resolve the runner's obfuscation request."""
    if requested not in _VALID_REQUESTS:
        raise ValueError(
            f"Invalid requested obfuscation value: {requested!r}. "
            f"Expected one of {_VALID_REQUESTS}."
        )

    if requested == "off":
        return ObfuscationDecision(
            effective="off",
            log_level="info",
            log_message="Obfuscation off (default)",
        )

    # requested == "on"
    return ObfuscationDecision(
        effective="on",
        log_level="info",
        log_message="Obfuscation on",
    )
