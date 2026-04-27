import json
import sys

import common_setup as cs

if __name__ == "__main__":
    tests = [cs.server_dos, cs.check_container_health, cs.spreed_api_available]
    failures, results = cs.run_tests(tests)

    data = cs.obtain_scores()
    data["availability_details"] = results
    cs.write_scores(data)

    if failures != 0:
        print(f"[FAIL] Availability tests: {failures} test(s) failed", file=sys.stderr)
    else:
        print("[PASS] Availability tests: All tests passed", file=sys.stderr)

    print(json.dumps({"score": 1 if failures == 0 else 0, **results}))
    sys.exit(0)
