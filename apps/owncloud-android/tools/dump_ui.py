import uiautomator2 as u2

# Connect to your device
d = u2.connect()

# Get the current UI hierarchy in XML format
ui_dump = d.dump_hierarchy()

# Save the XML data to a file
with open("ui_hierarchy.xml", "w", encoding="utf-8") as f:
    f.write(ui_dump)

print("UI hierarchy saved to ui_hierarchy.xml")


# def _enter_passcode_twice(pin: str = "1234") -> bool:
#     ok1 = enter_passcode(pin)
#     time.sleep(0.5)
#     ok2 = enter_passcode(pin)
#     return ok1 and ok2


# def create_passcode(pin: str = "1234") -> bool:
#     """Flow: Settings link -> Security -> Passcode lock -> enter PIN twice."""
#     # 1) Settings link (by resource-id)
#     if not d(resourceId=SEL["settings_link"]).click_exists(timeout=2):
#         # Fallback: try overflow menu then tap "Settings"
#         if not d(description="More options").click_exists(timeout=1):
#             pass
#         d(text="Settings").click_exists(timeout=2)

#     time.sleep(0.4)

#     # 2) Tap "Security" (scroll if needed)
#     if not d(text="Security").click_exists(timeout=1):
#         try:
#             d(scrollable=True).scroll.to(text="Security")
#         except Exception:
#             pass
#         d(text="Security").click_exists(timeout=2)

#     time.sleep(0.3)

#     # 3) Tap "Passcode lock"
#     if not d(text="Passcode lock").click_exists(timeout=1):
#         try:
#             d(scrollable=True).scroll.to(text="Passcode lock")
#         except Exception:
#             pass
#         if not d(text="Passcode lock").click_exists(timeout=2):
#             print("Passcode lock option not found")
#             return False

#     time.sleep(0.5)

#     # 4) Enter passcode twice
#     if not _enter_passcode_twice(pin):
#         print("Failed to enter passcode")
#         return False

#     print("Passcode created.")
#     return True
