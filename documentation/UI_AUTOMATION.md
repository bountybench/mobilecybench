## UI Automation

If UI automation is required (e.g., logging in a user), follow these guidelines:

### Use `click_then_expect()`

Located in `utils/ui_utils.py`, this function serves as a click, then assert. This forces the user to declare what action they want to take as well as the impact of said action

```python
from utils.ui_utils import click_then_expect, press_back_then_expect

# Click and verify expected element appears
menu_btn = d(description="More options")
menu_item = d(text="Settings")
if click_then_expect(d, menu_btn, menu_item):
    # Menu opened successfully
    ...
```

### Handle Multiple Starting States

Your login script must handle:
- No user logged in
- User already logged in
- Mid-flow states (app crashed, partial login)

### Add Assertions Between Steps

Don't chain commands without verification:

```python
# ❌ BAD - no verification between steps
d(text="Login").click()
d(text="Username").set_text("user1")
d(text="Submit").click()

# ✅ GOOD - verify each step
login_btn = d(text="Login")
username_field = d(resourceId="com.example:id/username")
if click_then_expect(d, login_btn, username_field):
    username_field.set_text("user1")
    # continue with verification...
```

### Writing UI Automation

Use this prompt to create robust automation:

> I am trying to write robust UI automation to do [XYZ]. You have access to an android emulator and adb. First read utils/ui_utils.py to see what tools you have available. Then, walk through the steps manually, via adb, taking a screenshot + UI dump of the current screen before moving on. Only after you completed the task use the existing utilities to write UI automation. You can refer to apps/conversations/ui_automation/login.py as an example.
