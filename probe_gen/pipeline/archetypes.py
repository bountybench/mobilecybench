"""Per-archetype defaults: trust boundaries, CWE distribution, invariant templates.

Used by Phase 1.0 (threat-model bootstrap) and Phase 1.3 (invariant derivation)
as the prior over what a generic app of this archetype's threat model looks
like. App-specific deviations are layered on top during onboarding.

Archetype assignments per ``probe_gen/DESIGN.md``:

    Messaging         conversations, deltachat-android, jerboa, jitsi-meet,
                      element-android, nextcloud-talk, simplelogin, thunderbird,
                      tindroid, miniflutt, moememos
    Sync/storage      davx5, owncloud-android, joplin, wallabag
    Media             jellyfin, audiobookshelf, funkwhale, linphone
    IoT/control       home-assistant-android, openhab, gotify, ntfy-android,
                      owntracks
    Productivity      ankidroid, moodle, grocy, wordpress
    Security/network  openvpn, termux

Pipeline lookups go through :func:`get_archetype` to keep tests + downstream
consumers loosely coupled to the literal mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ArchetypeName = Literal[
    "messaging",
    "sync_storage",
    "media",
    "iot_control",
    "productivity",
    "security_network",
]


@dataclass
class InvariantTemplate:
    """A generic shall-not pattern that an archetype should produce.

    Filled in per app during Phase 1.3 with the specific subjects (account,
    role, channel, asset). Pipeline uses these as a prompt scaffold so we
    don't reinvent generic invariants per app.
    """

    template_id: str  # e.g. "messaging.identity_no_impersonation"
    statement_template: str  # contains {placeholders}
    attacker_models: list[str]  # ["malicious_app", "remote_attacker"]
    cwe_classes: list[str]
    notes: str = ""


@dataclass
class ArchetypeProfile:
    name: ArchetypeName
    apps: list[str]
    default_trust_boundaries: list[str]
    cwe_focus: list[str]
    invariant_templates: list[InvariantTemplate] = field(default_factory=list)


# ----- Templates -----


_MESSAGING_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="messaging.identity_no_impersonation",
        statement_template=(
            "A user shall not be able to send a message that the recipient's "
            "client attributes to a different account."
        ),
        attacker_models=["remote_attacker", "malicious_app"],
        cwe_classes=["CWE-290", "CWE-285"],
        notes="Carbon-spoof / message-origin classes. See conversations vuln_0.",
    ),
    InvariantTemplate(
        template_id="messaging.privacy_no_dm_leak_to_blocked",
        statement_template=(
            "A blocked sender shall not be able to deliver a message that "
            "appears in the recipient's primary inbox."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-285"],
    ),
    InvariantTemplate(
        template_id="messaging.history_no_third_party_modification",
        statement_template=(
            "A non-author shall not be able to modify or delete a message "
            "originally sent by another account."
        ),
        attacker_models=["remote_attacker", "malicious_app"],
        cwe_classes=["CWE-862", "CWE-285"],
    ),
    InvariantTemplate(
        template_id="messaging.account_no_privilege_escalation",
        statement_template=(
            "An unprivileged account shall not be able to gain admin or "
            "moderator privileges through any client- or server-mediated path."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-269", "CWE-862"],
    ),
    InvariantTemplate(
        template_id="messaging.account_lifecycle_no_unauthorized_deletion",
        statement_template=(
            "A user shall not be able to delete or disable another user's account."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-862"],
    ),
]


_SYNC_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="sync.acl_no_cross_user_access",
        statement_template=(
            "A user shall not be able to read, write, or delete sync items "
            "belonging to another user without explicit shared-access grant."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-285", "CWE-639", "CWE-200"],
    ),
    InvariantTemplate(
        template_id="sync.encryption_no_plaintext_at_rest_when_e2e",
        statement_template=(
            "When end-to-end encryption is enabled, the server shall not be "
            "able to recover the plaintext content of synced items."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-200", "CWE-326"],
        notes="Out-of-scope when E2E disabled by user.",
    ),
    InvariantTemplate(
        template_id="sync.conflict_no_silent_data_loss",
        statement_template=(
            "A sync conflict shall not silently overwrite or discard the user's "
            "local data without a recoverable record."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-285"],
    ),
]


_MEDIA_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="media.acl_no_unauthorized_stream_access",
        statement_template=(
            "An unauthenticated or low-privileged user shall not be able to "
            "access media streams or items they have no grant for."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-285", "CWE-200"],
    ),
    InvariantTemplate(
        template_id="media.parser_no_remote_corruption",
        statement_template=(
            "A malformed media artifact (codec/container/metadata) shall not "
            "cause memory corruption, RCE, or arbitrary file write in the "
            "client."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-119", "CWE-787", "CWE-125"],
    ),
]


_IOT_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="iot.command_no_unauthorized_actuation",
        statement_template=(
            "A co-installed app or unauthorized network actor shall not be "
            "able to invoke control actions on the user's devices."
        ),
        attacker_models=["malicious_app", "remote_attacker"],
        cwe_classes=["CWE-285", "CWE-926"],
    ),
    InvariantTemplate(
        template_id="iot.credential_no_extraction",
        statement_template=(
            "A co-installed app shall not be able to obtain a credential that "
            "authenticates against the backend as the user."
        ),
        attacker_models=["malicious_app"],
        cwe_classes=["CWE-200", "CWE-922"],
    ),
    InvariantTemplate(
        template_id="iot.notification_delivery_no_silencing",
        statement_template=(
            "A co-installed app shall not be able to silence or block "
            "notifications delivered to the companion app."
        ),
        attacker_models=["malicious_app"],
        cwe_classes=["CWE-285"],
    ),
]


_PRODUCTIVITY_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="productivity.acl_no_cross_user_data_access",
        statement_template=(
            "A user shall not be able to read or modify another user's data "
            "items (notes, decks, courses, posts) without an explicit grant."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-862", "CWE-200"],
    ),
]


_SECURITY_NETWORK_TEMPLATES: list[InvariantTemplate] = [
    InvariantTemplate(
        template_id="netsec.cert_validation_required",
        statement_template=(
            "The client shall not establish a tunneled or authenticated "
            "session against a peer whose certificate chain does not validate "
            "to the configured trust anchor."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-295"],
    ),
    InvariantTemplate(
        template_id="netsec.cipher_no_weak_negotiation",
        statement_template=(
            "The client shall not negotiate a session using a cipher suite or "
            "key length below the configured policy floor."
        ),
        attacker_models=["remote_attacker"],
        cwe_classes=["CWE-326", "CWE-327"],
    ),
    InvariantTemplate(
        template_id="netsec.sandbox_no_escape",
        statement_template=(
            "Code executing inside the application's sandbox shall not be "
            "able to access OS-level resources outside that sandbox."
        ),
        attacker_models=["malicious_app", "remote_attacker"],
        cwe_classes=["CWE-284"],
    ),
]


# ----- Profile registry -----


_PROFILES: dict[ArchetypeName, ArchetypeProfile] = {
    "messaging": ArchetypeProfile(
        name="messaging",
        apps=[
            "conversations",
            "deltachat-android",
            "jerboa",
            "jitsi-meet",
            "element-android",
            "nextcloud-talk",
            "simplelogin",
            "thunderbird",
            "tindroid",
            "miniflutt",
            "moememos",
        ],
        default_trust_boundaries=[
            "own server: honest-but-curious; peer servers untrusted",
            "peer users untrusted unless verified",
            "co-installed apps: Android sandbox boundary",
        ],
        cwe_focus=["CWE-285", "CWE-290", "CWE-862", "CWE-639"],
        invariant_templates=_MESSAGING_TEMPLATES,
    ),
    "sync_storage": ArchetypeProfile(
        name="sync_storage",
        apps=["davx5", "owncloud-android", "joplin", "wallabag"],
        default_trust_boundaries=[
            "sync server: untrusted under E2E mode, semi-trusted otherwise",
            "other sync users untrusted unless explicit grant",
        ],
        cwe_focus=["CWE-285", "CWE-639", "CWE-200", "CWE-284"],
        invariant_templates=_SYNC_TEMPLATES,
    ),
    "media": ArchetypeProfile(
        name="media",
        apps=["jellyfin", "audiobookshelf", "funkwhale", "linphone"],
        default_trust_boundaries=[
            "media server: trusted within deployment",
            "media artifacts: potentially attacker-controlled (parser surface)",
            "peer streams (linphone): peer untrusted until call accepted",
        ],
        cwe_focus=["CWE-285", "CWE-119", "CWE-787"],
        invariant_templates=_MEDIA_TEMPLATES,
    ),
    "iot_control": ArchetypeProfile(
        name="iot_control",
        apps=[
            "home-assistant-android",
            "openhab",
            "gotify",
            "ntfy-android",
            "owntracks",
        ],
        default_trust_boundaries=[
            "co-installed apps: Android sandbox + exported component boundary",
            "remote actor with low privilege: backend ACLs",
            "local network actor: TLS pinning + auth",
        ],
        cwe_focus=["CWE-285", "CWE-200", "CWE-926"],
        invariant_templates=_IOT_TEMPLATES,
    ),
    "productivity": ArchetypeProfile(
        name="productivity",
        apps=["ankidroid", "moodle", "grocy", "wordpress"],
        default_trust_boundaries=[
            "backend: trusted within deployment",
            "peer users untrusted unless explicit grant",
        ],
        cwe_focus=["CWE-862", "CWE-200"],
        invariant_templates=_PRODUCTIVITY_TEMPLATES,
    ),
    "security_network": ArchetypeProfile(
        name="security_network",
        apps=["openvpn", "termux"],
        default_trust_boundaries=[
            "data plane: fully untrusted (network MITM, malicious server)",
            "control plane: PKI-rooted",
            "user-imported configurations: out-of-scope (user-trusted)",
            "Android sandbox: enforced by OS",
        ],
        cwe_focus=["CWE-295", "CWE-326", "CWE-327", "CWE-284"],
        invariant_templates=_SECURITY_NETWORK_TEMPLATES,
    ),
}


# Reverse lookup: app_name → archetype_name. Built from _PROFILES.
_APP_TO_ARCHETYPE: dict[str, ArchetypeName] = {
    app: profile.name for profile in _PROFILES.values() for app in profile.apps
}


def get_archetype(app_name: str) -> ArchetypeProfile:
    """Return the archetype profile for ``app_name``.

    Raises :class:`KeyError` if the app is not in any archetype's app list.
    Pipeline callers should validate apps against
    :func:`list_known_apps` before invoking, or surface the missing
    assignment as an onboarding-required error.
    """
    archetype_name = _APP_TO_ARCHETYPE[app_name]
    return _PROFILES[archetype_name]


def get_profile(name: ArchetypeName) -> ArchetypeProfile:
    return _PROFILES[name]


def list_known_apps() -> list[str]:
    return sorted(_APP_TO_ARCHETYPE.keys())


def list_archetypes() -> list[ArchetypeProfile]:
    return list(_PROFILES.values())
