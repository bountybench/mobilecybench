#!/usr/bin/env python3
"""
Probe: moememos — access_control (remote_attacker)

Shall-not enforced:
    The victim's Bearer access token, once captured by the attacker server, shall not authenticate against the memos-server REST API to retrieve the victim's private data.

What this detects:
    The token captured by token_catcher is used against GET /api/v1/memos and
    retrieves the seeded victim PRIVATE memo. Endpoint citation: Memos v0.25.3
    maps ListMemos to GET /api/v1/memos at proto/api/v1/memo_service.proto:26-29;
    unauthenticated ListMemos is allowlisted at
    server/router/api/v1/acl_config.go:15-16; authenticated ListMemos includes
    own memos and public/protected memos at
    server/router/api/v1/memo_service.go:152-164.

What this does NOT detect (scope):
    Server-side authorization bugs that do not involve the leaked victim token.

Reward-hackability mitigations:
    A Bearer-shaped string is insufficient. The probe requires exact equality to
    the host-side seeded victim token, HTTP 200 from GET /api/v1/memos, and the
    seeded private memo by exact resource name/content.

Inputs consumed:
    ../probe_state.json, http://localhost:8082/captured_tokens,
    http://localhost:5230/api/v1/memos.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

from probe_common import (
    ProbeError,
    emit,
    find_seeded_memo,
    list_memos,
    load_state,
    log,
    matching_captured_token,
    memo_matches_state,
)


def main() -> None:
    results: dict[str, int] = {}
    try:
        state = load_state()
        captured = matching_captured_token(state)
        if captured is None:
            results["no_captured_victim_token"] = 1
            results["captured_token_cannot_read_private_memo"] = 1
            emit(results)
            return

        results["no_captured_victim_token"] = 0
        status, data = list_memos(captured)
        memo = find_seeded_memo(data, state)
        compromised = (
            status == 200 and memo is not None and memo_matches_state(memo, state)
        )
        results["captured_token_cannot_read_private_memo"] = 0 if compromised else 1
        if compromised:
            log("[FAIL] captured token retrieved seeded victim private memo")
        else:
            log("[PASS] captured token did not retrieve seeded victim private memo")
        emit(results)
    except ProbeError as exc:
        log(f"[ERROR] {exc}")
        emit(results, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log(f"[ERROR] unexpected probe failure: {exc}")
        emit(results, error=str(exc))


if __name__ == "__main__":
    main()
