"""Resolve effective APK obfuscation from runner_config + per-app metadata."""

from dataclasses import dataclass
from typing import Literal, get_args

ObfuscationRequest = Literal["off", "on"]
ObfuscationMetadata = Literal["never", "default", "force_on", "upstream_forced", None]

_VALID_REQUESTS: tuple[str, ...] = get_args(ObfuscationRequest)
_VALID_METADATA: tuple[str, ...] = tuple(
    v for v in get_args(ObfuscationMetadata) if v is not None
)


@dataclass(frozen=True)
class ObfuscationDecision:
    effective: Literal["off", "on"]
    log_level: Literal["info", "warning"]
    log_message: str


def resolve_obfuscation(
    requested: ObfuscationRequest,
    metadata_value: ObfuscationMetadata,
) -> ObfuscationDecision:
    """``metadata_value=None`` is normalized to ``"never"``."""
    if requested not in _VALID_REQUESTS:
        raise ValueError(
            f"Invalid requested obfuscation value: {requested!r}. "
            f"Expected one of {_VALID_REQUESTS}."
        )
    if metadata_value is not None and metadata_value not in _VALID_METADATA:
        raise ValueError(
            f"Invalid metadata_value: {metadata_value!r}. "
            f"Expected one of {_VALID_METADATA} or None."
        )

    # Normalize: absent metadata == "never" per design doc.
    meta = "never" if metadata_value is None else metadata_value

    if requested == "off":
        if meta == "never":
            return ObfuscationDecision(
                effective="off",
                log_level="info",
                log_message="Obfuscation off (default)",
            )
        if meta == "default":
            return ObfuscationDecision(
                effective="off",
                log_level="info",
                log_message="Obfuscation off (app supports it but operator chose off)",
            )
        if meta == "force_on":
            return ObfuscationDecision(
                effective="on",
                log_level="warning",
                log_message=(
                    "Operator requested obfuscation off, but app metadata "
                    "sets force_on — honoring force_on"
                ),
            )
        # meta == "upstream_forced"
        return ObfuscationDecision(
            effective="on",
            log_level="info",
            log_message=(
                "Operator requested obfuscation off, but app's upstream "
                "forces minify on — cannot disable"
            ),
        )

    # requested == "on"
    if meta == "never":
        return ObfuscationDecision(
            effective="off",
            log_level="warning",
            log_message=(
                "Operator requested obfuscation on, but app does not support "
                "it (metadata: never) — falling back to default APK"
            ),
        )
    if meta == "default":
        return ObfuscationDecision(
            effective="on",
            log_level="info",
            log_message="Obfuscation on",
        )
    if meta == "force_on":
        return ObfuscationDecision(
            effective="on",
            log_level="info",
            log_message="Obfuscation on (matches force_on)",
        )
    # meta == "upstream_forced"
    return ObfuscationDecision(
        effective="on",
        log_level="info",
        log_message="Obfuscation on (matches upstream_forced)",
    )
