"""Non-serving synthetic IMP-023 launcher. Server scenarios require boundary review.

No operator/private/live mode, arbitrary target, auth input, or server proxy exists.
All server requests and fixture controls run inside the mandatory IMP-002 worker.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp002_prototype import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("startup", "history", "reconnect", "interrupt"))
    args = parser.parse_args()
    try:
        return run("imp023-" + args.scenario)
    except Exception:
        # No process output, settings, exceptions, transcripts or generated auth.
        print(json.dumps({"success": False, "session_capability_unavailable": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
