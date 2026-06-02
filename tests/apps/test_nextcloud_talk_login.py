import importlib.util
import sys
import types
from pathlib import Path


def load_login_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "uiautomator2", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "utils.ui_utils",
        types.SimpleNamespace(click_then_expect=lambda *args, **kwargs: True),
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "nextcloud-talk"
        / "ui_automation"
        / "login.py"
    )
    spec = importlib.util.spec_from_file_location("nextcloud_talk_login_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules["nextcloud_talk_login_test"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("nextcloud_talk_login_test", None)
    return module


def test_wait_for_initial_login_state_rechecks_native_server_screen(monkeypatch):
    module = load_login_module(monkeypatch)
    calls = {"server_url": 0}

    def delayed_server_url_screen(_device):
        calls["server_url"] += 1
        if calls["server_url"] < 3:
            return None
        return object()

    monkeypatch.setattr(module, "server_url_field", delayed_server_url_screen)
    monkeypatch.setattr(module, "is_logged_in", lambda _device: False)
    monkeypatch.setattr(module, "on_ssl_cert_dialog", lambda _device: False)
    monkeypatch.setattr(
        module, "on_browser_login_handoff_screen", lambda _device: False
    )
    monkeypatch.setattr(module, "current_package", lambda _device: module.PACKAGE)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    state = module.wait_for_initial_login_state(object(), timeout=1, interval=0)

    assert state == "server_url"
    assert calls["server_url"] == 3


def test_launch_app_retries_with_monkey_when_launcher_stays_foreground(monkeypatch):
    module = load_login_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    class Device:
        def __init__(self):
            self.shell_calls = []

        def app_start(self, package, wait=True):
            assert package == module.PACKAGE
            assert wait is True

        def shell(self, command):
            self.shell_calls.append(command)

        def app_current(self):
            if any(call.startswith("monkey ") for call in self.shell_calls):
                return {"package": module.PACKAGE, "activity": ".MainActivity"}
            return {
                "package": "com.google.android.apps.nexuslauncher",
                "activity": ".NexusLauncherActivity",
            }

    device = Device()

    assert module.launch_app(device, timeout=1) is True
    assert any(
        call == f"monkey -p {module.PACKAGE} -c android.intent.category.LAUNCHER 1"
        for call in device.shell_calls
    )


def test_submit_server_url_accepts_browser_when_submit_icon_disappears(monkeypatch):
    module = load_login_module(monkeypatch)

    class MissingElement:
        exists = False

    class Device:
        def __init__(self):
            self.pressed = []

        def __call__(self, **_kwargs):
            return MissingElement()

        def app_current(self):
            return {
                "package": module.BROWSER_PACKAGE,
                "activity": "org.chromium.chrome.browser.firstrun.FirstRunActivity",
            }

        def press(self, key):
            self.pressed.append(key)

    device = Device()

    assert module.submit_server_url(device, timeout=1) is True
    assert device.pressed == []


def test_submit_server_url_waits_for_browser_after_arrow_click(monkeypatch):
    module = load_login_module(monkeypatch)

    class Element:
        def __init__(self, exists, click=None):
            self.exists = exists
            self._click = click

        def click(self):
            if self._click is not None:
                self._click()

    class Device:
        def __init__(self):
            self.clicked = False

        def __call__(self, **kwargs):
            if kwargs.get("resourceId") == f"{module.PACKAGE}:id/text_input_end_icon":
                return Element(not self.clicked, self._mark_clicked)
            return Element(False)

        def _mark_clicked(self):
            self.clicked = True

        def app_current(self):
            package = module.BROWSER_PACKAGE if self.clicked else module.PACKAGE
            return {"package": package, "activity": ".Activity"}

    device = Device()

    assert module.submit_server_url(device, timeout=1) is True
    assert device.clicked is True


def test_handle_grant_access_accepts_direct_return_to_app(monkeypatch):
    module = load_login_module(monkeypatch)

    class Device:
        def __call__(self, **_kwargs):
            return object()

        def app_current(self):
            return {"package": module.PACKAGE, "activity": ".MainActivity"}

    device = Device()

    monkeypatch.setattr(module, "on_account_connected_page", lambda _device: False)
    monkeypatch.setattr(module, "is_logged_in", lambda _device: True)
    monkeypatch.setattr(
        module,
        "click_then_expect",
        lambda _device, _target, expected, **_kwargs: expected(),
    )
    monkeypatch.setattr(
        module,
        "launch_app",
        lambda _device, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launch_app should not run after direct app return")
        ),
    )

    module.handle_grant_access(device)


def test_handle_grant_access_does_not_accept_browser_as_app_return(monkeypatch):
    module = load_login_module(monkeypatch)
    launch_kwargs = {}

    class Device:
        def __call__(self, **_kwargs):
            return object()

        def app_current(self):
            return {
                "package": module.BROWSER_PACKAGE,
                "activity": "org.chromium.chrome.browser.ChromeTabbedActivity",
            }

    device = Device()

    monkeypatch.setattr(module, "on_account_connected_page", lambda _device: True)
    monkeypatch.setattr(module, "is_logged_in", lambda _device: True)
    monkeypatch.setattr(
        module,
        "click_then_expect",
        lambda _device, _target, expected, **_kwargs: expected(),
    )

    def fake_launch(_device, **kwargs):
        launch_kwargs.update(kwargs)
        return True

    monkeypatch.setattr(module, "launch_app", fake_launch)

    module.handle_grant_access(device)

    assert launch_kwargs["accept_browser"] is False
