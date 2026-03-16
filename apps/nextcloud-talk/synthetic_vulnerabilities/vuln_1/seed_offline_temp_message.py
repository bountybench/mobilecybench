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


def refresh_conversation_list(d):
    """Pull-to-refresh the conversation list to sync rooms created via API."""
    width, height = d.window_size()
    cx = width // 2
    d.swipe(cx, int(height * 0.25), cx, int(height * 0.65), duration=0.5)
    time.sleep(4)


def open_room_from_list(d, label):
    """Find room by label in conversation list and open it."""
    scroll_to_label(d, label)
    target = wait_for(d, room_selector(d, label), timeout=30)
    target.click()
    wait_for(d, d(resourceId=f"{PACKAGE}:id/messageInput"), timeout=30)


def launch_chat_activity(d, room_token):
    """Navigate directly to a chat room via explicit intent."""
    intent = (
        f"am start -n {PACKAGE}/com.nextcloud.talk.chat.ChatActivity "
        f"--es KEY_ROOM_TOKEN {shlex.quote(room_token)} --activity-clear-top"
    )
    d.shell(intent, timeout=30)
    time.sleep(5)


def ensure_room_open(d, conversation_label, room_token=None):
    """Open the chat room.

    Tries a direct ChatActivity intent first (fast path). If the message
    composer doesn't appear — e.g. because the room isn't yet in the app's
    local DB after API creation — falls back to pull-to-refresh the
    conversation list and then navigates via the list.
    """
    if room_token:
        log(f"Opening room via direct intent: {room_token}")
        launch_chat_activity(d, room_token)
        try:
            wait_for_chat_ready(d, timeout=20)
            return
        except RuntimeError:
            log(
                "ChatActivity launch did not expose the composer; refreshing conversation list"
            )

    # Pull-to-refresh so rooms created via API appear in the local list.
    refresh_conversation_list(d)
    open_room_from_list(d, conversation_label)


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
