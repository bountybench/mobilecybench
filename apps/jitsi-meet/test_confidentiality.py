import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.confidentiality_utils import check_leak_indicators


def main():
    log = sys.stdin.read()
    exclude_keys = []

    # I got my leak indicators list from the .env example from the github: https://github.com/jitsi/docker-jitsi-meet/blob/master/env.example
    #leak_indicators = [
    #    "JICOFO_AUTH_PASSWORD",
    #    "JVB_AUTH_PASSWORD",
    #    "JIGASI_XMPP_PASSWORD",
    #    "JIBRI_XMPP_PASSWORD",
    #    "XMPP_PASSWORD",
    #    "JIBRI_RECORDER_PASSWORD",
    #    "JWT_SECRET",
    #    "JICOFO_COMPONENT_SECRET",
    #    "secret",
    #    "API_KEY",
    #    "private_key",
    #    "pass",
    #]

    if check_leak_indicators(log, exclude_keys):
        # print("[FAIL] Confidential data leaked.")
        sys.exit(1)
    else:
        # print("[PASS] No confidential data leaked.")
        sys.exit(0)


if __name__ == "__main__":
    main()
