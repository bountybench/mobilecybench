from utils.crash_metrics import (
    parse_anr_traces,
    parse_dropbox_crashes,
    parse_logcat_crashes,
)


def test_parse_logcat_crashes_filters_for_target_package():
    logcat = """04-13 11:20:01.100  1000  1000 E AndroidRuntime: FATAL EXCEPTION: main
04-13 11:20:01.101  1000  1000 E AndroidRuntime: Process: com.example.app, PID: 1234
04-13 11:20:01.102  1000  1000 E AndroidRuntime: java.lang.NullPointerException: boom
04-13 11:20:03.100  1000  1000 E AndroidRuntime: FATAL EXCEPTION: main
04-13 11:20:03.101  1000  1000 E AndroidRuntime: Process: com.other.app, PID: 9999
04-13 11:20:03.102  1000  1000 E AndroidRuntime: java.lang.IllegalStateException: ignore
"""
    events = parse_logcat_crashes(logcat, "com.example.app")

    assert len(events) == 1
    assert events[0].type == "FATAL_EXCEPTION"
    assert events[0].timestamp == "04-13 11:20:01.100"
    assert "NullPointerException" in events[0].summary


def test_parse_dropbox_crashes_detects_crash_and_anr_entries():
    dropbox = """========================================
Tag: data_app_crash
Timestamp: 2026-04-13T18:20:01Z
Package: com.example.app
java.lang.IllegalArgumentException: broken
========================================
Tag: app_anr
Timestamp: 2026-04-13T18:21:01Z
Cmd line: com.example.app
"""
    events = parse_dropbox_crashes(dropbox, "com.example.app")

    assert len(events) == 2
    assert {event.type for event in events} == {"DROPBOX_CRASH", "ANR"}


def test_parse_anr_traces_detects_matching_cmdline():
    traces = """----- pid 222 at 2026-04-13 11:20:01 -----
Cmd line: com.example.app
some blocked stack
----- end 222 -----
----- pid 333 at 2026-04-13 11:21:01 -----
Cmd line: com.other.app
----- end 333 -----
"""
    events = parse_anr_traces(traces, "com.example.app")

    assert len(events) == 1
    assert events[0].type == "ANR"
    assert "com.example.app" in events[0].summary
