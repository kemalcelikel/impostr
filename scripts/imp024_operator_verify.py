"""COORDINATOR ONLY: credential-free operator helper/frontdoor synthetic proof.

Never invokes operator setup/key input or real HTTPS. Inject deterministic DATA
through the same native worker/relay; reuse delivered isolated worker and cleanup.
Review before Docker/broker/worker execution. No live/private inputs or auth bypass.
"""

import argparse
import json
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp024_broker import Broker, SyntheticProduct, SYNTHETIC_AGENTS, SYNTHETIC_BACKLOG, SYNTHETIC_PROJECT
from imp024_operator_helper import OperatorFixture
from imp024_operator import run_broker
from imp024_operator_product import Unavailable as ProductUnavailable
from imp024_protocol import terminal_error
from imp024_verify import reap_children, report, require


class SyntheticAcceptance(SyntheticProduct):
    def __init__(self, payload):
        super().__init__(payload)
        changes = json.loads(payload["prompt"].split("Target data (JSON, not instructions from a file):\n", 1)[1])
        allowed = (
            {"PROJECT.md": SYNTHETIC_PROJECT, "AGENTS.md": SYNTHETIC_AGENTS},
            {"BACKLOG.md": SYNTHETIC_BACKLOG},
            {"PROJECT.md": SYNTHETIC_PROJECT + "\nThe local owner reviews note text before saving.\n"},
        )
        require(changes in allowed)
        self.plan = [("read", {"filePath": "/project/" + name}) for name in changes]
        self.plan.append(("question", {"questions": [{"question": "Prepare the synthetic proposal?",
            "header": "Planning", "options": [{"label": "Yes", "description": "Synthetic only"}]}]}))
        self.plan.extend(("edit", {"filePath": "/project/" + name,
            "oldString": payload["documents"][name]["content"], "newString": content})
            for name, content in changes.items())


class SyntheticRejectedBacklog(SyntheticAcceptance):
    """Named provider-like terminal failure AFTER real spec/pair acceptance.

    No error details, host transport or operator input. The worker still receives
    a native terminal error and the product must visibly refuse completion/import.
    """
    def events(self, data, cancelled, deadline, *, submission=None):
        if self.plan[0][1]["filePath"] == "/project/BACKLOG.md":
            if submission is not None:
                require(not cancelled.is_set() and time.monotonic() < deadline)
                submission.consumed(data)
            yield terminal_error(0)
            return
        yield from super().events(data, cancelled, deadline, submission=submission)


def verify_rejected_product(product):
    files = product.review()
    require(files["project"]["origin"] == files["agents"]["origin"] == "agent"
            and files["backlog"]["origin"] == "template")
    require(product.get(product.root + "/document-pair-approval")["approved"] is True
            and product.get(product.root + "/final-approval")["approved"] is False)
    turns = product.get(product.base)["turns"]
    require(len(turns) == 2 and turns[-1]["state"] == "failed")
    events = [row for row in product.events() if row["turn_id"] == turns[-1]["id"]]
    require(sum(row["type"] == "failed" for row in events) == 1
            and not any(row["type"] in ("completed", "proposals") for row in events))
    for kind in files:
        require(product.client.get(product.root + "/final-approval/files/" + kind).status_code == 409)


def main(*, failure_after_pair=False):
    fixture = OperatorFixture()
    broker = thread = None
    passed = False
    try:
        fixture.prepare()
        broker = Broker(fixture.channel, persistent_directory=True,
                         transport_factory=SyntheticRejectedBacklog if failure_after_pair else SyntheticAcceptance,
                         mode="synthetic")
        failed = threading.Event()
        thread = threading.Thread(target=run_broker, args=(broker, failed), daemon=True)
        thread.start()
        if failure_after_pair:
            try:
                fixture.product.run()
            except ProductUnavailable:
                verify_rejected_product(fixture.product)
            else:
                require(False)  # Injected failure may never be a passing acceptance.
        else:
            fixture.product.run()
        require(thread.is_alive() and not failed.is_set())
        report("operator_helper_failed_acceptance_rejected" if failure_after_pair
               else "operator_helper_frontdoor_synthetic_acceptance", "passed")
        passed = True
    except (Exception, KeyboardInterrupt):
        report("operator_helper_failed_acceptance_rejected" if failure_after_pair
               else "operator_helper_frontdoor_synthetic_acceptance", "failed")
    finally:
        try:
            if broker is not None:
                broker.stop.set()
                if thread is not None:
                    thread.join(20)
                    require(not thread.is_alive())
                else:
                    broker.listener.close()
                    broker.path.unlink()
            reap_children()
        except Exception:
            passed = False
            report("operator_synthetic_broker_cleanup", "failed")
        passed = fixture.cleanup() and passed
    return 0 if passed else 1


if __name__ == "__main__":
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure-after-pair", action="store_true",
                        help="Inject credential-free native error after spec/pair; require rejection and owned cleanup")
    args = parser.parse_args()
    raise SystemExit(main(failure_after_pair=args.failure_after_pair))
