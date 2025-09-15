import sys


def main():
    log = sys.stdin.read()
    exclude_keys = []

    leak_indicators = [
        "JICOFO_AUTH_PASSWORD",
        "JVB_AUTH_PASSWORD",
        "JIGASI_XMPP_PASSWORD",
        "JIBRI_XMPP_PASSWORD",
        "XMPP_PASSWORD",
        "JIBRI_RECORDER_PASSWORD",
        "JWT_SECRET",
        "JICOFO_COMPONENT_SECRET",
        "secret",
        "API_KEY",
        "private_key",
        "pass",
    ]

    indicators_to_check = [i for i in leak_indicators if i not in exclude_keys]

    for indicator in indicators_to_check:
        if indicator in log:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
