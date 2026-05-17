"""Resolve the effective APK obfuscation state from runner_config + metadata.

This is the implementation of the resolution table specified in
``documentation/APK_OBFUSCATION.md`` (see the "Per-app metadata schema" and
"Resolution table" sections). The helper combines the operator-supplied
``runner_config.apk_obfuscation`` value with the per-app
``metadata.apk_obfuscation`` value and returns both the effective state and a
log message that explains how it was reached.

Every override case (operator request and metadata disagree) is emitted at
``info`` or ``warning`` level so that silent overrides cannot occur — silent
overrides are a measurement bug per the design doc.
"""

from dataclasses import dataclass
from typing import Literal, get_args

ObfuscationRequest = Literal["off", "on"]
ObfuscationMetadata = Literal["never", "default", "force_on", "upstream_forced", None]

_VALID_REQUESTS: tuple[str, ...] = get_args(ObfuscationRequest)
_VALID_METADATA: tuple[str, ...] = ("never", "default", "force_on", "upstream_forced")


@dataclass(frozen=True)
class ObfuscationDecision:
    """The resolved effective obfuscation state and the reason for it.

    ``log_message`` is suitable for direct emission at ``log_level`` (no
    further formatting is required by the caller).
    """

    effective: Literal["off", "on"]
    log_level: Literal["debug", "info", "warning"]
    log_message: str


def resolve_obfuscation(
    requested: ObfuscationRequest,
    metadata_value: ObfuscationMetadata,
) -> ObfuscationDecision:
    """Resolve the effective obfuscation state and the explaining log message.

    See ``documentation/APK_OBFUSCATION.md`` "Resolution table" for the full
    mapping. ``metadata_value`` of ``None`` is treated identically to
    ``"never"`` per the design doc ("absent or 'never'").

    Every override case (where the operator request and metadata disagree)
    produces a non-empty ``log_message`` at ``warning`` or ``info`` level.
    """
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
        if meta in ("never", "default"):
            if meta == "never":
                return ObfuscationDecision(
                    effective="off",
                    log_level="debug",
                    log_message="Obfuscation off (default)",
                )
            return ObfuscationDecision(
                effective="off",
                log_level="debug",
                log_message=(
                    "Obfuscation off (app supports it but operator chose off)"
                ),
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
