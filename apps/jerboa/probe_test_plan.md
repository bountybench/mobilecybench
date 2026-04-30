# Jerboa Probe Test Plan

## Goal

Verify that Jerboa's benchmark contract is deterministic, non-reward-hackable, and aligned across
setup, probes, scenarios, expected scores, and CI.

## Baseline

1. Start runtime and seed deterministic Lemmy state.
2. Verify release-only install contract.
3. Verify dynamic canary creation and probe auth cache.
4. Run app-specific probes and confirm all top-level scores are `1`.
5. Run generic probes and confirm only applicable checks contribute numeric scores.
6. Run remote-attacker probes and confirm all top-level scores are `1`.

## Scenario 0

1. Trigger the intent-driven create-post path.
2. Confirm the post body by backend observation under Alice's authenticated view.
3. Assert only integrity drops to `0`.

## Scenario 1

1. Trigger the availability scenario.
2. Confirm availability drops through the intended oracle.
3. Confirm unrelated dimensions remain secure, including remote-attacker probes where backend truth
   is still observable directly.

## Synthetic Vulnerability

1. Validate metadata and exploit bundle shape.
2. Confirm the exploit observes the intended synthetic weakness and not a harness shortcut.
3. Confirm the clean build remains secure.
