#!/usr/bin/env python3
import argparse
import shlex
import sys
import time

import uiautomator2 as u2

PACKAGE = "com.nextcloud.talk2"


def log(msg):
    print(f"[seed_temp_message] {msg}", file=sys.stderr, flush=True)


def wait_for(d, obj, timeout=30):
    if not obj.wait(timeout=timeout):
        raise RuntimeError(f"timed out waiting for {obj.selector}")
    return obj


def is_conversation_list_visible(d):
    return (
        d(text="Join a conversation or start a new one").exists
        or d(resourceId=f"{PACKAGE}:id/floatingActionButton").exists
        or d(resourceId=f"{PACKAGE}:id/dialogName").exists
    )


def wait_for_chat_ready(d, timeout=45):
    deadline = time.time() + timeout
    message_input = d(resourceId=f"{PACKAGE}:id/messageInput")
    while time.time() < deadline:
        if message_input.exists:
            return message_input
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {message_input.selector}")


def room_selector(d, label):
    exact = d(text=label)
    if exact.exists:
        return exact
    partial = d(textContains=label)
    if partial.exists:
        return partial
    return exact


def open_room(d, label):
    target = wait_for(d, room_selector(d, label), timeout=45)
    target.click()
    wait_for_chat_ready(d, timeout=45)


def scroll_to_label(d, label):
    scrollable = d(scrollable=True)
    if not scrollable.exists:
        return
    try:
        scrollable.scroll.to(text=label)
    except Exception:
        pass


def launch_chat_activity(d, room_token):
    intent = (
        f"am start -n {PACKAGE}/com.nextcloud.talk.chat.ChatActivity "
        f"--es KEY_ROOM_TOKEN {shlex.quote(room_token)} --activity-clear-top"
    )
    d.shell(intent, timeout=30)
    time.sleep(5)


def ensure_room_open(d, conversation_label, room_token=None):
    if room_token:
        log(f"Launching chat activity for room token: {room_token}")
        launch_chat_activity(d, room_token)
        try:
            wait_for_chat_ready(d, timeout=20)
            return
        except RuntimeError:
            log(
                "ChatActivity launch did not expose the composer, falling back to room list"
            )

    if not is_conversation_list_visible(d):
        log("Conversation list not visible yet, waiting briefly before fallback")
        time.sleep(5)

    scroll_to_label(d, conversation_label)
    open_room(d, conversation_label)


def wait_for_offline_banner(d):
    banner = d(text="Connection lost - Sent messages are queued")
    if banner.wait(timeout=15):
        return
    time.sleep(3)


def send_temp_message(d, message):
    input_box = wait_for_chat_ready(d, timeout=20)
    input_box.click()
    input_box.set_text(message)
    send_button = wait_for(
        d,
        d(resourceId=f"{PACKAGE}:id/messageSendButton", description="Send message"),
        timeout=20,
    )
    send_button.click()
    time.sleep(3)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversation-label", required=True)
    parser.add_argument("--room-token", default=None)
    parser.add_argument("--message", default="")
    parser.add_argument("--expect-offline", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    d = u2.connect()
    d.app_start(PACKAGE, wait=True)
    time.sleep(3)

    ensure_room_open(d, args.conversation_label, args.room_token)

    if args.expect_offline:
        wait_for_offline_banner(d)

    if args.message:
        send_temp_message(d, args.message)
        log("Seeded offline queued message through normal chat UI")
    else:
        log("Opened seeded room successfully")


if __name__ == "__main__":
    main()
