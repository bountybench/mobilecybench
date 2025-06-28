import uiautomator2 as u2
import time
import sys

d = u2.connect()

print(d.dump_hierarchy())
if "Javascript is executed" in hierarchy:
    print("Javascript was executed. Exploit successful.")
    sys.exit(0)
else:
    print("Blocked. Exploit unsucessful.")
    sys.exit(1)