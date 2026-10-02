# Local development setup

These instructions cover the IMP-001 bootstrap, IMP-003 identity/account
administration, the IMP-004 project and Markdown-draft implementation, the
human-only pair-approval slice from IMP-013, and the IMP-007 backlog-task API and
operator candidate review. Run commands from the repository root. Docker Compose
is the supported install and start path; there is no supported direct Vite
development-server command. This is local-only, work-branch software, not a
shared-server release. Candidate review evidence applies only to the exact
reviewed snapshot; neither a candidate preview nor a worktree alone constitutes a
delivered release. Consult `BACKLOG.md` for task outcomes.

## PDF extractor phase one — locally verified (IMP-017)

`compose.pdf.yaml` is standalone, opt-in boundary packaging, not an ordinary-stack
PDF feature. This phase-one extractor/channel boundary is not itself the ordinary
application intake or model integration. The affected reviewed boundary now has actual
coordinator acceptance: **56 pure tests and the full runtime helper passed**, including
pinned build, mountless namespace/Landlock/seccomp containment, filesystem/socket
denials, output/timeout/escaped-descendant cleanup, representative PDFs, exact decimal
50MB success, expansion limit and encrypted rejection, busy/short-body/overrun recovery,
scratch reuse, peer/credential denials, new-listener readiness, whole-job deadline EOF,
stopped-container and post-restart extraction recovery. Owned cleanup passed. This
supersedes the failed intermediate outcomes preserved below; it is not merely mock
or pathname-existence evidence.

Verified coordinator command from repository root:
`/usr/bin/python3 -B scripts/imp017_verify.py --reviewed-runtime`.
It uses an owned disposable standalone stack and removes its containers, channel
volume and image; it does not activate application PDF intake. No additional runtime
rerun is needed for this documentation-only finalization.

Exact successful build references (nonsecret hashes, not retained runtime artifacts):

- Build provenance SHA256:
  `b976249ca1a5aea47689ac9210b15611b6b9c88ab9c337f766e5e1569faa4192`
- Image ID:
  `sha256:68efe37a1cb9e110def0d47369dff31218df21d118359f22e766b24472addcaf`

The checked-in dependency lock and image-build recorder preserve the pinned base,
snapshot, versions, source and hash-generation contract. Complete resolved `build.json`
provenance is generated inside the dedicated image; no downloaded packages, image
archive, generated PDFs, transcripts or runtime scratch belong in the source commit.

IMP-017's three phases are delivered: phase-one extractor delivery is committed in
`ca09dc3`, phase-two DB/raw intake in `269710f`, and phase-three extraction/lifecycle
in `8925dfa`. Phase two used **2/5** attempts and phase three **4/5**; their histories
are preserved. IMP-018 phase four is exhausted (**5/5**) and phase five has used
**2/5**. A renewed finite phase-four scope is required before further implementation.
No automatic runner/application start, UI/model activation, live provider acceptance
or completed local-use workflow follows from IMP-017 acceptance.

### IMP-018 PDF composer and inference receipt — unaccepted candidate

The uncommitted backend candidate adds selected attachment references, an inference
receipt and delete handling, but the PDF composer is absent. It is not a usable
candidate: actual end-to-end inference and rendered proof have not passed. Static
reviews passed; runtime acceptance did not. Earlier fresh-PostgreSQL evidence passed
two tests and failed `capture_delete_race`; the latest corrective candidate has
no passing fresh PostgreSQL rerun.

Latest coordinator check, from repository root:
`/usr/bin/python3 -I -B scripts/imp018_verify.py --api-only`.
Build, DB startup, upgrade and current migration (`0010`) passed. The final focused API
run failed at `test_delete_outage_is_fenced_pending_and_purge_recovers_without_scrubbing_quotes`
with an `AssertionError` at the call assertion. Earlier focused API passes are not
final acceptance. All owned cleanup passed. Do not treat this candidate as usable or
claim full inference/rendered acceptance; preserve the later human live-provider test.
No private configuration access, push or automatic start is authorized.

## PDF DB/raw intake phase two — coordinator-verified (IMP-017)

The API persists project- and conversation-scoped attachment records and raw PDF
originals in PostgreSQL, with status/list, raw download, escaped text-preview and
delete routes under `/api/projects/{project}/chat/{conversation}/attachments`.
Upload uses `POST .../upload?filename=<name>.pdf` with a raw `application/pdf`
request body; the actual body is bounded to 50,000,000 bytes and its digest is
recorded. Intake checks the PDF envelope, not PDF structural validity: an accepted
upload is `pending`, not validated or ready. There is no parser dispatch, automatic
processing/readiness, UI or model inclusion in this phase; preview is unavailable
until a future extraction lifecycle supplies ready text.

Coordinator synthetic verification passed build, migration 0008, focused API and
fresh PostgreSQL preservation/over-cap/hash/delete checks, Ruff, format, mypy,
Nginx checks and owned cleanup. Command from repository root:
`/usr/bin/python3 -I -B scripts/imp017_intake_verify.py`. This is a
coordinator-only synthetic disposable verification, **not** normal operator setup
or an instruction to start PDF intake. Phase two remains delivered in `269710f`;
its migration/API evidence is preserved, not invalidated by the phase-three addition.

Limits remain PDF text-layer only: no OCR/scanned support or image/diagram understanding,
max50,000,000 original bytes, 500 pages, 128KiB UTF-8 derivative and 30s whole-job
deadline, in the existing networkless non-root resource-bounded extractor. Mixed
documents report missing-text pages and the explicit text-only label; there is no
fidelity/comprehension or real-provider acceptance claim. No private HTTPS or other
attachment formats are activated by this PDF-only slice.

### PDF extraction lifecycle — coordinator-verified phase three

The verified lifecycle uses migration 0009 and an API-owned background thread,
independent of chat enablement. Default `IMPOSTR_PDF_ENABLED=0` performs no channel
dispatch; only exact `0`/`1` are supported. Explicit ordinary integration uses
`compose.yaml` plus `compose.pdf-app.yaml`; the latter reuses unchanged phase-one
converter packaging and mounts only its private Unix channel read-only in the API.
The converter remains networkless, non-root, resource bounded, and without any DB,
repository, broker, workspace or credential mounts. The reviewed candidate passed
the coordinator's full runtime helper; these configuration facts are still not an
instruction to start the application or runner.

Accepted originals are durably `pending`; one API pump claims them as `processing`
with a 45-second token lease before conversion, closing its DB transaction/session
before the existing 30-second whole-job client call. Completion atomically requires
the same unexpired lease. Restart can reclaim expired work; completion after deletion
or a newer claim cannot recreate/overwrite records. The maximum is three attempts.
Only `busy`/`unavailable` retry with durable 5-/15-second backoff; exhaustion and all
other rejections (including timeout) remove originals/derivatives and retain safe
failure metadata. Ready derivatives are protocol-validated, including text hash,
page coverage and the actual phase-one verified build fingerprint listed above.
Metadata reports configured processing, attempts and transient retry status, not
proof of converter health or model submission. No model/UI inclusion is added.

Processing is server-owned once upload commits: logout/revocation blocks subsequent
access but does not cancel extraction or delete retained project data. All attachment
HTTP operations retain the existing current-actor/project/conversation checks.
Explicit deletion and the existing conversation/project foreign-key cascades remove
durable data; there is no separate filesystem authority/cache to orphan. In-flight
private bytes may exist only until the bounded job returns/exits. Graceful API shutdown
stops admission and joins its PDF thread; forced exit leaves only a recoverable lease.

After affected independent review, the coordinator's actual
`/usr/bin/python3 -B scripts/imp017_lifecycle_verify.py --reviewed-lifecycle` passed
source/build provenance, API/DB build and migration, focused API tests, Ruff lint/format,
mypy and fresh PostgreSQL checks. The joined run passed unavailable recovery, actual
ready provenance, busy admission/durable retry, terminal blob removal, deletion during
extraction, API crash/lease recovery, concurrent PostgreSQL lease ownership, revoked
access and graceful shutdown. All joined/stack/account/volume/image/input cleanup
passed. The **96 pure IMP-017 tests** are retained passing evidence; no repeat check
is needed for this documentation-only finalization. Phase three is verified at
**4/5 used**, with the remaining **1/5 not needed**.

The helper reuses intake-owned fixture handling and synthetic PDF inputs; it does not
repeat sandbox verification. The initial absent-image stop was an ordinary artifact
failure: phase-one cleanup had intentionally removed `impostr-pdf:phase1`. Attempt
3/5 added the reviewed absence-only reconstruction and mechanical fixture diagnostics/
mock correction; attempt 4/5 corrected the final shutdown expectation. These failed
intermediate checkpoints are history, not active blockers.

Before use, the helper requires extractor inputs to match committed `ca09dc3` via
`git diff --no-ext-diff --no-textconv --exit-code`, including dependency lock, build
recorder, bootstrap, protocol, seccomp and standalone Compose packaging. It validates
the original `.dockerignore` hash with only the exact synthetic fixture allowance
added, and refuses a Dockerfile-specific ignore override. An existing shared image
is never rebuilt, retagged or removed. Only a successful empty shared-tag inventory
allows one bounded reconstruction under an exclusively reserved per-run tag, using
the existing standalone Compose build with `--env-file /dev/null` and the fixture's
minimal environment/fresh HOME. No application `.env` or private Docker configuration
is read; networked parser installation remains confined to the pinned image build.

For either path, a container is created but not started. Bounded `docker cp` archives
are hashed locally to require exact worker/supervisor source bytes and both actual
`build.json` hashes equal to `b976249ca1a5aea47689ac9210b15611b6b9c88ab9c337f766e5e1569faa4192`.
Lifecycle execution is pinned to that validated immutable image ID, not a mutable tag
or the historical Docker ID alone. Output projects only fixed stages and nonsecret
source/build/image hashes. Cleanup removes owned containers/volumes and only the
owned reconstructed image tag, leaving pre-existing images untouched. Failed build,
source/provenance checks or cleanup fail acceptance, without automatic retries.
Focused pytest failures project at most 16 allowlisted file/test-function names from
the existing short summary, with only `assertion`/`unknown` categories. Parameter
IDs, assertion values, source snippets and raw logs are discarded; unrecognized
output retains a fixed unknown finding. This changes reporting, not test execution.

Actual reconstruction passed the unchanged source-base check against `ca09dc3` and
the exact build hash above. Its different immutable Docker image ID was correctly
accepted only after actual packaged provenance validation and pinned for execution.
Reconstructing this owned disposable artifact is permitted packaging recreation,
not extractor reimplementation or policy relaxation. Owned cleanup removed it; no
retained image or historical Docker ID is a prerequisite for continuation.

The final joined shutdown check was accepted in phase-three **attempt 4/5**.
After revoked-access assertions pass, it requires a fresh completion marker written
only after successful application lifespan exit, including the PDF processor's bounded
close/join. Pinned Uvicorn 0.54.0 re-raises SIGTERM after graceful shutdown, so the
expected subprocess status is `-SIGTERM`, not zero; that status without the fresh
marker does not pass. A fixed `shutdown` substage isolates failures from revocation.
Previously passing lifecycle/security/static/PG checks remain valid evidence; this
fixture correction does not change product authorization, retention or parsing.

### Preserved phase-one repair history (superseded by verification above)

The following review-ready/blocked outcomes and next-step instructions describe
earlier checkpoints, not current prerequisites or authorization for more diagnostics.

**Renewed diagnostic (attempt 1/3):** The subsequent coordinator run passed
the pinned build and mountless namespace/Landlock/seccomp denial, timeout/output,
escaped-descendant and owned-cleanup checks. Representative channel execution then
failed with only `container-runtime/verifier`; this establishes neither a Docker
fault nor successful extraction. Prior startup repair 3/3 and original phase-one
5/5 are retained; later phases remain 0/5.

The renewed diagnostic leaves containment, parser policies and cleanup unchanged.
It catches the synthetic client's failures into a fixed record, then projects only
`client_fixture`, `client_stage`, `client_error`, `result_status` and `result_code`
from the **same captured client stdout**. Stage/fixture/error/status/code are fixed
enums; unknown or noncanonical records (including extra keys, raw output or trailing
data) yield fixed unknown fields. Only the exact ordered prefix of known PASS lines
may precede a record. No PDF text, exception strings, traceback, paths, settings or
stderr are reported. A failed representative exec is `client-workflow-failure`, not
an attributed container/parser fault. Failure still denies acceptance and runs owned
cleanup.

**Expansion fixture repair (previous renewed attempt 2/3):** Coordinator's
diagnostic run passed 45 pure tests, pinned build/containment and owned cleanup, then
reported `client_fixture=expansion client_stage=extract client_error=pdf-error
result_status=unknown result_code=invalid`. In this exact client order, all fourteen
small fixtures had completed their assertions: valid text and mixed coverage, scanned,
zero, punctuation, spoof, malformed, escaped/compressed actions, embedded files, XFA,
rich media, external streams and page-limit rejection. The decimal50MB fixture then
returned ready at exactly 50,000,000 bytes. These are status/text checks, not proof
of each rejected fixture's specific reason. Encrypted bytes had been generated,
but encrypted rejection, busy/short-body, overrun, peer and deadline-restart checks
had not run. No full phase-one acceptance follows from this intermediate evidence.

The old expansion stream placed 100,000 text copies at the same coordinate, testing
pathological layout rather than predictable output expansion. No obvious object/xref
defect was found; `pdf-error/invalid` raised by the client is not a worker rejection
code and does not prove a qpdf fault. A whole-job EOF remains a hypothesis, not a
measured timeout cause. Replace that workload with 32 ordinary pages, each holding
48 non-overlapping Courier lines in small Flate streams: compressed input <1MB,
inflated content <256KiB and visible text >128KiB, within the unchanged 500-page
bound. Pure tests check the exact generated lengths/xref/references/layout; they
do not execute a host parser or establish actual parser acceptance.

`expansion: PASS` now requires the exact validated `rejected('limit')` result, not
an invalid/timeout rejection or a dropped channel. Worker/supervisor/protocol,
containment, time/output/page/resource bounds and owned cleanup are unchanged.
The host also reprints only the canonical captured prefix of known PASS markers
before a fixed client failure; malformed records still yield unknown fields and
no partial PASS projection. The corrected fixture awaits affected review and real
confined execution; renewed budget is 2/3, earlier 5/5 + 3/3 retained, later 0/5.

**Deadline diagnostic continuation (2/3 used):** Coordinator subsequently
passed 47 pure tests, pinned build/containment, all representative checks (including
exact limit expansion, encrypted rejection and decimal50MB), busy/short-body,
counted-overrun, scratch reuse and both peer denials. Owned cleanup passed. The next
`whole-job-deadline-restart` stage failed with only `container-runtime/verifier`;
trigger, stopped-state, restart, readiness and recovery outcomes were indistinguishable.
This does not identify a root cause or complete phase-one acceptance.

The diagnostic-only continuation reuses the existing captured client result and
strict fixed schema. `deadline_step` identifies the host fixture operation; trigger
and recovery clients report fixed `deadline-trigger`/`deadline-recovery` fixtures,
stage/error/status/code, including distinct connection-error versus timeout versus
assertion/PDFError. Unknown/raw/noncanonical output stays unknown. No logs, exception
strings, PDF text or new private lookups are added. A reset, timeout or nonempty
reply still **fails** the unchanged EOF assertion. The accepted-but-unfinished body,
35s socket timeout, 40s exec bound, stopped-container assertion, bounded readiness
loop and ready recovery assertion remain. No production boundary or limit changes.
50 pure tests cover the fixture diagnostics and mocked failure/cleanup paths; actual
deadline behavior still awaits affected review and coordinator execution. The final
focused repair attempt 3/3 remains available only after an actual failure is located.
Static tracing identifies one concrete harness concern to distinguish, not yet the
measured failure: protocol `receive(... +2)` resets the socket timeout while reading
the acceptance frame, so the following EOF read does not retain the preceding 35s
setting. The diagnostic leaves this behavior unchanged and tests that mutation;
use the actual fixed trigger/stage/error result before selecting a correction.

**Confirmed harness repair (previous renewed attempt 3/3):** Coordinator's fixed
diagnostic located the failure at `deadline_step=trigger`, acceptance received, then
`client_stage=deadline-eof client_error=timeout`. This confirms the fixture's short
acceptance-frame socket timeout was retained for the deliberate whole-job wait.
The trigger now captures an absolute `monotonic() + JOB_SECONDS + 5` deadline before
connecting, then restores only its **remaining** time after acceptance. The fixed 5s
grace is a harness wait allowance, not a change to the supervisor's 30s hard job
deadline. Elapsed connection/acceptance time is deducted; an expired absolute wait
fails rather than being renewed. EOF, stopped-container, bounded restart readiness
and ready recovery assertions remain mandatory; resets/nonempty replies still fail.

52 pure tests pass, including a fake acceptance receive that shortens the socket
timeout and an EOF check that succeeds only when the original remaining wait is
restored, plus expired-deadline rejection without sleeps. Production/parser/channel
containment and limits are unchanged; reuse the coordinator's passing representative,
50MB/expansion/encrypted, busy/overrun/scratch/peer and cleanup evidence. Actual repaired
deadline/restart acceptance awaits affected review and coordinator verification.
Renewed budget is now 3/3; original phase-one5/5, earlier repair3/3 and later0/5 retained.

**New-listener repair (new restart budget attempt 1/3):** From
`2a3d08c`, owner approved three focused attempts, preserving original5/5 and both
previous repair3/3 histories, later0/5. Coordinator's prior extraction/containment,
deadline EOF and stopped-container checks passed; recovery raised
`deadline-recovery/extract/pdf-error/unavailable`, with owned cleanup passing.
Socket pathname existence could report the old named-volume socket after forced
exit. This is a concrete harness defect, not an established cause of that failure.

The harness now records only the old socket device/inode internally before triggering
the deadline. After restart it checks the container is running, then waits at most
10s (12s outer exec limit) for different socket identity, the existing exact directory/
socket ownership and modes, and an authenticated responding listener. The check
holds the current socket's nofollow O_PATH reference across connect and revalidates
its identity/metadata afterward. It uses the already-tested synthetic UID10002:GID10001
credential denial: this UID can connect but the supervisor rejects it **before**
job/lease acquisition. No header, data, ping extension or extraction job is sent.
EOF/reset confirms the existing denial path responded; a stale/missing/replaced
socket, unfinished permissions, refused connection or nonresponsive listener cannot
produce `new-listener: PASS`. Container-running is checked again afterward.

Only listener startup is polled. One recovery extraction follows, with **no retry**
after parser/channel failure. Strict snapshot parsing prevents raw identity output
from reaching reports; readiness failures use existing fixed client fields. No
production/protocol/image/security-policy or resource-bound changes are made.
56 pure tests pass, including stale/changed/missing socket, refused/nonresponsive
listener, metadata/credential checks, no-send behavior and mocked failure cleanup.
Affected review caught that UID10002:GID10001 cannot import from the private
UID10001 mode0700 `/fixture`. The mechanical attempt-one correction makes the
denied-UID listener check fully inline with only fixed standard-library dependencies
and fixed diagnostics. Its metadata/peer/deadline/held-inode checks are retained;
no private fixture permissions or image packaging are changed. Tests execute these
actual inline definitions with fakes and verify no private imports or secret output.
Use the unchanged full verifier command below once after affected review; no new
restart-only mode or acceptance bypass. Actual new-listener/recovery acceptance is
still for the coordinator, not proved by these pure tests.

After affected independent review, the coordinator alone runs from repository root:
`/usr/bin/python3 -B scripts/imp017_verify.py --reviewed-runtime`.
Use its sanitized fixture/stage/error and cleanup outcome to choose the next focused
repair; do not relax passing containment or retry blind. The older startup narrative
below is preserved as history.

The first additional diagnostic slice leaves Compose, image, seccomp and parser
launch/cleanup unchanged. Public
[`bubblewrap.c` v0.8.0](https://github.com/containers/bubblewrap/blob/v0.8.0/bubblewrap.c)
ties the error to `mount(NULL, "/", NULL, MS_SILENT | MS_SLAVE | MS_REC, NULL)`.
After independent review of this diagnostic, the coordinator alone runs from root:
`/usr/bin/python3 -B scripts/imp017_verify.py --reviewed-runtime`.
Do **not** run `scripts/imp017_mount_probe.py` directly on the host.

Only an exact `mount-propagation-denied` startup failure triggers the new helper in
a separate disposable, networkless extractor-image container with the same dropped
capabilities, seccomp, no-new-privileges and resource limits, and no channel mount.
It verifies non-root/zero-capability outer identity, atomically creates fresh user
and mount namespaces, verifies both changed, writes only its own fixed single-ID
maps, and requires namespace-local mount capability before trying that one syscall.
It emits only `root-propagation-diagnostic=<fixed-stage>:<fixed-outcome>` and
`root-propagation-policy=unattributed`. Unreadable self facts stop without another
reader; no policy lookup, tracing dependency or permission expansion is attempted.
The verifier still fails containment and cleans up even if that diagnostic says
`root-slave-recursive:ok`. Python reproduction is not the actual bwrap execution:
success or denial cannot attribute executable-specific AppArmor or another policy.
`namespace-guard`/map/unshare failures mean a required diagnostic capability is
unavailable; stop for the sanitized result, not blind retries or further allowances.

Coordinator's attempt-one diagnostic subsequently reported
`root-slave-recursive:eacces`, policy unattributed, with build and cleanup passing.
**Attempt two is a material mountless candidate, not runtime acceptance.** It keeps
outer Compose limits/security and the Unix API contract. An existing image
`util-linux` package is required at `2.38.1-5+deb12u3`, unshare release `2.38.1`;
the image build checks it before/after parser installation and records its digest.
It never installs or upgrades that launcher. Missing/drifted packaging stops; actual
availability in the pinned image remains for coordinator verification.

Trusted single-thread bootstrap invokes only `unshare --user --map-current-user
--pid --net --ipc --fork --kill-child=KILL`, with no mount namespace, mount-proc,
root change or persistent namespaces. It verifies new user/network namespaces,
unchanged mount namespace and job PID1 identity using container self facts, then
requires Landlock ABI >=3, all ABI3 filesystem rights handled (REFER/TRUNCATE
included), zero capabilities and no-new-privileges. Immutable runtime/worker/library/
font reads and harmless device access are granted; only the exact generated job
directory is writable. The dynamic loader and two parser executables alone get
execute rights. `/proc`, `/sys`, `/run`, `/supervisor`, spool and sibling scratch
are not granted. Path metadata remains visible: no hidden-path or private proc
mount claim. Landlock is not silently optional.
Public source references are
[`unshare.c` v2.38.1](https://github.com/util-linux/util-linux/blob/v2.38.1/sys-utils/unshare.c)
(propagation changes are conditional on a mount namespace; none is requested) and
[Linux 6.8 Landlock documentation](https://www.kernel.org/doc/html/v6.8/userspace-api/landlock.html).
These are source evidence, not proof that the actual kernel enables Landlock.

Outer seccomp additionally admits only the three privilege-neutral Landlock
self-restriction syscalls. Its historical netlink allowance remains outer-only:
the child stacks an architecture-checked, inherited default-deny filter blocking
all socket/comms/FD-reception calls, mounts/namespaces/namespace-capable clone,
ptrace/FD-stealing, privilege changes and metadata mutations Landlock doesn't cover.
Supervisor passes a read-only descriptor for its owned anonymous spool; bootstrap
checks stdin access and pipe outputs and closes all descriptors above 2 before
parsing. Job PID1 teardown kills even double-fork/setsid descendants; launcher
parent-death, supervisor process-group kill/subreaping, whole-job exit and container
teardown remain backstops. Scratch cannot be reused after unproved reaping.

Independent **implemented-boundary** review is required before the coordinator
runs the same verifier command above. It now checks fixed image-resident probe
modes through the exact production bootstrap (no arbitrary code/path transport),
actual file read/write/metadata and socket denials, escaped-descendant cleanup,
then unchanged representative parser/channel workflow and deadline recovery.
No privileged, host-parser, unconfined or bwrap retry fallback exists.
Capability failures report only fixed `sandbox-<stage>-unavailable` categories;
no exception, namespace ID, policy name, input or host path escapes. Do not repeat
a denied setup with another reader or silently drop enforcement to reach parsing.

Coordinator's first mountless run built successfully and cleaned up, but stopped
at `sandbox-descriptors-unavailable` before parser execution. That old category
covered identity, no-new-privileges, standard-FD checks, limit setup **and** closing;
it does not establish a denied close syscall or a leaked descriptor. The follow-up
mechanical native-ABI correction explicitly types all five glibc `prctl` arguments
(variadic arguments are unsigned-long width) and `close_range`'s three arguments.
The seccomp program pointer is passed at full native width. Fixed stages now
distinguish `identity`, `no-new-privileges`, `stdin`, `outputs`, `limits` and
`close-fds`. Full `close_range(3, UINT_MAX, 0)` stays mandatory, with no fallback or
`/proc` enumeration; closing only to a lowered NOFILE limit could leave preexisting
high-numbered descriptors open. This is a glibc call, not CPython's absent
`os.close_range` API. Cause attribution and the corrected runtime remain unproved
until affected review and the coordinator's same verifier command.

The next coordinator result narrowed the startup failure to
`sandbox-stdin-unavailable`, again with build/cleanup passing. The exact startup
probe calls `run(..., source=None)`, which selected `subprocess.DEVNULL`;
[CPython 3.12.11 `Popen._get_devnull`](https://github.com/python/cpython/blob/v3.12.11/Lib/subprocess.py)
opens that descriptor **O_RDWR**, even for stdin. **Additional attempt 3/3** fixes
the shared runner default to open only `/dev/null` with `O_RDONLY | O_CLOEXEC`,
passing its explicit descriptor and closing the parent's copy after spawn, including
spawn failure. Production's already-read-only spool and supplied read-only pipes
stay unchanged. The bootstrap's read-only-stdin assertion is retained; there is no
writable-input exemption, alternate path or changed syscall policy. Missing default
input capability fails before launch. Original phase-one 5/5 and later phases 0/5
remain preserved; no further substantive attempt is available automatically.
The repair awaits affected independent review and coordinator runtime verification,
not another blind allowance change or a claim that containment now passes.

Historical bwrap diagnostic source basis is Debian bubblewrap **0.8.0-2+deb12u1**:
[`network.c::loopback_setup`](https://github.com/containers/bubblewrap/blob/v0.8.0/network.c)
uses exactly that socket to configure loopback. The public
[Debian source descriptor](https://deb.debian.org/debian/pool/main/b/bubblewrap/bubblewrap_0.8.0-2+deb12u1.dsc)
lists SHA-256 `957ad1149db9033db88e988b12bcebe349a445e1efc8a9b59ad2939a113d333a`
for the original source and `37917e8abdd6df1d1118f089e9cf1f9374e1b5bb21c8a70d7de4e9b5dfb10f6d`
for Debian patches. Both downloaded archives matched those hashes; the complete
patch series changes neither `network.c` nor `loopback_setup`. This was source-only
inspection without installation/execution, not independent signature verification
or proof of the built image; the coordinator still verifies build provenance.

## Operator-only chat-safety prototype (IMP-002)

### Ordinary foreground planning connection (IMP-005)

Base `compose.yaml` remains chat-off and has no host broker attachment. The
optional `compose.chat.yaml` enables only the API and mounts the retained channel
read-only with `create_host_path: false`. It does not launch a broker, acquire a
credential, enable synthetic inference or configure a provider. Independent boundary
review and the coordinator's owned synthetic ordinary-stack proof passed. This is
not real-provider or live acceptance; the owner deferred that test.

The human-only connection command, run from repository root in a plain terminal, is:

```sh
/usr/bin/python3 -I -B scripts/imp005_connection.py connect
```

Supply the exact public HTTPS:443 authority, supported Responses route, deployment,
and API-version (or literal `none`); none is guessed or discovered from installed
agents, host environment/config/auth, or files. The measured UID/GID1000 runtime,
owned runtime/channel and exclusive lock, DNS pin and CA/TLS setup are checked
**before** verified no-echo API-key input. A failure/non-TTY refuses setup. The key
is trusted foreground-process memory only, not an argument/env/file or API/worker/
browser/DB/log value. Python copies and host swap/dumps/debuggers remain risks;
this is not a secret-storage facility or an encoded/semantic-exfiltration guarantee.

Keep the launcher foreground. In a separate operator terminal, use the existing
local DB setup/project name and explicitly add the overlay (no provider key here):

```sh
IMPOSTR_CHAT_CHANNEL_DIR=/tmp/impostr-chat-1000/channel \
  docker compose -p impostr-local -f compose.yaml -f compose.chat.yaml up -d --wait
```

This is a local loopback setup, not deployment/runner authorization. The launcher
does not run Docker, migrations, fixture accounts or acceptance. Real-provider
compatibility/testing remains owner-deferred. There is no automatic background
service, persisted provider setting, host-auth reuse or reconnect credential cache.
Restart always requires fresh explicit terminal facts and no-echo human key input.

`Ctrl-C`, SIGTERM and SIGHUP disable the in-memory key and perform bounded owned
worker/socket cleanup. `/tmp/impostr-chat-1000/channel` remains the **same inode**
for the API's existing bind; its mode0700 sibling `private` contains only the
exclusive lock and ephemeral confined turn scratch, never mounted into the API.
Clean restart removes the lock, creates a new broker epoch and reconstructs from
DB history. Uncertain dispatch is visibly interrupted, never automatically retried.
On crash/SIGKILL/cleanup failure, stale lock/socket/scratch deliberately blocks
restart. Do not delete/adopt it automatically: the operator must first stop the
attached API and confirm the old launcher and all its workers are gone, then
inspect/remove only that owned runtime and recreate/rebind the API. Unknown or
foreign/symlink/writable state fails closed; no unsafe host fallback is provided.

Capacity is deliberately bounded: **248 new turns per foreground broker epoch**
(8 additional tombstones reserved for uncertain aborts), at most 8 concurrent turns
and one file-writing turn per project. At capacity the broker stays alive, existing
turns can drain, history/replay remain available, and new turn requests return 503.
Stop after draining and restart with fresh human input; don't retry an uncertain
turn. This is a practical session-capacity limitation, not transparent unlimited
service. Existing 12-prior-turn/context/output/time bounds remain unchanged.

The generated repository-owned `PLANNING_PROMPT` in `scripts/imp024_worker.py` is
the vetted agent source, not unrestricted installed `tech-lead` permissions. It
covers specification/AGENTS pair and backlog planning. Only canonical reads,
questions and once-permitted proposal edits are admitted; approvals/readiness
remain human/server-controlled. Normal API admission/dispatch accepts only explicit
`planning` broker mode. Synthetic/operator/unknown mode cannot start ordinary
account turns; test-only entrypoints use generated actor/project-ID scopes,
without a normal environment/config allow-synthetic switch.

Real transport now releases bounded literal-key-safe text prefixes before terminal
completion. It retains the longest suffix that could complete the literal key;
split/JSON-decoded key echoes fail closed, including emitted-tail matching across
model calls within a turn. The first safe delta is early; later tiny deltas coalesce
in roughly 1 KiB chunks within existing event/text budgets. Tool arguments/functions
and successful terminal frames stay withheld until full validated completion.
Late invalid output/error can leave honest partial safe chat text; it cannot
authorize failed-terminal proposals or make a partial reply successful. This is
not protection against arbitrary encodings or semantic disclosure by a provider.

**Coordinator-only synthetic verification (already passed; not a live-provider test):**

```sh
/usr/bin/python3 -I -B scripts/imp005_verify.py
```

The coordinator reported 94 focused tests, build/migration/API checks, Ruff, format,
and mypy passing, followed by joined restart/save-conflict/PostgreSQL-race/approval-
invalidation/uncertain-start-and-reply-no-repeat/revocation checks, broker/worker/
channel/DB outage checks, the ordinary frontdoor workflow, and all owned cleanup.
Independent boundary and affected-repair review passed. The verifier uses generated
inputs under `/tmp/opencode`, disposable Compose/DB resources, and controlled
synthetic transport through the early-text normalizer. It never invokes the public
operator entrypoint, real model or real accounts. Unit tests alone are not this
runtime acceptance. Historical browser
candidate fingerprints are unchanged past evidence, **not valid previews of this
new boundary**; no new UI/profile rebuild is required for unchanged delivered UI.

### IMP-024 phase three — verified synthetic UI/front-door acceptance

**Latest coordinator-verified outcome:** On exact base
`1121bb3314c7f298a16854f2f21ac084b13b44ae`, fresh 11 focused fixture tests and
`imp024-candidate-preflight` passed with fingerprint
`0cd9062476ec6b654acd2931702beeec97766d3dae289beac3d4ea3d179910fe`.
Exact-fingerprint launch passed using the approved canonical UID/GID1000 mode0775
synthetic Member handoff, without chmod or a wider private-state exception. No
runtime/profile inputs changed between preflight and rendered acceptance.

Normal generated Member sign-in and project creation passed. The rendered flow
completed a native question reply, Allow once and unapproved `PROJECT.md` import.
A second turn with a human save before Allow once retained the human text as a
proposal conflict and displayed its comparison. Composer drafts survived conversation
tab switches; refresh and re-login restored the server's last-used conversation.
An actual DOM MutationObserver observed `Synthetic planning` text while tech-lead
was still running, before completion, proving incremental rendered delivery through
the front door rather than merely a successful API/stream connection.

Independent candidate and affected repair reviews PASS remain valid. UI-designer
rendered review returned **PASS** at 1440/1024/768/375 px, with no horizontal overflow,
keyboard-focus checks and unsaved-text retention. Existing coordinator evidence of
92 web tests plus lint/format/typecheck/build remains valid for the unchanged web
inputs. Fixture `stop` returned **0**; sanitized cleanup status verified synthetic
Member accounts and removal of the login, owned stack/images, private state and
broker/worker/channel resources. These are coordinator execution results, not
developer Docker/browser runs.

Phase three uses **5/5** substantive attempts and is delivered. Phase four uses
**3/5**; phases one and two are delivered (phase two retained its historical 5/5
plus one focused 1/3 repair). The phase-four candidate's integrated synthetic proof,
human-only operator boundary and rendered approval/download workflow are now prepared
and verified as described below. IMP-024 preparation stops for a human's sanitized
result from the command at the end of this section; no agent runs it. This result does
not establish real-provider compatibility or complete IMP-002/005/006/008, enable
ordinary application chat, or satisfy first-release acceptance.

**Preserved earlier runner checkpoint:** 92 focused web tests and lint/format/typecheck/build
passed; fresh exact-input preflight passed migration0007, normal Member chat history,
authorization denials and all owned cleanup. Rendered launch stopped before handoff
because the approved channel failed its ownership/mode0700 gate. The owner subsequently
accepted the existing development directory's exact mode0775 for synthetic Member
handoff only, without chmod. At that checkpoint the fixture correction, affected
review and fresh preflight/rendered proof were outstanding; the latest verified
outcome above supersedes that blocker without erasing the failed launch. Earlier
fingerprints do not cover the corrected fixture/base.

Phase-three candidate uses delivered backend `a39a2f4` at exact committed base
`1121bb3314c7f298a16854f2f21ac084b13b44ae`. It adds durable conversation tabs,
per-tab drafts, explicit Send/Stop, Ctrl/Command+Enter, incremental DB replay,
inline questions/once-or-reject permissions and unapproved proposal/conflict links.
The stable project conversation panel is shared by planning, backlog and final review.
At <=768px switch Chat/Files/Backlog without discarding mounted text; final review
uses the region switcher so all three files retain full desktop width. Project list
collapses while a project is open. Existing revision checks and explicit conflict
compare/reapply remain authoritative; agent updates never approve a document.

The exact-base reconciliation from `4a4d820` to `1121bb3` verified that only
`BACKLOG.md` and `DONE.md` changed; all scoped runtime/build/test/helper bytes and
Git modes are identical. These bookkeeping paths and dirty coordinator planning/docs
remain outside the existing candidate status/archive scope. The full fixed inventory
is unchanged, including the added `scripts/test_imp024_browser_fixture.py` harness
input. The updated exact pin and handoff exception passed affected independent review
before the latest fresh preflight. Any later changed-input profile needs affected
review and fresh preflight; do not bypass the pin or reuse a stale fingerprint.

Unsaved composer/editor/task text is held only in browser memory, not localStorage
or cookies. Expiry unmounts private workspace/aborts streams; same-page re-login
restores drafts only after the server authenticates the **same user ID**. A different
account or explicit sign-out drops that memory. Refresh reloads saved history and
the server's last-used conversation, not unsaved browser text. Do not interpret
synthetic chat as live connection/account acceptance.

**Coordinator-only, after independent boundary/profile review:**

```sh
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp024_browser_fixture.py'
/usr/bin/python3 -I -B scripts/local_browser_fixture.py imp024-candidate-preflight
/usr/bin/python3 -I -B scripts/local_browser_fixture.py launch --handoff-dir /tmp/opencode/impostr-review-handoff --lifetime-minutes 30 --imp024-candidate-fingerprint <fresh-IMP024_CANDIDATE_FINGERPRINT>
# Normal generated Member sign-in/rendered review, then always:
/usr/bin/python3 -I -B scripts/local_browser_fixture.py stop --handoff-dir /tmp/opencode/impostr-review-handoff
```

The new `IMP024_CANDIDATE_PREVIEW_POLICY` is separate from older profiles. It pins
the actual base, exact modified web/Nginx inputs, test/harness bytes, full enumerated
API/build/migration/Compose/template inputs and delivered host helper inventory.
Unexpected scoped changes, missing inputs, unsafe files, token material, stale HEAD
or fingerprint drift fail closed.
Three committed lockfiles are root-owned mode0644 in this checkout; only their
read-only inventory accepts that owner, retaining nofollow/single-link/mode checks.
No dirty inputs or host helpers receive that exception. `compose.chat-synthetic.yaml` is
inventory only, **not** executed by this preview. The fixture prepares just one
read-only API bind of its random owned `/tmp/opencode/impostr-browser-chat-<run-id>`
directory to `/run/impostr-broker`, with `create_host_path: false`. No other service
may bind/enable chat. The original Compose safety checks still reject general host
attachments, external services and non-owned resources. No live activation/default
Compose changes, private configuration or model credentials are involved.

`imp024_browser.py` supervises the committed synthetic broker via an owned stdin
watchdog. EOF (also supervisor death), signals or lifetime expiry stop/reap only
owned children before channel removal; fixture success requires its zero exit and
removed channel. Cleanup failure retains the private snapshot and reports failure.
The guardian confines the delivered broker's fixed turn-tempfile call to a separate
owned mode0700 scratch sibling (never API-mounted), and removes that inode-pinned
scratch only after its adopted children are reaped, including forced shutdown.
It never certifies cleanup from component evidence. Existing Member revocation, stack,
volume/network/image ownership and handoff cleanup stay in place.

Coordinator web checks on the exact candidate: `npm run test -- src/chat.test.ts
src/ProjectChat.test.tsx src/ProjectWorkspace.test.tsx src/BacklogPlanning.test.tsx
src/FinalReview.test.tsx src/App.test.tsx`, then lint, format:check, typecheck and build
using the existing owned `web-check` environment. No host install is needed.
The earlier developer host `npm run typecheck` was unavailable (`tsc: not found`);
that attempt provided no web/rendered evidence. The coordinator results above are
separate successful checks. Run the web commands below inside that owned
environment, not against a live Compose stack or reusable account:

```sh
npm run test -- src/chat.test.ts src/ProjectChat.test.tsx src/ProjectWorkspace.test.tsx src/BacklogPlanning.test.tsx src/FinalReview.test.tsx src/App.test.tsx
npm run lint
npm run format:check
npm run typecheck
npm run build
```

Preflight alone is **not** browser/SSE acceptance. For future changed-input reviews,
fresh normal Member rendered proof must
cover new/last-used tabs, separate drafts, question and permission ACKs, Stop,
incremental delivery through Nginx (before completion), replay without duplicate text,
manual-save proposal conflict/compare/reapply, dirty editor/task/focus preservation,
final-review invalidation and 1440/1024/768/375 layouts. Expire/revoke the generated
session; verify private-state hiding/stream abort, same-user draft restoration and
different-user isolation. Confirm the dedicated stream location forwards auth/cursor
and unrelated API requests retain their ordinary timeout/buffering behavior. Always
verify owned broker/worker/channel plus normal fixture cleanup. The latest run's
rendered evidence is recorded above. The subsequent phase-four integrated synthetic
and rendered acceptance, and its pending human-only provider step, are recorded below.

### IMP-024 phase four — verified synthetic preparation; awaiting human outcome

The operator boundary and affected exact-input browser profile received independent
review **PASS**. On coordinator base `23e39ae`,
`/usr/bin/python3 -I -B scripts/imp024_verify.py --phase-four-only` passed build,
migration, Ruff, all four integrated workflow/recovery gates and owned cleanup. The
coordinator also passed `/usr/bin/python3 -I -B scripts/imp024_operator_verify.py`
in both normal and `--failure-after-pair` modes: actual frontdoor/helper acceptance
and expected native failure, respectively, with verified cleanup. A first lint run
failed on E501; the mechanical correction was made, and the passing verification run
cleaned its owned resources. Coordinator reran all 93 focused unit tests successfully.
Existing web 92 and responsive designer
reviews at 1440/1024/768/375 remain valid for unchanged inputs.

Fresh exact candidate preflight and launch passed fingerprint
`252bfcb41a5759e18f761b74d3c1abe4424e95a1df14e493bb0fa6acb4f6dd7e` on base
`23e39ae`. Normal generated-Member rendered acceptance completed specification
questions, two Allow-once edits, import, human pair approval, backlog import, human
TASK-001 readiness, final approval, and all three downloads matching the approved
manifest (PROJECT 1349 bytes, AGENTS 1288, BACKLOG 579). A subsequent agent revision
invalidated pair/final approvals and disabled all downloads; explicit human pair and
final reapproval restored all three downloads with matching digests (1399/1288/579
bytes). Fixture stop exited 0; sanitized cleanup verified accounts, login, stack,
images, private state and broker state removed. No credentials or live/operator mode
were used.

Phase four uses **3/5** attempts; phases one and three use **3/5** and **5/5** and
are delivered, while phase two's delivered history is 5/5 plus the additional 1/3
repair. Do not repeat unchanged gates or treat old checkpoints below as current.
Preparation is complete; only the human-only step remains. It is not a general app
activation, live compatibility claim, or completion of dependent chat/release tasks.

**Fresh integrated browser profile (affected review required before preflight):**
`IMP024_CANDIDATE_PREVIEW_POLICY` now pins committed HEAD
`23e39ae108c452f72c9acfe7815a44374aa0104a`. Delivered UI/Nginx files and browser guardian
are committed inventory; only dirty `scripts/imp024_broker.py` is overlaid/executed.
Exact dirty joined/member tests and phase-four operator/verification scripts/tests are
fingerprinted but never copied into or launched by the browser snapshot. Operator
transport, credentials and private resolver are not browser host-runtime inputs.
Strict unexpected-change, nofollow/owner/link/mode/size/token checks remain; neither
the read-only single-API bind nor the exact synthetic Member handoff is broadened.
Docs/task state/private logs/browser artifacts are outside this runtime scope.

Coordinator after affected profile/failure-scenario review:

```sh
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp024_*.py'
/usr/bin/python3 -I -B scripts/imp024_operator_verify.py --failure-after-pair
/usr/bin/python3 -I -B scripts/local_browser_fixture.py imp024-candidate-preflight
/usr/bin/python3 -I -B scripts/local_browser_fixture.py launch --handoff-dir /tmp/opencode/impostr-review-handoff --lifetime-minutes 30 --imp024-candidate-fingerprint <fresh-IMP024_CANDIDATE_FINGERPRINT>
# Normal generated Member sign-in and rendered integrated flow; always finish with:
/usr/bin/python3 -I -B scripts/local_browser_fixture.py stop --handoff-dir /tmp/opencode/impostr-review-handoff
```

The failure verifier injects a fixed credential-free native terminal error on the
backlog turn **after** real agent specification import and human pair approval.
It requires a visible failed turn, no backlog import/false completion, no final approval,
all downloads denied and owned teardown. Its coordinator PASS certifies expected
rejection and cleanup, never successful model acceptance.

**Coordinator rendered path, one newly created project/conversation:**

1. Normal generated Member sign-in; create a new project from untouched starters.
   Send exact prompt `Synthetic acceptance: specify Fieldnotes`. Answer Yes to the
   native question; Allow once for each of the two file edits. Wait for completed
   imports. Review saved PROJECT.md and AGENTS.md (both now fully valid); explicitly
   click **Approve saved PROJECT.md + AGENTS.md pair**. If a stale-pair comparison is
   shown, view both saved-version diffs and **I reviewed both latest documents** first.
2. Send `Synthetic acceptance: plan Fieldnotes backlog`; answer Yes and Allow once.
   Open BACKLOG.md/task rail and verify TASK-001/TASK-002 both start draft. Read task
   scope/acceptance/verification, explicitly mark TASK-001 ready using its human
   on-row readiness control; TASK-002 stays draft with its TASK-001 dependency. Do not send a
   readiness prompt as a substitute for that human action.
3. Open **Final review and downloads**, inspect all three saved files, revision IDs
   and readiness summary; click **Approve displayed three-file snapshot**. Use each
   rendered **Download PROJECT.md**, **Download AGENTS.md**, **Download BACKLOG.md**
   button. Compare actual download UTF-8 bytes/digests with the current approved
   manifest/reviewed saved contents through authenticated requests for this same
   project. Each manifest reference must match that displayed saved revision.
4. For rendered invalidation/reapproval in this same project, send
   `Synthetic acceptance: revise Fieldnotes specification`, Yes/Allow once. Both
   pair/final approvals and all downloads must become unavailable. Review/approve
   the new pair, then exact three-file snapshot, and repeat all three downloads.
   Optional backlog-only spot-check: `Synthetic acceptance: extend Fieldnotes backlog`
   adds TASK-003 draft, preserves TASK-001 ready, keeps pair approval but invalidates
   final approval; explicitly reapprove the new snapshot before downloads.

Exact spelling selects deterministic synthetic tool DATA only; ordinary prompts keep
the delivered append-only fixture. Do not substitute operator/live inference or reuse
the historical phase-three fingerprint. Any further fingerprinted file changes require
fresh reconciliation/preflight. Always verify stop/account/login/stack/images/private
state/broker/worker/channel cleanup before delivery.

One implemented **human-only** command from checkout root, in a real plain terminal:

```sh
/usr/bin/python3 -I -B scripts/imp024_operator.py setup-accept
```

Do not run this through agent tools or supply secret arguments, environment exports,
files or redirected input. The command asks for the exact HTTPS authority (no path,
public port443), exact `/openai/v1/responses` or
`/openai/deployments/<deployment>/responses` route, exact `api-version` or literal
`none`, and exact deployment. The deployment-bearing route must match that deployment.
No account values or version defaults are guessed; unsupported routes/auth stop.
Only literal API-key authentication with direct pinned public-address TLS443 and the
fixed system CA file is supported—not OAuth, bearer tokens, arbitrary routes, proxy,
private network endpoints, host config discovery, the parked resolver or plugin loader.
DNS and TLS preparation happen before credential acquisition.

A credential-free child, launched before key input with a clean environment and
closed descriptors, owns a random disposable Compose stack, loopback frontdoor port,
generated DB inputs and generated Member. The parent asks for explicit `ACCEPT`, then
reads the key only after verifying terminal echo disabled; no getpass fallback exists.
The trusted foreground parent alone holds the key and injects its transport into the
broker. Post-key worker launches use the delivered clean-exec/bwrap boundary; provider
key and host transport are not in worker code, arguments, environment, DB or browser.
The already-running credential-free helper performs Docker work; no orchestration
process is created from the credential-bearing parent after key input.

Acceptance uses normal Member sign-in through the actual loopback Nginx/frontdoor,
API, PostgreSQL, private broker and bwrap worker. The **real model**, not deterministic
inference, must read/ask/edit and import exact synthetic PROJECT/AGENTS and backlog,
leave tasks draft, accept explicit human readiness and pair/final approval actions,
produce all three byte/digest-identical downloads, reconnect to durable SSE, and
complete a new specification turn that invalidates both approvals before exact
reapproval/download. Wrong bytes, unsupported native event shapes, tool errors,
timeout or missing interactions fail—there is no ping-only acceptance or model fallback.
These helper-driven human actions are restricted to disposable synthetic acceptance,
not autonomous approval of real projects. Previously verified restart/concurrency/
revocation and rendered UI evidence is reused, not claimed as new live proof.

Planning Responses normalization retains existing canonical function/argument and
time/output bounds (4096 output tokens maximum). It holds a bounded inference response
until complete validation and literal credential-contamination checks finish, including
text, accumulated argument chunks, decoded arguments and call IDs. This fails closed
rather than exposing an echoed key; it cannot promise detection of arbitrary transformed
secrets. The complete bounded response is validated before release, so live early text
deltas are not provided; real-provider compatibility remains unknown until human use.
Provider errors/IDs/headers are never forwarded; incomplete/error responses cannot
be successful tools or completion. Worker model alias stays fixed and nonsecret.

Success retains only this foreground disposable connection until Ctrl-C, not a saved
configuration or enable flag. The generated Member remains helper-private; this command
does not provide an owner-account/browser activation channel. Failure/stop clears the
transport key, stops/reaps owned workers, asks the helper to remove accounts/projects,
stack/volumes/images/channel/generated inputs and verifies cleanup. Share only the fixed
sanitized result. SIGKILL, host/daemon loss or denied cleanup may leave disposable
resources; a cleanup failure is never a passing result. Python memory copies, host
swap/dumps/debuggers and accepted local synthetic scratch group-tampering risk remain;
memory-only is not a confidentiality guarantee against the host.

Pure synthetic checks (no operator/private/provider/network/Docker execution):
`/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp024_operator.py'`.
The **coordinator-only**
`/usr/bin/python3 -I -B scripts/imp024_operator_verify.py` proves the new helper's
fresh build/migration/generated-Member/frontdoor acceptance and owned cleanup using
only an exact deterministic synthetic transport. It never calls the human entrypoint,
key reader or HTTPS inference. Coordinator actual execution passed as recorded above;
the developer did not run Docker. The `--failure-after-pair` variant separately proves
failed-acceptance rejection and cleanup. The remaining human-only step is the command
above: it supports only explicit public HTTPS:443 Responses and API-key authentication,
with no guessed endpoint, deployment, API version or credentials. Non-interactive input
or inability to disable terminal echo fails closed. The secret exists in trusted process
memory; memory-only does not protect against host swap/dumps or other memory copies.
After local verified commits, stop and await only a sanitized human outcome; no agent
runs `setup-accept`.

### IMP-024 phase two — verified synthetic backend acceptance

**Latest coordinator-verified outcome (2026-10-01):** From checkout root,
`/usr/bin/python3 -I -B scripts/imp024_verify.py` returned PASS on the preserved
candidate at base HEAD `0e94e09`, disposable project `imp024-verify-4af45777168e`.
Build/database setup, migration `20261001_0007`, focused pytest, Ruff lint/format
and mypy passed, followed by all **seven joined checks**, **three lifecycle checks**
and **every owned cleanup stage**. This proves the authenticated Member/API/DB/broker/
confined-worker path through real post-restart poll ACK, native question reply and
permission, concurrent human save/import and provenance/approval invalidation,
active revocation, uncertain start/reply crashes without duplicates, and actual
broker/worker restart plus channel/DB outage recovery without false imports.
These are coordinator execution results, not developer Docker runs. Substantive
repair and orchestration review passed. Additional repair budget used **1/3**;
mechanical harness/environment/lint corrections do not add substantive attempts.
Historical phase-two **5/5** and delivered phase-one **3/5** remain preserved.

This outcome supersedes the exhausted stop/missing backend acceptance statements
below; they are retained as historical evidence. The earlier permission timeout's
causal root cause was **not isolated**: inspection established the incompatible
8-second product SSE idle bound versus a retained 20-second pump lease and stale
`running`/HTTP202 recovery assumptions, and the corrected combined flow now passes,
but no controlled runtime experiment attributes the old failure to one cause.
No further backend changes are needed for these proved gates. Coordinator owns
phase-two commit/task bookkeeping. IMP-024 as a whole is **not complete**: phases
three/four remain **0/5**, frontend/live acceptance is absent, and no operator/live
mode or runner was started. Phase three must reconcile its actual candidate profile
against the **new committed phase-two base**, then obtain fresh exact-input preflight
and authenticated rendered evidence; older UI fingerprints are not reusable.

**Reviewed coordinator-only orchestration support:** From the
checkout root, `/usr/bin/python3 -I -B scripts/imp024_verify.py` prepares a random
owned Compose project/channel and a mode0600 generated synthetic env file under
the verified `/tmp/opencode` parent. It does not inspect checkout `.env` or host
private inputs. This approved owner/group1000 synthetic scratch parent may be
group-writable (observed mode0775); it is not a credential-reader ancestor. The
helper never chmods it. Exclusively created children use mode0700 for generated
inputs and mode0711 for the broker channel required by API UID10001 traversal.
Nofollow directory descriptors retain each inode, generated env creation uses the
private input descriptor, and pathname/inode checks before subprocesses and removal
reject a replaced path. These checks are not complete protection against an active
host process sharing the writable group racing Docker/broker pathname resolution;
use remains confined to the accepted local synthetic scratch contract, never real
provider credentials or a private-auth/config safety tree. It does not inspect host
configuration; the Docker client receives a disposable HOME and fixed local Unix
daemon, not ambient endpoint/proxy/auth settings. No secret values enter arguments
or output. It builds the documented images, migrates an empty owned DB, runs focused
API/static checks and joined `check`, then drives `lifecycle` with piped `-i` stdin
(no TTY). Only the five exact existing prompts select fixed broker/db actions;
database restoration waits for Compose health before sending Enter.

Focused pytest, Ruff lint, Ruff format and mypy now run as individually labeled
gates (same commands/scope, no weakened checks); failures expose fixed categories
and, for Ruff only, assigned allowlisted relative filenames/rule codes/line numbers,
never arbitrary paths, assertions, error messages, source snippets or fix contents.
Lint runs once with `ruff check --output-format json`; its separately bounded stdout
is strictly projected before the nonzero exit remains a failed gate. Format diagnostics
can name only the same fixed assigned paths. Cleanup reports each fixed stage,
activates both check profiles for image removal, and requires inventory **stdout**
empty plus command exit0. Bounded stderr warnings are discarded separately; they
are not evidence of leaked resources. Any failing cleanup stage still fails the
whole helper and does not prevent later independent cleanup stages being attempted.

The helper reports fixed check statuses, allowlisted failure categories and
reconstructed safe diagnostic counts/states. Raw build/DB/CLI/assertion/JSON output
is bounded in memory and discarded, never saved or forwarded. Its `finally` removes
explicitly named check containers, stops its own broker, reaps detached owned
descendants using Linux subreaper/pidfds (excluding the active lifecycle CLI), runs
owned Compose `down -v --remove-orphans --rmi local`, verifies label-scoped resources
and project images absent, and removes only its empty channel/generated input
directory. Cleanup failure returns nonzero with the nonsecret resource label; it
does not erase stale channel contents or claim acceptance. SIGTERM/ordinary failures
enter cleanup; SIGKILL, daemon/host loss or denied cleanup cannot guarantee it.
Generated disposable DB passwords exist in the private fixture env and Docker
container configuration until cleanup, never product workers. Do not run this
helper as a developer, operator/live connector or automatic runner launcher.

**Verified focused interactive repair, attempt one of three additional attempts:** The
preserved joined failure is not yet explained by runtime evidence. Code inspection
does establish that SIGKILL leaves the committed 20-second pump lease, while the
product worker inherited an 8-second native SSE idle timeout. Product SSE reads now
use the **remaining original driver lifetime**, not a fresh/replenished timeout;
the existing main-loop deadline, abort/cleanup and broker lifetime remain unchanged.
Phase-one SSE defaults remain eight seconds. No lease is stolen or shortened.

The joined restart check now requires a real post-restart native poll ACK instead
of accepting the retained `running` DB row as recovery. It verifies question reply
ACK/durable `replied` before proceeding to permission; HTTP202 alone is still queue
acceptance. Failed workers can publish only fixed allowlisted reason categories,
retained with the durable failure event. On assertion failure, the fixture prints
a bounded turn summary before cleanup: states, dispatch flags, lease remaining,
cursor, operation-stage counts/poll gap and fixed failure categories, never IDs,
cookies, DB settings, text, raw channel data or exception details. Summary failure
does not replace the original failed check. Joined acceptance passed as recorded
above; the historical failure's actual cause remains unisolated.

Coordinator setup/lifecycle/cleanup commands below remain the existing disposable
fixture contract. For this candidate, replace the focused check-container command
with (all other Compose arguments/setup steps unchanged):

```sh
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-check sh -c 'python -m pytest -p no:cacheprovider tests/test_chat.py && ruff check app/chat_protocol.py app/chat_state.py app/chat_dispatch.py tests/imp024_joined.py tests/test_chat.py && ruff format --check app/chat_protocol.py app/chat_state.py app/chat_dispatch.py tests/imp024_joined.py tests/test_chat.py && mypy app'
```

**Historical exhausted phase-two checkpoint (2026-10-01, candidate HEAD `1bf79bd`; superseded above):** Phase two
used all **5/5** authorized attempts; preserve its uncommitted candidate, but it was
not delivered. Phase one remains delivered at **3/5** attempts and is not reopened;
phases three and four remain **0/5**. The coordinator's final fresh joined run
passed fresh Docker builds, migration `20261001_0007`, 15 focused `test_chat`
tests, and Ruff check/format for the two harness files. The joined run progressed
through normal Member authentication, conversation creation, native question/reply,
and API-process restart, then failed with `Timed out: native pending permission`
in `normal_restart_and_concurrency`. The cause is not established; do not claim
joined acceptance or infer why it timed out. Lifecycle/revocation/save-import
concurrency gates were not reached and remain unproved. The coordinator reported
owned API/account/project cleanup through `finally` without secondary errors, then
broker SIGTERM/exit, Compose volume/network/image removal, and fixture-directory/
environment removal completed without error. Both final repairs (persistent broker
directory handling and standard-library HTTP client) received selective reviewer
PASS; these and the component checks do not change the failed joined result.

No phase-two task delivery or new operator run was authorized by that checkpoint.
The reproduction/setup instructions below are retained as maintainer context only,
not a request to run commands. Any continuation requires renewed owner scope and
budget. No live activation is established.

**Attempt-four continuation (not acceptance):** Preserves the candidate and all
prior component evidence. `api/tests/imp024_joined.py` now supplies coordinator-only
`check` and interactive `lifecycle` modes. They run a real loopback HTTP API child
inside the UID10001 check container, normal Member login, PostgreSQL transactions,
the real Unix broker and confined workers. Test-only file gates pause outside DB
transactions around real channel ACKs; no test auth route or fabricated response.
The checks cover known API restart, uncertain start/reply crashes, real save/import
content retention/provenance, matching-head import and approval invalidation,
active HTTP stream/queued-reply revocation and revocation before completed import.
Lifecycle mode asks the coordinator to stop/restart only its owned broker and DB.
It checks safe interruption after broker/worker replacement and channel/DB outages;
it does not promise native-session restoration after losing the broker epoch.

Concrete fixture repair: Docker binds a directory inode. Previously a clean broker
restart deleted/recreated that directory, leaving existing API mounts disconnected.
The explicit synthetic `--persistent-directory` option retains the empty owned
mount directory. Reuse requires exact UID/GID1000, mode0711, no symlink or contents;
stale sockets fail closed. Default broker cleanup is unchanged. This is not live
activation or authorization to remove arbitrary stale paths. This records the
attempt-four checkpoint; the final review and joined-run outcome are stated above.
Developer pure checks passed 43 IMP-024, 21 IMP-023 and 51 IMP-002 tests; the harness
passes the available Black parser/format check. Host FastAPI/SQLAlchemy/Ruff are
unavailable; no Docker, joined harness, operator or live mode was executed here.

**Attempt-five dependency repair:** Coordinator reported fresh builds/migration0007,
15 focused chat tests, Ruff lint/format and affected review passing, but the joined
entrypoint failed at `import httpx`. The lock provisions `httpx2`, not that module.
`api/tests/imp024_http.py` replaces the undeclared import with standard-library
HTTPConnection/CookieJar: persistent normal login, synchronized cookie updates,
independent concurrent connections, incremental UTF-8/chunked SSE, bounded reads/
timeouts, no environment proxy, redirects or mutation retries. In-memory HTTP wire
regressions run without listeners, API/DB dependencies or worker execution. No
dependency installation/lock edits. Phase two is now **5/5 used, zero remaining**;
the four-attempt paragraph above is the preserved prior checkpoint. Affected review
of the new client/harness import change must precede coordinator rerun. No joined
acceptance is claimed by this repair alone. The subsequent joined-run outcome is
stated above. API request/reply, document-write and pair/final-approval fields were checked
against the existing schemas and required no contract changes.
Developer check: `/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp024_*.py'`
passed **47 tests**, including four standard-library HTTP/cookie/concurrency/stream
regressions. The new client passes available Black100 formatting; the harness keeps
the already coordinator-verified Ruff-specific assertion formatting. Ruff and the
actual joined modes remain coordinator checks, not developer execution results.

Historical reproduction instructions: after independent review, use a **fresh empty owned DB** and a new broker directory,
with existing coordinator-generated disposable env settings (never checkout `.env`),
`IMPOSTR_SYNTHETIC_BROKER_DIR=/tmp/opencode/imp024-phase2-joined`, `APP_PORT=8080` and
`IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080`. Verify `/tmp/opencode` first. Broker
foreground terminal command, also used at each lifecycle restart:

```sh
/usr/bin/python3 -I -B scripts/imp024_broker.py synthetic --directory /tmp/opencode/imp024-phase2-joined --persistent-directory
```

Coordinator-only setup/check commands (`<synthetic-env>` is the existing generated
fixture path; every Compose invocation must retain it). No frontdoor/API service
is needed: the joined harness owns the API process inside the check container.

```sh
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml build db api api-check api-integration-check
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml up -d db
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml run --rm api alembic upgrade head
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-check sh -c 'python -m pytest -p no:cacheprovider tests/test_chat.py && ruff check tests/imp024_joined.py tests/imp024_http.py && ruff format --check tests/imp024_joined.py tests/imp024_http.py'
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-integration-check python -B tests/imp024_joined.py check
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml run --rm -it api-integration-check python -B tests/imp024_joined.py lifecycle
```

Lifecycle broker actions: Ctrl-C/SIGTERM the owned foreground broker, wait for exit,
then use the same foreground command. Keep its mount directory/inode. At the DB
prompts, in another coordinator terminal use these exact owned-stack actions:

```sh
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml stop db
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml start db
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml ps
```

Each mode refuses a nonempty users table, stops its API child, aborts scoped workers
before deleting its own projects/account, and removes temporary gates/operation-only
journal on success. Failure returns nonzero, never prints raw DB exceptions. If DB/
broker is left unavailable at failure, cleanup cannot be certified: restore only the
owned capability and tear down the disposable stack/broker; do not use a live DB.
Final cleanup (also after failed gates): stop the foreground broker, confirm its exit
and worker descendants/listeners gone; then:

```sh
docker compose --env-file <synthetic-env> -p imp024-phase2-joined -f compose.yaml -f compose.chat-synthetic.yaml down -v --remove-orphans --rmi local
rmdir /tmp/opencode/imp024-phase2-joined
```

`rmdir` intentionally refuses nonempty/stale paths. Verify no owned containers,
volume/network, API child, worker descendants or channel listener remains; remove
only the coordinator-generated fixture env inputs. Successful component commands
below remain useful history, not a substitute for these still-unrun joined gates.

The phase-two candidate adds authenticated chat persistence and a **synthetic-only**
host broker. Default Compose has no channel mount and chat stays disabled. Only the
explicit `compose.chat-synthetic.yaml` disposable coordinator overlay enables it;
this is not a live-provider setup or a public auth bypass. Review the new broker,
product worker adapter, API transactions and migration before any new boundary run.
Phase-one code/pins/tools are reused; there is no provider credential in the API,
worker, database or browser and no general HTTP/OpenCode proxy.

Protocol: fixed length-prefixed JSON `hello/start/poll/reply/abort` over one Unix
socket. Host peer UID1000 is checked by the API; only API peer UID10001 is accepted
by the host. The exact owned directory is mounted read-only into API/check only.
The socket is mode 0666 because the container does not share the host group;
`SO_PEERCRED`, not mode bits or an opaque project ID, authenticates callers.
This authenticates an OS identity, not every process of that UID: do not reuse
UID10001 for untrusted host processes. The broker never enters a worker mount.

PostgreSQL records conversations, per-user last tab, idempotent turns, ordered
events, pending/replied interactions, project reservations and agent provenance.
A short committed pump lease is intended to coordinate API processes; inference/channel
calls are placed outside DB transactions. The implementation replays committed events,
interrupts unknown dispatch/reply rather than retrying, and attempts same-epoch known
running-turn recovery. Actual combined API/broker/worker restart acceptance remains
pending; the passing mock recovery checks are not full-process proof. A new
turn explicitly reconstructs bounded durable text/interaction/tool-state context
in a new native session, not assumed native SSE replay. It does not restore an
unvalidated OpenCode database or silently truncate history. Concurrent document
head changes retain generated text as conflict proposals. Matching heads get
immutable `agent` revisions, invalidating prior approval tuples; humans alone may
approve them or change task readiness. New tasks must remain draft.

Practical ceilings: 32 tabs/project, at most 12 prior turns (24 reconstructed
history entries), 64 KiB per document and per raw/JSON-escaped user message or
assistant turn text (both byte limits apply),
384 KiB reconstructed context including native JSON escaping, 512 KiB aggregate
dispatch frame/event buffer, 256 ordered events,
eight inference calls, eight concurrent host turns with one writer/project,
60-second worker lifetime and bounded channel I/O. The aggregate byte limit may
reject a large history before 12 prior turns: the turn-count limit is not a promise
that 12 maximum-sized turns fit. A 64 KiB first ASCII message can continue with its
full 64 KiB assistant text and framing; over-limit escaped context or a complete
start envelope is rejected **before durable queued acceptance**, never clipped.
Only product reconstructed input uses the larger cap; tool arguments/results and
phase-one/prototype input/output defaults stay bounded as before. Native inference
requests retain the independent 512 KiB cap and may fail closed if later tool
results exceed it. Existing API documents can reach 128 KiB; those above
the worker's measured 64 KiB ceiling cannot be dispatched in this candidate.
Broker tombstones are capped at 256 turns; a full broker restart changes epoch
and interrupts unknown work. These are explicit candidate limits, not aggregate
resource containment. Migration downgrade refuses to erase agent-origin history.

**Final reported coordinator evidence (2026-10-01):** Focused API/migration/pair/final
manifest checks passed **327 tests**; Ruff passed, format checked **36 files**, and
mypy checked **32 source files**. Fresh owned PostgreSQL upgrade/current reached
`20261001_0007`; both chat PostgreSQL tests passed. Those two tests prove preservation
of preexisting identity/document bytes through migration and concurrent submission
idempotency/project reservations/pump-claim exclusion. They do **not** exercise a
human-save versus agent-import race. The five actual Unix-channel tests passed:
normal, CRLF-only, large LF-context, combined CRLF/large-context native planning,
and unknown-abort tombstone denial of delayed dispatch. Each planning case exercised
native read/question/reply/edit permission, ordered events and unapproved proposal
capture, including duplicate-start and forged epoch/project denial. The separate
host UID1000 peer probe confirmed host caller denial; the API client checks the host
UID1000 peer and actual calls run as API UID10001. Earlier pure regression checks
passed 41 IMP-024, 21 IMP-023 and 51 affected IMP-002 tests. These are coordinator
reported execution results plus preserved developer pure checks, not new executions
performed by this documentation assessment.

**Historical missing acceptance (now proved by the latest joined/lifecycle outcome above):** BACKLOG.md phase two explicitly requires durable
full restart/outage recovery and fresh PostgreSQL concurrency, not only passing
component checks. The joined attempt failed before these gates:

- Exercise the actual authenticated API -> PostgreSQL dispatcher -> Unix broker ->
  confined worker -> durable event/interaction/proposal path. The channel test calls
  `UnixBroker` directly with generated IDs; it bypasses API turns, reservations,
  initiating-session authorization and database delivery/import. Demonstrate a
  committed turn dispatch once, incremental events persisted before API replay,
  normal native reply and revision-bound import/approval invalidation on that path.
- Race a real PostgreSQL human document save against completion/import. Show both
  texts retained, correct imported-head versus conflict outcome, captured/observed
  provenance and approval invalidation; show the human save is not blocked behind
  inference. The existing sequential fake-broker conflict test and submission race
  do not prove the changed import transaction under concurrent head updates.
- Restart actual API, broker and worker state during an active/pending turn using
  the same durable DB. Verify known same-epoch replay versus unknown interruption,
  no second start/reply, preserved history/last tab and bounded reservation recovery.
  Include a representative unavailable broker/channel and DB outage/recovery with
  no false completion/import and no duplicate dispatch after restoration. Existing
  tests replace the dispatcher or fake epoch/unknown response; they do not kill or
  restart these product processes.
- Verify revocation while the actual product stream/interaction is active: no later
  reply dispatch or proposal import from a revoked session, stream stops and stale
  reply is denied. Current API checks validate these controls against a fake broker
  and invoke the stream generator directly; retain that useful evidence, but join
  it to the actual product path rather than treating standalone UID proof as session
  authorization proof. Front-door streaming/rendered UI is phase three, not this gate.
- Record owned broker/worker/listener/stack cleanup. Individual channel tests confirm
  turn stop. The final coordinator cleanup reported above completed; this does not
  prove lifecycle acceptance.

At that historical checkpoint phase two remained blocked, with all **5/5** attempts consumed. Preserve this candidate
as an acceptance checkpoint, not a delivered phase or new implementation
authorization. Any further work requires renewed bounded authorization. No generic
full suite, coverage target, UI/operator work, live activation or aggregate quota
prerequisite is added by this checkpoint.

**Reproduction commands for the reported component checks:** Use a new owned
Compose project/volume and existing synthetic fixture provisioning only. Do not use
this checkout's `.env`, owner accounts, live DB or reusable secrets. Supply
`--env-file` pointing to coordinator-generated disposable settings on **every**
Compose call (no raw config/log rendering). After independent review, create the
broker with this foreground command in an owned plain process; the directory must
not already exist:

```sh
/usr/bin/python3 -I -B scripts/imp024_broker.py synthetic --directory /tmp/opencode/imp024-phase2-channel
```

The actual UID-channel test includes separate CRLF-only and large LF-context cases,
plus their combined case. The initial combined run failed; a pure regression found
the inherited SSE reader rejected the native 131 KiB reconstructed-prompt echo at
its 8 KiB line ceiling, before non-tool projection could discard it. Product-only
framing now permits up to the unchanged 512 KiB stream ceiling; phase-one parser
defaults and projected delta/tool limits remain unchanged. Following affected review,
the coordinator's final actual channel rerun passed all five tests, including the
combined case. That corrects the component failure, not the missing combined
API/PostgreSQL recovery/concurrency evidence above.
The disposable env file must set `IMPOSTR_SYNTHETIC_BROKER_DIR` to that exact
directory in addition to ordinary generated fixture DB settings. With
`<synthetic-env>` replaced by its coordinator-owned path:

```sh
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml build db api api-check api-integration-check
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml up -d db
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml run --rm api alembic upgrade head
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml run --rm api alembic current
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-check sh -c 'python -m pytest -p no:cacheprovider tests/test_chat.py tests/test_migrations.py tests/test_document_pair_approvals.py tests/test_project_approval_manifests.py && ruff check app tests/test_chat*.py migrations/versions/20261001_0007_durable_chat.py && ruff format --check app tests/test_chat*.py migrations/versions/20261001_0007_durable_chat.py && mypy app'
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-integration-check python -m pytest -p no:cacheprovider tests/test_chat_postgres.py
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml run --rm api-integration-check python -m pytest -p no:cacheprovider tests/test_chat_channel.py
/usr/bin/python3 -I -B scripts/imp024_peer_probe.py --directory /tmp/opencode/imp024-phase2-channel
docker compose --env-file <synthetic-env> -p imp024-phase2 -f compose.yaml -f compose.chat-synthetic.yaml down -v --remove-orphans
```

Stop the owned broker with SIGTERM/foreground Ctrl-C, then verify its owned directory
and descendants/listeners are gone and remove only generated fixture inputs. Component
UID and migration/submission tests are now verified; the commands above alone do not
cover the remaining integrated acceptance scenarios listed in this checkpoint.
UI/front-door and private operator activation remain phases three/four, not delivered
by these commands. No agent runs operator/live modes.

### Existing IMP-002 prototype instructions

The default prototype modes are synthetic; a continuation now prepares an
operator-only live transport, **independently reviewed, not live-verified**.
There is no app gateway. Do not put real credentials/project data into it. It requires
this host's measured UID/GID 1000:1000 and pinned bwrap 0.6.1/OpenCode 1.18.34/runtime digests;
changed binaries fail closed, rather than falling back to the host. `/tmp/opencode`
must already exist as the permitted scratch parent. From the repository root:

```sh
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp002_*.py'
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic-stream
/usr/bin/python3 -I -B scripts/imp002_prototype.py probes
/usr/bin/python3 -I -B scripts/imp002_prototype.py outage
/usr/bin/python3 -I -B scripts/imp002_prototype.py timeout
```

Prior independently verified checkpoint: 9 tests and the original four modes passed,
including synthetic file/socket/network denials, clean environment,
read-only runtime/config/discovery, native Responses
stub decoding, fail-closed relay outage, timeout/descendant pipe EOF and owned-state
removal. Reports contain synthetic protocol shape/digests, not live credentials.
Independent review approved only this synthetic scope. The owner defers aggregate
resource quotas and accepts host disruption risk; time/output/relay bounds do not
prove aggregate containment. The continuation removes relay/shim buffering and
normalizes bounded native Responses SSE into text-only events. Continuation checks
passed 22 focused unit tests and all five synthetic launcher modes; socketpair tests
proved incremental relay-to-shim delivery before completion and upstream cancellation
on caller disconnect. Coordinator repeated the suite and all five modes; independent
review approved the operator steps after rejecting provider-level endpoint overrides.
Full session/proposal
behavior remains unproved. These commands do not make the runner or product chat ready.

### Confined synthetic session proof (IMP-023)

The non-serving synthetic session harness has now passed actual scenarios against the
pinned OpenCode server inside the bwrap worker. From the repository root, the focused
commands verified were:

```sh
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp023_*.py'
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp002_*.py'
/usr/bin/python3 -I -B scripts/imp023_session.py startup
/usr/bin/python3 -I -B scripts/imp023_session.py history
/usr/bin/python3 -I -B scripts/imp023_session.py reconnect
/usr/bin/python3 -I -B scripts/imp023_session.py interrupt
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic
/usr/bin/python3 -I -B scripts/imp002_prototype.py probes
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic-stream
/usr/bin/python3 -I -B scripts/imp002_prototype.py outage
/usr/bin/python3 -I -B scripts/imp002_prototype.py timeout
```

The IMP-023 tests passed 21 tests; the affected IMP-002 tests passed 51. All four
session scenarios and all five existing prototype modes completed successfully.
Startup verified authenticated health/version 1.18.34, unauthenticated 401 denial,
`server.connected`, and session creation/read. History verified a text delta before
completion, distinct sessions, prior-turn context, and no history in a fresh session.
Reconnect recovered history/status without resubmitting; restarting the server inside
the same worker retained history and allowed continuation. Interrupt verified abort
cancellation; a bounded inference failure remained a terminal failure, not successful
completion. Synthetic containment and owned cleanup checks passed for file, socket,
network and configuration injection, child/listener/fixture/state cleanup. The host
relay remains inference-only, with observed call counts 0/3/2/2 for startup/history/
reconnect/interrupt and the existing four-call ceiling unchanged.

This proves only generated namespace-local authentication, disabled mDNS and no host
ingress for this synthetic harness. It does not prove SSE replay or durability after a
full worker restart. Aggregate resource quotas remain deferred. No private inputs,
operator modes or live model operation were used; this is not actual-model, product
chat, tool/question/proposal, or release acceptance. The separate IMP-024 phase-one
synthetic planning proof below adds native planning interactions, but does not change
this IMP-023 or IMP-002 outcome.

### Synthetic planning interactions (IMP-024 phase one)

After independent initial boundary review and affected reviews of the native-permission
and abort/pending-question repairs passed, the bounded phase-one harness passed its
focused tests and actual synthetic scenarios. From the repository root, these commands
were verified:

```sh
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp024_*.py'
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp023_*.py'
/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp002_*.py'
/usr/bin/python3 -I -B scripts/imp024_session.py planning
/usr/bin/python3 -I -B scripts/imp024_session.py denials
/usr/bin/python3 -I -B scripts/imp024_session.py cancel
/usr/bin/python3 -I -B scripts/imp024_session.py error
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic
/usr/bin/python3 -I -B scripts/imp002_prototype.py probes
/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic-stream
/usr/bin/python3 -I -B scripts/imp002_prototype.py outage
/usr/bin/python3 -I -B scripts/imp002_prototype.py timeout
```

The focused suites passed 29 (IMP-024), 21 (IMP-023), and 51 (affected IMP-002)
tests. Each of the four IMP-024 scenarios and five existing IMP-002 modes reported
success with owned cleanup true. In the synthetic planning scenario, pinned OpenCode
used native read/question/edit functions, a pending question was replied to, an edit
permission was asked and granted once, always-denied tools stayed denied, and the
resulting canonical-file change was captured as an unapproved proposal. A malicious
shell function was rejected before worker execution. Abort cleared a pending question
and a stale reply was denied; a partial delta followed by terminal error was not
reported as success.

This is generated-data proof only, not a product broker/API/UI, live model or operator
entrypoint. It does not provide a worker-restart durability guarantee, authoritative
database-backed proposals, or full product chat. Practical protocol limits include
64 KiB per canonical document, 512 KiB request/response, eight relay calls and eight
questions; the harness also bounds a run and its output. Aggregate memory/CPU/process
quota work is owner-cancelled for personal text chat and containment is unproved
(the reused harness labels this owner-deferred); these practical bounds do not establish
aggregate containment. IMP-024 remains in progress: its next phase covers a broker,
Unix UID/authentication, durable database state, and proposals. IMP-002/005/006/008
acceptance is unchanged; no live/operator rerun or runner launch is authorized by this
synthetic checkpoint.

### Reviewed continuation operator step

Do **not** run these operator modes from an agent or before independent review and
passing synthetic checks. Only the human operator may resolve existing private
configuration/auth. No secret, endpoint, deployment or credential file is a command
argument. From this repository root in a plain operator terminal:

```sh
/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-inspect
```

This performs **no network/model operation**. The prepared compatibility repair reads
bounded validated XDG-selected global config/API-auth locations privately, interpreting a narrow literal
JSON Azure Responses/API-key subset without running OpenCode, plugins or config
expansion. It returns only a nonsecret contract fingerprint or a generic capability
failure.
Offline failure now also includes an allowlisted coarse `reason_code` and
`network_used:false`. The diagnostic change passed independent review and 28 focused
tests with synthetic errors. The human's subsequent SSH-terminal rerun reported
`environment_override`; the triggering variable is unknown, not an established SSH
fault. Affected independent review approved the guard, and coordinator passed 29
focused tests. Rerun the
same inspection command and share only its JSON, never environment dumps, private files
or exception/configuration details. Do not clear the environment to bypass a refusal.

The previous reviewed name-only guard allowed ordinary SSH metadata and these XDG session names:
`XDG_SESSION_ID`, `XDG_SESSION_TYPE`, `XDG_SESSION_CLASS`, `XDG_SESSION_DESKTOP`,
`XDG_CURRENT_DESKTOP`, `XDG_SEAT`, `XDG_VTNR`, but denied every XDG directory/Azure
input. The human category result proved directory/resource inputs are present,
not which variables, values or authentication mechanism. The owner approved the
small compatibility repair below, not a live run or broader credential contract.
Public source basis: pinned OpenCode
[`global.ts`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/core/src/global.ts)
uses the data/config/cache/state paths from
[`xdg-basedir` 5.1.0](https://github.com/sindresorhus/xdg-basedir/blob/v5.1.0/index.js),
whose directory inputs exclude the allowed session names. OpenCode's
[`flag.ts`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/core/src/flag/flag.ts)
and [`auth/index.ts`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/auth/index.ts)
consume config/auth overrides; its
[`provider.ts`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/provider/provider.ts)
and bundled [`@ai-sdk/azure` 3.0.93](https://unpkg.com/@ai-sdk/azure@3.0.93/dist/index.js)
consume Azure resource/key environment inputs. None of that source establishes which
variable was present in the human's terminal.

#### Prepared measured compatibility repair

**Prior compatibility attempt 1/3 passed affected independent review and 47
coordinator synthetic tests. No private resolver or live mode was run by agents.**
Agents never run the resolver, diagnostic or operator modes. After approval, the
next human-only command is the same `operator-inspect` command above. Share only
its sanitized JSON and stop for the coordinator; success does not authorize live use.

The human's latest offline result was `reason_code:file_permissions` with
`network_used:false`. **The actual cause and path are unknown**; this does not identify
a bad directory, file, ownership, permission mode or symlink. Compatibility attempt
2/3 prepares fixed reader-failure details; 51 focused synthetic tests passed,
with affected independent review approved before the human rerun of the
**same** command above. No new diagnostic
command, input support, permission/setup change or live authorization is added.

Only `operator-inspect` failures with coarse `reason_code:file_permissions` may add
an allowlisted `detail_code`:

| Detail code | Observed rejection (no private metadata values returned) |
| --- | --- |
| `directory_ownership` | An opened ancestor is owned by neither root nor the operator. |
| `directory_write_mode` | An opened ancestor fails the existing group/world-write policy, including its root-owned sticky exception. |
| `file_ownership` | The opened final regular file is not operator-owned. |
| `file_write_mode` | The opened final regular file is group/world-writable. |
| `file_type` | The opened final entry is not a regular file. |
| `file_hardlinks` | The opened final regular file's link count is not one. |
| `access_denied` | The existing open/metadata/read operation returned an access denial. |
| `symlink_or_not_directory` | A nofollow/directory operation rejected a link or non-directory; these are deliberately not distinguished by another lookup. |

For these detailed reader failures, `source_category:config` or `source_category:auth`
identifies only the fixed reader call site, **not** a filename, path, credential or
authentication mechanism. The first failing check is reported, not all possible
problems; config is checked before auth, so a config failure leaves auth unestablished.
Unknown/unsupported details are omitted; an unsupported mutated reason remains
`unknown` with no detail/source. Other coarse reasons, successful inspection and all
live generic failure reports are unchanged. No retry, link following, path discovery,
extra metadata lookup or private exception/name/value output is used. Do not change
permissions or clear inputs to bypass a refusal. After review, share only the human
rerun's sanitized JSON and stop; IMP-002 stays blocked and the runner stays stopped.

The resolver's name guard now admits the seven exact XDG directory names and the
session names above, plus **only `AZURE_RESOURCE_NAME`**. Every `OPENCODE_*`, other
`AZURE_*` (including `AZURE_API_KEY` and `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME`),
and unknown `XDG_*` name still stops. Only reviewed human-run code reads selected
`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `HOME` and `AZURE_RESOURCE_NAME` values privately.
Cache/state/runtime/search-directory exports do not select this resolver's
global-config/auth inputs and their values are never retrieved or traversed.
No ambient secret environment mechanism is added.

Source mapping for the implemented subset (public pinned source, not host settings):

- OpenCode `v1.18.34` [`package.json`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/package.json)
  pins Azure `3.0.93` and xdg-basedir `5.1.0`; the
  [root catalog](https://github.com/anomalyco/opencode/blob/v1.18.34/package.json)
  pins Remeda `2.26.0`.
- xdg-basedir `5.1.0` chooses each nonempty config/data home environment value,
  otherwise `os.homedir()`'s `.config`/`.local/share`. OpenCode `Global.Path` appends
  `opencode`; `auth/index.ts` appends `auth.json` to data. This pinned host supports
  only `/home/kemal` for home fallback; another or empty `HOME` stops when a fallback
  is needed, rather than silently reading a different tree. Selected XDG paths must
  be absolute and length/depth bounded, without dot traversal or control characters.
- [`config.ts::loadGlobal`](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/config/config.ts)
  loads `config.json`, `opencode.json`, then `opencode.jsonc` using
  [`mergeDeep` 2.26.0](https://github.com/remeda/remeda/blob/v2.26.0/packages/remeda/src/mergeDeep.ts):
  recursively merge plain objects, later arrays/scalars replace earlier values.
  The resolver implements only literal JSON in those three files, including a
  `.jsonc` file containing strict JSON. Comments, references, invalid/duplicate JSON,
  nonfinite/deep/oversized data and any legacy `config` file stop. It never executes
  JSONC/TOML/OpenCode loaders, legacy migration, plugins or referenced instructions.
- `provider.ts::custom().azure` chooses config `resourceName`, then stored API
  metadata/OAuth account, then `AZURE_RESOURCE_NAME`; config options are reapplied
  after custom loaders. `resolveSDK` prefers nonempty options `baseURL`, then model
  API URL; options `apiKey` overrides the stored API key. Within the supported subset,
  a literal `baseURL` wins over resource inputs; otherwise literal config
  `resourceName` wins over the environment name. Empty/malformed explicit settings
  stop, rather than guessing catalog fallback. Stored Azure auth is checked even
  with config `apiKey`: OAuth and nonempty/malformed API metadata remain unsupported.
  `provider.api`, custom credential `provider.env`, model endpoint/options/headers
  and non-Azure SDK overrides remain denied.
- Azure SDK `createAzure` uses options `baseURL` or
  `https://<resourceName>.openai.azure.com/openai`; Responses routes append `/v1/responses`
  on Azure OpenAI hosts (or deployment-based routes when explicitly enabled), with
  default `api-version=v1`. Its `AZURE_API_KEY` fallback is deliberately **not** supported.
  OpenCode's `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` belongs to the separate
  `azure-cognitive-services` loader, not the supported `azure` provider.

Every selected file is opened relative to nofollow directory fds, including all
ancestors, with checked root/operator ownership and non-writable directories
(root-owned sticky ancestors allowed). Files must be operator-owned regular files,
not group/world-writable or hardlinked, and at most 256 KiB. Missing default JSON
files are skipped in source order; an unavailable/unsafe present file stops, never
falls back to another tree. The existing diagnostic's directory check is reused;
the diagnostic command itself is unchanged.

This interprets **only the supported literal global contract**, not full effective
host configuration. Account/managed/project/plugin sources and model catalog/cache
inheritance are not loaded or established; no assertion is made that the real host
session uses this contract. Actual XDG/resource values, auth mechanism, account/model
compatibility and complete isolated session/proposal acceptance remain unproved.
An unsupported source yields only a fixed sanitized refusal. No file paths, values,
endpoint, deployment or credential appear in reports/arguments/logs or worker inputs;
the existing host-only contract fingerprint and relay boundary are unchanged.

### Reviewed category diagnostic (human only)

After another `environment_override` result, the owner authorized a different-angle
**diagnostic only**, not another guard change or configuration/auth support expansion.
The command below passed independent review and 40 focused synthetic tests before
the **human** runs it in a plain terminal from this repository. Agents must never run
it, read private inputs or ask for their contents:

```sh
/usr/bin/python3 -I -B scripts/imp002_diagnostic.py
```

It accepts no arguments. Share only its one sanitized JSON report. `status:complete`
means category collection completed, **not** compatible auth/config or live readiness;
`status:unavailable` is a generic stop with no error details. No fingerprints are made.
The fixed `environment` booleans distinguish XDG directory/session/unknown names,
OpenCode inline config/path/inline auth/other names and Azure auth/resource/other names.
Presence includes empty values; only the two exact inline content inputs are read.
Path/resource/key/unknown environment values are never read or followed.

`sources` reports the two inline inputs and the existing resolver's fixed global
JSON/named-JSON/JSONC/legacy and default auth locations. `literal_json` means a bounded
read produced a literal JSON object, not a valid OpenCode configuration. `absent`,
`unreadable`, `unsafe`, `too_large`, `unsupported`, `unsupported_format` and
`expansion_required` distinguish safe collection failures without showing content.
Directory/path overrides (including unknown XDG names) leave both default trees
`uninspected_override`; inline auth leaves default auth uninspected. This conservative
inspection policy is **not** a claim about runtime precedence. JSONC/legacy files get
safe metadata checks only; there is no JSONC/TOML parser or new dependency. File reads
are bounded, owner/permission checked and nofollow through every directory component.

`authentication_observed` aggregates literal API-key/OAuth/well-known remote and
config bearer-header/token-provider declarations across inspected inputs, never
provider identities or the effective credential. Unsupported records are flagged;
token-provider declarations are unsupported, not executed. False means **not observed
in inspected literal inputs**, not proof of absence. References are detected but never
expanded; referenced content is not classified. Plugins, remote config, project,
managed/account sources and arbitrary referenced files are never loaded or traversed.
Endpoint/model `ambiguity:potential` is a coarse warning from declarations/overrides;
`unknown` does not prove unambiguous precedence. `effective_configuration:unestablished`
and `other_sources:uninspected` always remain explicit. No network/OpenCode/worker/live
operation or config/environment edit occurs. Output is projected through fixed key,
enum and boolean allowlists; no names, values, paths, URLs, credentials or errors escape.

The diagnostic checkpoint was followed by the measured compatibility authorization
above. Stop after the reviewed inspection's sanitized operator result; do not proceed
to the historical live command below. IMP-002 stays blocked and the runner stays stopped.

The resolver also refuses unsupported
global formats, auth/metadata/model/provider options, non-inference routes
and nonliteral settings; it does not pretend to implement full host config precedence.
If unavailable, stop. The next useful operator action is privately reconciling the
actual endpoint, deployment mapping, API version and auth mechanism with this
supported subset; do not send private settings/secrets/logs to an agent or substitute
invented settings, a fresh credential copy, host CLI fallback or network provisioning.

**Historical continuation command, not authorized by the current compatibility repair.**
Only after separately approved live continuation, pin a successful inspection fingerprint in the following operator
command (the only argument is that **nonsecret** fingerprint):

```sh
/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-live --contract-sha256 <returned-fingerprint>
```

This re-resolves the contract privately, rejects drift, pins a public resolved IP,
uses direct verified TLS with the fixed system CA bundle, and sends only the generated
synthetic worker prompt. No redirects/retries/proxies/worker headers/ambient TLS env;
no host transport/config/auth is mounted in the worker. Limits remain four accepted
connections/calls, 128 KiB requests, 32 KiB upstream and downstream stream bytes,
3 s idle I/O, 12 s per call, 30 s relay life and 20 s worker time. Caller disconnect,
relay shutdown or deadline cancels and closes the upstream connection. Provider
headers/IDs/metadata/reasoning/errors are not exposed; only bounded normalized text
is retained in host memory for the synthetic sentinel check. Reports omit raw
worker/model output and credentials; literal credential echoes are redacted, including
split deltas. Failed/incomplete/malformed inference produces no completed event.
These live bounds/capabilities have **not** been verified against the actual account.

The pinned public `v1.18.34` `cli/cmd/run.ts` explicitly denies questions in noninteractive
mode, auto-rejects permissions and emits text only after `part.time.end`; `--format json`
is not full protocol proof. The pinned SDK exposes `/event`, `/session`,
`/session/{sessionID}/message`, `/session/{sessionID}/prompt_async`,
`/session/{sessionID}/abort`, `/question/{requestID}/reply` and
`/permission/{requestID}/reply`. Next bounded session experiment must exercise those
interfaces **inside the isolated worker**, without exposing a host OpenCode server,
and prove restart/resume, event recovery, question replies, default-deny permissions
and revision-safe proposal import. None of those acceptance checks is delivered by
the operator live turn. IMP-002 remains blocked and the runner stays stopped.

## Manifest persistence verification (IMP-020)

Migration `20260930_0006`, following `20260929_0005`, adds the three-document
manifest table and pair-snapshot constraint without backfilling approvals or changing
existing pair approvals/document history. IMP-020 verified persistence with routes
unregistered; IMP-021 subsequently verified and enabled the final approval/status/
download routes. Persistence alone was not approved-download delivery.

Fresh owned PostgreSQL checks verified upgrade, populated-0005 preservation, pair
snapshot foreign-key/uniqueness failures and disposable downgrade/re-upgrade. A
downgrade removes final manifests; use it only on disposable verification storage,
not as a promised preservation/recovery operation for real approved handoffs.

For this checkout's bounded verification, the operator helper
`/tmp/opencode/impostr-imp020-prereq-20260930/check_current.py` provides `verify`,
`check` and `pg`. It pins current API/Compose/DB inputs, uses generated disposable
database credentials, publishes no ports and verifies owned cleanup. Three immutable
legacy template files from the archived `e2cabfd` baseline are **test-harness-only**
inputs. Deleted root templates remain deleted: a passing bounded check does not mean
the ordinary worktree build works or that simplified templates were integrated.
The helper/source map is local evidence, not a reusable unpinned setup command;
refresh exact inputs before checking changed code. Reviewer uses in-repo material,
not the denied temporary marker or snapshot content.

## Human-only final approval and downloads (IMP-021/010)

### Selected template compatibility (IMP-022)

The API and browser-fixture archive now consume exactly
`overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example`. Canonical output filenames
remain PROJECT.md, AGENTS.md and BACKLOG.md. Ordinary runtime/development API builds
work with those inputs; historical root-template test harnesses are no longer needed
for this repaired build. Earlier build-blocker statements below are historical.

New project seeds record exact nested source paths/raw-byte digests. Frozen supported
legacy/simplified three-file provenance tuples select approval validation; editing
headings or changing installed templates cannot change an existing project's profile.
Unsupported/mixed provenance fails closed. Startup does not complete partial seeds
using a different bundle. Existing immutable history and approvals are not rewritten.
Changing a canonical example's bytes requires explicit supported-version compatibility
work; it is not a free-form runtime template override.

Compact scope prose, `Acceptance:` and inline `Verification:` are interpreted
consistently by task editing and approval, without borrowing metadata or hidden
examples. IMP-014's local candidate and rendered acceptance is verified; consult
BACKLOG.md for delivery references.

Final approval requires the current approved PROJECT.md/AGENTS.md pair and exact
current BACKLOG.md revision with substantive task evidence. A ready task marker is
not final approval or proof that its dependencies are complete. Metadata-only or
otherwise invalid required evidence returns `422`, creates no manifest/success audit
or document mutation, and leaves status unapproved with downloads unavailable (`409`).
Stale pair/backlog expectations return `409`; changing any saved member invalidates
the handoff, including saving identical bytes as a new revision. Review the current
pair/backlog and explicitly approve again; historical invalid manifests fail closed.

Authorized downloads return the recorded current tuple's exact UTF-8 bytes with
canonical PROJECT.md, AGENTS.md and BACKLOG.md filenames. They do not initialize a
repository, run a task or enable chat. These checks do not deliver chat, private
HTTPS/media, agent isolation or release readiness. Local synthetic API checks used
disposable storage, not real project data.

### Using Stage 3 · Final review

Open a project's **Final review and downloads** stage after reviewing the saved drafts. It
shows the current saved PROJECT.md, AGENTS.md and BACKLOG.md revisions and their
content digests. Review each file; the two-file pair approval, backlog task
readiness/dependency eligibility, and final three-file approval are separate:
readiness is metadata, pair approval covers only PROJECT.md + AGENTS.md, and final
approval records the exact current three-file tuple. Approve the displayed tuple
only after reviewing it. Each file has its own download action, enabled only while
the server confirms that the displayed saved revisions and readiness snapshot
match the current final approval. Downloads use the canonical filenames and exact
approved saved bytes.

If any document or task edit is pending locally, save or discard it and refresh
status before approval or download. Saving a new revision of any document (even
identical content) invalidates final approval; review the changed saved tuple and
approve it again. A stale revision or readiness snapshot requires reloading the
current drafts/status. On narrow screens, use the PROJECT.md, AGENTS.md and
BACKLOG.md tabs to switch the visible review pane; keyboard arrows, Home and End
move among tabs. Changing project stages may reset the selected file and scroll
position.

## Prerequisites and pinned runtimes

- Docker Engine with Compose v2 (`docker compose`); observed verification host:
  Docker 29.8.0 and Compose 5.5.1.
- The host Python 3 executable is used only to generate the local `.env` file.
  Observed host version was Python 3.10.12.
- `curl` is optional and is used only for the command-line health check below;
  the same local endpoint can be opened in a browser.
- Application containers use Python 3.12.11, Node 22.17.0 with npm 10.9.2,
  PostgreSQL 17.6, and nginx 1.29.0. API dependencies are hash-pinned in
  `api/requirements.lock` and `api/requirements-dev.lock`; web dependencies are
  pinned by `web/package-lock.json` and `web/.npmrc` enforces the Node/npm engine
  versions. No host Node or Python application install is required.

## Create local credentials and start

1. Create a private local environment file from the canonical example. The
   following command creates `.env` with two separate random 256-bit hex passwords,
   sets mode `0600`, and refuses to overwrite an existing file:

   ```sh
   python3 -c 'from pathlib import Path; import os, secrets; os.umask(0o077); p=Path(".env"); t=Path(".env.example").read_text(); assert not p.exists(), ".env already exists; refusing to overwrite"; t=t.replace("POSTGRES_PASSWORD=\n", "POSTGRES_PASSWORD="+secrets.token_hex(32)+"\n").replace("DB_PASSWORD=\n", "DB_PASSWORD="+secrets.token_hex(32)+"\n"); p.write_text(t); p.chmod(0o600)'
   ```

   Keep `.env` local and do not copy these development credentials to another
   environment. If `.env` already exists, preserve it and handle it securely;
   do not rerun the generation command over it. The database password variables
   `POSTGRES_PASSWORD` and `DB_PASSWORD` must be non-empty. The front door is
   published on `127.0.0.1:${APP_PORT:-8080}`; do not expose it to a network.

   Compose reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_USER`,
   `DB_PASSWORD`, `IMPOSTR_RATE_LIMIT_KEY`, `IMPOSTR_PUBLIC_ORIGIN`, and
   `APP_PORT`. The example uses database `impostr`, database owner
   `impostr_owner`, and application role `impostr_app`. Leave
   `IMPOSTR_PUBLIC_ORIGIN` unset for this local setup; the API derives
   `http://127.0.0.1:<APP_PORT>`. A blank `IMPOSTR_RATE_LIMIT_KEY` uses
   `DB_PASSWORD` as the key for pseudonymized rate-limit buckets; a separately
   configured key must contain at least 32 bytes. `APP_BIND_ADDRESS` is not a
   current setting.

2. Build the pinned service images, apply migrations, then start the stack. Use
   the same explicit Compose project name for every command in this guide; choose
   a different unique local name if another stack would otherwise share it.

   ```sh
   docker compose -p impostr-verify1 config --quiet
   docker compose -p impostr-verify1 build db api frontdoor
   docker compose -p impostr-verify1 run --rm api alembic upgrade head
   docker compose -p impostr-verify1 run --rm api alembic current
   docker compose -p impostr-verify1 up -d
   docker compose -p impostr-verify1 ps
   ```

   The migration command starts and waits for the database dependency. Apply
   migrations before starting/updating the API and front door. The earlier
   IMP-001/003 baseline check reached `20260925_0002`. This worktree adds
   `20260925_0003` for project-name keys and document/revision/conflict-proposal
   tables; the API seeds three root-template drafts on project creation and startup.
   `20260925_0004` bounds normalized project-name keys to 64-character digests.
   `20260929_0005` adds immutable records binding a human approval to one
   `PROJECT.md`/`AGENTS.md` revision pair. Existing drafts are not automatically
   approved by this migration. The IMP-013 candidate preflight checked a fresh
   database at head `20260929_0005`; this does not establish that every existing
   local database has been migrated. The API and front door wait for their
   dependencies' health checks.

3. Bootstrap the first administrator once, after migrations and stack startup.
   Replace `adminname` with a chosen username accepted by the account rules. The
   command prompts twice for the password in the terminal; do not put passwords in
   command arguments or copy them into Git.

   ```sh
   docker compose -p impostr-verify1 run --rm -it api \
     python -m app.bootstrap_admin bootstrap --username adminname
   ```

   Bootstrap succeeds only once, when migrations are applied and the users table
   is empty. Usernames are normalized to lowercase, must start with an ASCII letter
   or digit, and contain 3–127 ASCII letters, digits, or `.`, `_`, `@`, `+`, `-`.
   Passwords must contain at least 12 characters.

4. Open <http://127.0.0.1:8080> on the same machine (the default `APP_PORT` is
   `8080`; use the configured port if you changed it). The only host-published
   service is the front door. Sign in with the credentials you chose. Verify the
   API/database health endpoint with:

   ```sh
   curl --fail --silent --show-error http://127.0.0.1:8080/api/health
   ```

   This health command uses the default port; replace `8080` if `APP_PORT` was
   changed.

   Health checks database reachability only; it does not verify sign-in or a
   project workflow. Local sign-in uses an operator-provisioned account; there is
   no public registration.

## Tests and checks

Compose loads `.env` while parsing the project, so create it before running these
commands. The `checks` profile builds the development/check images; API tests use
SQLite fixtures and do not require a running PostgreSQL service. These are the
coordinator-verified combined gates:

```sh
docker compose -p impostr-verify1 --profile checks run --build --rm api-check sh -c 'python -m pytest -p no:cacheprovider && ruff check . && ruff format --check . && mypy app'
docker compose -p impostr-verify1 --profile checks run --build --rm web-check sh -c 'npm run test && npm run lint && npm run format:check && npm run typecheck && npm run build'
```

The earlier IMP-004 API gate skipped 9 PostgreSQL-specific integration tests;
those 9 were reported as passing separately against a fresh isolated validation
database migrated to `20260925_0004`. The IMP-001/003 baseline had only 3 such
tests. These earlier results do not include the IMP-013 candidate or establish
its final gates. Do not run integration tests against a database containing local
project data.

The Compose `integration` profile runs PostgreSQL-backed tests against its own
database service and sets the opt-in integration-test flag. For a fresh, unique
project name (change the example suffix if it is already in use), run from the
repository root after creating the local `.env` described above. Migrate that
disposable database before running its tests, and remove only its resources:

```sh
docker compose -p impostr-imp013-pg-check-01 config --quiet
docker compose -p impostr-imp013-pg-check-01 --profile integration build db api-integration-check
docker compose -p impostr-imp013-pg-check-01 run --rm api alembic upgrade head
docker compose -p impostr-imp013-pg-check-01 run --rm api alembic current
docker compose -p impostr-imp013-pg-check-01 --profile integration run --rm api-integration-check \
  sh -c 'python -m pytest -p no:cacheprovider tests/test_postgres_integration.py tests/test_document_pair_approval_postgres.py'
docker compose -p impostr-imp013-pg-check-01 --profile integration down -v --remove-orphans
```

This starts the profile's database dependency; `-v` deletes that named project's
database volume, so never reuse a project name containing local data. The IMP-013
isolated PostgreSQL check migrated a fresh database to `20260929_0005` and passed
all 10 integration tests, then removed its disposable resources.

In the earlier IMP-001/003 baseline validation, the coordinator verified Compose
configuration, image builds, a fresh migration at `20260925_0002`, stack
start/status/restart, and health behavior. Health returned 200 normally, 503 with
the database stopped, and 200 after database recovery; `/api/agents` returned
404. The only published service was `127.0.0.1:8080`; all listed commands exited
0. That baseline API gate passed 32 tests, skipped 3 PostgreSQL-only tests, and
passed Ruff, format, and mypy; separate PostgreSQL migration and 3 integration
tests passed. The baseline web gate passed 6 tests plus lint, format, typecheck,
and build. Browser checks at 1440, 1024, 768, and 375 px found no horizontal
overflow and confirmed keyboard focus. These IMP-001/003 results are not final
IMP-004 gates. A prior toolkit run passed 98 tests with one gated live-Docker
test skipped; the separately exercised live recovery test is described below.
That toolkit result predates the IMP-013 candidate and is not its final gate.

## Disposable authenticated browser review (operator-only)

This is a maintainer/operator check for the approved local checkout, not a general
product setup, CI service, or unattended global fixture. It requires Docker with a
working local Unix socket and the owner-approved handoff directory
`/tmp/opencode/impostr-review-handoff` already available to the operator and
permitted file tools. The directory must be owned by the current user and mode
`0700`. The owner also explicitly accepts the existing exact canonical directory
at UID/GID `1000:1000`, mode `0775`, **only** for short-lived generated synthetic
Member login and sanitized cleanup handoff. Other group members can observe or
tamper with this channel; confidentiality/integrity against them is not claimed.
This exception never applies to real accounts, provider/admin/DB credentials,
private fixture/control state, other paths or modes, world-write, changed owners
or symlinks. Private state still requires `0700`; handoff files remain plain owned
single-link mode `0600` with existing size/content checks. No directory permissions
are changed by this correction. If tool permissions for
this channel change, first prove a harmless marker can be written and read through
the permitted tools. If that proof is denied, stop before launching or creating
credentials; do not move the file or use another tool to bypass the denial.

From the repository root, start the fixture with the approved 30-minute lifetime:

```sh
python3 scripts/local_browser_fixture.py launch --handoff-dir /tmp/opencode/impostr-review-handoff --lifetime-minutes 30
```

On success, the launcher prints the run's temporary loopback browser origin and
the private handoff-file location. Use the permitted `Read` tool to read
`member-login.json`; enter that generated, short-lived synthetic Member login in
the application's normal sign-in form in the shared Playwright page. Keep that
same authenticated page open for `ui-designer`'s rendered review. The generated
Member usernames are compact, validator-compatible synthetic identifiers, not
real-person accounts. The fixture creates a fresh disposable app/database and
does not use a test-only sign-in bypass. Do not copy login values, session data,
or the temporary origin into Git, issues, or public logs; keep browser/tool logs
private and untracked. Never use owner-created or other real-user logins, or
owner/admin/database/provider/host credentials or sessions.

After the review, stop the fixture and read its sanitized cleanup record through
the permitted `Read` tool:

```sh
python3 scripts/local_browser_fixture.py stop
```

Read `/tmp/opencode/impostr-review-handoff/cleanup-status.json`. Verified cleanup
has a stopped phase, the generated login removed, owned Compose resources and
images removed, private fixture state removed, and recovery either not needed or
completed. The cleanup record contains status values only, not credentials. A
zero exit from `stop` with that verified status indicates normal completion; a
nonzero exit means setup or review failed, even when cleanup succeeded. Two fresh
runs of this fixture completed normal browser sign-in and rendered review;
`ui-designer` returned PASS. Its checks included Member denial of an admin-only
request (HTTP 403), expired/revoked session denial (HTTP 401), and post-handoff
account/session and owned-resource cleanup.

If launch fails, it exits nonzero and reports that setup failed or no safe browser
handoff was produced; do not continue to the browser. Read the sanitized cleanup
status rather than relying on process exit or raw logs. `stop` may also exit
nonzero when setup/review failed even if owned cleanup was verified; that does not
mean the review passed. If owned teardown is still unverified after the supervisor
has stopped, retry its ownership-checked recovery:

```sh
python3 scripts/local_browser_fixture.py recover
```

Recovery succeeds only when the fixture's registered resources and private state
can be verified as removed. If a supervisor or guardian is still active, use
`stop` first. If Docker is unavailable or the local engine is recovering, retain
the private recovery state and retry after the engine is available. If the status
is `manual-required`, ownership cannot be verified: do not run broad Docker
cleanup or delete the private recovery state; request operator-assisted recovery.
The launcher also refuses to replace an existing login or prior run with
unverified cleanup. The requested lifetime is bounded (5–240 minutes) and the
fixture performs automatic teardown at its limit.

By default, the fixture archives committed `HEAD` for the app snapshot, not dirty
working-tree changes. Uncommitted IMP-004 code is therefore excluded from the
default mode. An opt-in, fingerprint-pinned candidate mode is described below; it
does not change the default. The normal browser page is served only on loopback,
but the shared Playwright tool server is **not OS-confined** and may have access to
Docker, host secrets, or another stack. This is an accepted residual host risk for
this local synthetic review, not a security control; do not claim a proven denial,
intentionally use those capabilities, or extend this exception to product-agent
isolation or shared-server readiness.

### Reviewing the dirty IMP-004 candidate

This operator-only path is separate from the committed-`HEAD` fixture mode. It is
for reviewing the specific IMP-004 worktree candidate based on `2d71c1b`; it is not
a general dirty-tree preview or a product/deployment command. The preflight needs
Docker with the local Docker socket. Candidate launch additionally requires the
already-approved handoff directory `/tmp/opencode/impostr-review-handoff` to be
owned by the operator with mode `0700` (or the exact synthetic-only development
exception documented above) and available through the permitted file
tools. If the channel's permissions may have changed, prove a harmless write/read
marker first. If that fails, stop before creating credentials; do not choose
another path or tool.

First run the candidate infrastructure preflight from the repository root:

```sh
python3 scripts/local_browser_fixture.py candidate-preflight
```

It accepts only the fixture's explicit reviewed runtime-input and test-only
allowlists over the pinned base commit. It rejects unrelated or missing changes,
symlinks, traversal, oversized inputs (512 KiB per file and 2 MiB total), and
recognized literal secrets. The tests are accepted as test-only input, not copied
into runtime images. The fixture fingerprints the base commit, path/status/mode,
and input content digests; the fingerprint does not disclose file contents. The
preflight builds and migrates a fresh isolated Compose stack to `20260925_0004`,
checks project creation, template provenance for all three drafts, cross-member
denial and cleanup. It does **not** perform browser rendering or publish a login.
Copy the exact lowercase 64-character `CANDIDATE_FINGERPRINT` it prints. Do not
reuse any fingerprint from an earlier run or from this document.

Only if preflight passes and none of its candidate inputs have changed, launch the
rendered-review fixture with that exact fingerprint (replace the placeholder):

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --candidate-fingerprint <CANDIDATE_FINGERPRINT_FROM_THIS_PREFLIGHT>
```

The launch refuses an invalid or stale fingerprint, rechecks the snapshot, and
uses a new uniquely named local Compose project and loopback-only front door. Read
only the generated `member-login.json` through the permitted tool, use it for
normal Member sign-in, and keep that authenticated page open for the rendered
review. The fingerprint printed at launch must match the preflight fingerprint.
Candidate preflight alone is infrastructure evidence, not rendered-review signoff.
Any candidate input change requires a fresh preflight and rendered review of that
same new fingerprint.

After review, stop the supervisor and inspect only the sanitized cleanup status:

```sh
python3 scripts/local_browser_fixture.py stop \
  --handoff-dir /tmp/opencode/impostr-review-handoff
```

Read `/tmp/opencode/impostr-review-handoff/cleanup-status.json` through the
permitted tool. Confirm the phase is stopped, the generated login/accounts are
removed or disabled, owned Compose resources and run-built images are removed,
private fixture state is removed, and recovery is either `not-needed` or
`completed`. A failed review remains a failure even if owned cleanup succeeded.
If cleanup is not verified, follow the ownership-checked `recover` procedure above;
do not run broad Docker cleanup or delete recovery state manually. The fixture
removes only resources it registered to its unique project and does not prune the
shared Docker cache.

The candidate fixture necessarily uses the local Docker daemon and contains an
unconfined shared browser-tool-server residual risk. Use only its generated
synthetic account and project. Do not infer Docker/host-secret denial, product
agent isolation, or shared-server readiness. The candidate preview and browser
review do not make the dirty implementation committed or establish production
acceptance.

### Reviewing the dirty IMP-013 approval candidate

This is a separate operator-only preview of the bounded IMP-013 candidate, based
on committed `HEAD` `60e9480`; it is not the IMP-004 candidate mode above. It uses
the local Docker daemon and the same private handoff, synthetic-account, and
unconfined shared-browser-tool-server cautions described above. Run from the
repository root. First run its fresh-stack API preflight:

```sh
python3 scripts/local_browser_fixture.py imp013-candidate-preflight
```

The preflight accepts only its explicit IMP-013 runtime/test allowlist over that
base, fingerprints the candidate and fixture inputs, creates synthetic accounts
and project drafts, checks project isolation and the authenticated approval flow,
and performs owned cleanup. It exercises rejection of an invalid pair, approval
of a valid saved pair, and invalidation after a later saved edit. It does not
publish a browser login or provide rendered-review evidence. If it passes, copy
the lowercase fingerprint printed by that run; never reuse a fingerprint from an
earlier run or copy one into documentation.

Only if the candidate inputs are unchanged since that preflight, launch its
authenticated rendered review with that exact fingerprint:

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --imp013-candidate-fingerprint <FINGERPRINT_FROM_THIS_PREFLIGHT>
```

Replace the fingerprint placeholder with the exact value from the immediately
preceding preflight. As in the IMP-004 procedure, use only the generated,
short-lived synthetic Member login through normal sign-in; keep credentials,
session data, origin, and raw logs out of Git and public channels. The coordinator
owns sign-in and rendered review. On completion, stop the fixture and verify its
sanitized cleanup record using the same ownership checks as above:

```sh
python3 scripts/local_browser_fixture.py stop \
  --handoff-dir /tmp/opencode/impostr-review-handoff
```

After the UI repair, the independent code review returned APPROVED. The exact
candidate preflight passed with migration head `20260929_0005`, and the
authenticated rendered reviewer passed valid-pair approval, approval invalidation
after the `AGENTS.md` edit to revision 3, and responsive review at 1440, 1024, 768,
and 375 px, including the narrow action layout. A two-tab stale-save check
produced the expected r2/r3 conflict while preserving the editor text and
conflict-proposal comparison; no false history alert appeared.
Fixture stop and owned cleanup were verified. Final API (81 passed, 10 PostgreSQL-
profile skips, plus Ruff/format/mypy), isolated PostgreSQL (10 passed), web (60
passed plus lint/format/typecheck/build), and toolkit (116 passed, one gated live-
Docker test skipped) checks also passed. These results are local candidate gates,
not a commit or release. If any candidate input changes, repeat preflight and
rendered review against the new fingerprint. A failed review remains a failure even when
cleanup succeeds; use the ownership-checked recovery steps above if cleanup is
not verified.

### Reviewing the dirty IMP-007 backlog candidate

This operator-only path previews the scoped IMP-007 worktree candidate over
committed base `31d0f8f`; it is separate from the IMP-004 and IMP-013 profiles and
is not a general dirty-tree preview. It accepts only its pinned runtime, test and
fixture inputs, fingerprints the exact snapshot, and uses the committed
`scripts/backlog.py` as compatibility support. Run the preflight from the
repository root:

```sh
python3 scripts/local_browser_fixture.py imp007-candidate-preflight
```

The preflight builds a fresh disposable stack, migrates it to head
`20260929_0005`, checks the authenticated saved backlog task view, and verifies
that another synthetic Member cannot read or edit that project's tasks. It cleans
up its owned resources without publishing a browser login; it is API/infrastructure
evidence, not rendered review. If it passes, use the exact lowercase 64-character
`IMP007_CANDIDATE_FINGERPRINT` printed by that run. Do not reuse a value from an
earlier run or copy one from this guide.
Any change to candidate inputs requires a new preflight and rendered review.

Only with that same candidate snapshot, launch the authenticated rendered review
using the exact preflight fingerprint:

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --imp007-candidate-fingerprint <FINGERPRINT_FROM_THIS_PREFLIGHT>
```

The launch revalidates the fingerprint and snapshot, then runs the same private,
loopback-only synthetic browser fixture described above. Use only its generated
Member login through normal sign-in; the coordinator owns sign-in and rendered
review. Keep the login, session data, temporary origin and raw logs private and
untracked. After review, stop the fixture:

```sh
python3 scripts/local_browser_fixture.py stop \
  --handoff-dir /tmp/opencode/impostr-review-handoff
```

Read the sanitized `cleanup-status.json` through the permitted handoff tool. Check
that the run stopped, its generated account was removed or disabled, its owned
Compose resources/images and private fixture state were removed, and recovery is
`not-needed` or `completed`. A failed review remains a failure even if cleanup
succeeds; if cleanup is not verified, use the ownership-checked recovery procedure
above, not broad Docker cleanup.

The latest reviewed candidate used an abbreviated fingerprint recorded as
`a2621b7…d4a2e` (evidence only, not a reusable value). Its preflight passed at
migration `20260929_0005` and confirmed cross-Member authorization denials. Normal
synthetic Member sign-in and rendered review passed at 1440, 1024, 768 and 375 px;
`ui-designer` returned PASS, and owned cleanup was verified with `stop` exit 0.
This evidence applies only to that exact candidate snapshot and does not mean the
candidate was committed.

### Reviewing the dirty IMP-014 backlog editor candidate

This operator-only profile is based on committed `3b5d603` and overlays only
`web/src/BacklogPlanning.tsx` and its test plus the host fixture scripts. It uses
the IMP-015 synthetic fixture and approved private handoff; do not broaden the
overlay or use real project data. From the repository root, run:

```sh
python3 scripts/local_browser_fixture.py imp014-candidate-preflight
```

For the exact snapshot that passed preflight, launch with the printed fingerprint:

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --imp014-candidate-fingerprint <FINGERPRINT_FROM_THIS_PREFLIGHT>
```

The coordinator uses the generated short-lived Member login through normal sign-in
and reviews the rendered UI. Keep credentials, session data, private fixture state
and raw logs private. Stop the owned fixture and verify sanitized cleanup status
through the permitted handoff; confirm generated accounts/login and owned resources,
images and private state were removed. Do not use broad Docker cleanup or move
handoff contents to another channel. Existing denied-path and residual shared
Playwright host-risk rules above apply.

The verified candidate fingerprint was
`14074823ca05988bb8d0b091376c15419acfe62dab405031e2f901bf24758f13`. Its preflight
passed migration `20260930_0006`, nested-template checks, authentication and
cross-Member denials. Normal sign-in rendered review received `ui-designer` PASS at
1440/1024/768/375 px. Review covered body preservation, missing-newline repair,
invalid inputs, readiness, rail collapse, keyboard operation, and an actual 409 conflict
that retained local edits and showed the newer saved version for explicit reapplication. Stop exited 0 and
owned cleanup verified generated accounts/login, resources/images, and private
state removed. These results verify local acceptance of that exact candidate only;
consult BACKLOG.md for delivery references.

Web verification was 73 tests plus lint, format, typecheck and build; toolkit was
137 tests with one gated live-Docker test skipped. A proposed live setup using an
empty backlog was rejected to preserve task state; unit coverage exists, but there
is no live empty-backlog proof. Independent code review and focused repair review
passed. If candidate inputs change, repeat preflight and rendered review.

As with the other candidate reviews, this preview uses the local Docker daemon and
the shared Playwright tool server is **not OS-confined**; it may access Docker,
host secrets or another stack. This is accepted residual host risk for synthetic
local review, not a security control. Do not intentionally use those capabilities,
claim a proven denial, or extend the exception to product-agent isolation or
shared-server readiness.

### Reviewing the dirty IMP-010 final-review candidate

This operator-only profile is pinned to committed base `daf078c` and the scoped
Stage 3 UI inputs (`web/src/App.tsx`, `web/src/ProjectWorkspace.tsx`, and
`web/src/FinalReview.tsx`), their scoped tests, and fixture harness changes. It is
not a general dirty-tree preview. From the repository root, run:

```sh
python3 scripts/local_browser_fixture.py imp010-candidate-preflight
```

The fresh disposable-stack preflight checks migration `20260930_0006`, approval,
save invalidation and reapproval, exact downloads, cross-Member denials, and owned
cleanup; it does not render the UI or publish credentials. If it passes, use only
the fingerprint printed by that run, and only while the candidate inputs remain
unchanged:

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --imp010-candidate-fingerprint <FINGERPRINT_FROM_THIS_PREFLIGHT>
```

Use the generated short-lived Member login through normal sign-in; keep credentials,
temporary origin and raw logs private. Coordinator-owned rendered review is separate
from preflight. Stop the fixture and verify its sanitized cleanup status using the
ownership and residual-risk precautions above. Any changed candidate input requires
a fresh preflight and rendered review. Do not broaden the profile, preview arbitrary
worktree changes, reuse a prior fingerprint, or treat this synthetic review as
chat, private-HTTPS, isolation or release acceptance.

The verified IMP-010 candidate passed preflight and rendered review, including
normal Member approval, save invalidation/reapproval and three exact downloads;
`ui-designer` passed the 1440/1024/768/375 px review. This evidence is only for that
exact candidate snapshot, not a general preview permission or release claim.

The separately gated live SIGKILL recovery test is run from the repository root
with Docker available and an appropriate container image already cached. It does
not pull an image; if none is cached, the test skips. The test starts two isolated
throwaway Compose projects, simulates an abrupt supervisor-child `SIGKILL`, and
checks recovery removes only the fixture-owned resources while preserving the
other test project:

```sh
IMPOSTR_FIXTURE_LIVE_RECOVERY=1 PYTHONPATH=scripts python3 -m unittest test_local_browser_fixture.RecoveryOwnershipTests.test_live_abrupt_failure_recovery_preserves_an_unrelated_compose_project
```

The default toolkit command remains `python3 -m unittest discover -s scripts -p 'test_*.py'`;
it skips this live test unless `IMPOSTR_FIXTURE_LIVE_RECOVERY=1` is set.

The local `.env` generation helper was tested by the developer from an initially
absent file; no `.env` was committed. The optional `curl` health probe was run by
the coordinator. An earlier `npm audit --audit-level=moderate` check (from `web/`)
found zero moderate-or-higher issues; the latest attempt was blocked by `EAI_AGAIN`
resolving the npm registry. Host `pip-audit` is not installed and no final
independent Python dependency audit was run; no release security gate has been
established.

## Accounts and operator recovery

- The initial administrator is created only through the offline bootstrap command
  above. There is no public or network endpoint to bootstrap or recover an admin.
- Administrators provision accounts in the authenticated UI. There is no
  self-registration. Admins can reset another account's password or deactivate
  it; deactivation and password resets revoke that account's active sessions.
  Users can change their own password; that revokes other sessions while keeping
  the current session active. Credential administration is recorded in the audit
  table.
- To recover an existing administrator, use the same Compose project/database and
  substitute the real administrator username. The command prompts for and
  confirms a new password, re-enables the account, and revokes its active sessions:

  ```sh
  docker compose -p impostr-verify1 run --rm -it api \
    python -m app.bootstrap_admin recover --username adminname
  ```

- Browser sessions last 12 hours. The session cookie is HttpOnly and SameSite
  Strict; unsafe API requests require a matching CSRF token and exact configured
  Origin. The API uses Argon2id password hashes and database-backed rate limits.
  These controls do not make the local-only deployment suitable for external
  exposure.

- A signed-in member can list, create, and read projects owned by their account;
  administrators can read all project metadata and documents, with admin reads
  audited. Project names are trimmed and NFC-normalized, 1–120 characters, cannot
  contain path separators/control/format characters, and are unique per owner after
  NFKC normalization, trimming and case-folding. Names never become filesystem
  paths. A new project receives an opaque ID, creator and UTC creation time, plus
  draft `PROJECT.md`, `AGENTS.md`, and `BACKLOG.md` revisions seeded from the root
  `.example` templates. The initial revision records template source and SHA-256
  provenance. On API startup, missing template drafts are also backfilled for
  existing metadata-only projects. This does not create a Git repository or launch
  the toolkit.

## Project drafts, history, and local data recovery

PostgreSQL is authoritative for project metadata, each document's current-head
number, immutable document revisions, and stale-write conflict proposals. A
revision records UTF-8 Markdown content, a SHA-256 content digest, UTC timestamp,
origin (`template` or `human`), author where applicable, and template source/digest
for template revisions. Each of the three document kinds allows at most 128 KiB
of UTF-8 content. Project and document reads/writes are restricted to the owner;
administrators may access all projects and their reads/writes are audited. A
foreign or missing project is reported as not found.

Saving a draft requires the revision number the editor read. A current expected
revision creates the next immutable `human` revision. A stale expected revision
does not overwrite the saved head: the API returns HTTP 409 with the latest
revision and records the submitted text, expected/observed revision numbers,
author, timestamp and digest as an immutable conflict proposal. Review and
reapplication are explicit; there is no automatic merge. Revision history is
ordered by revision number. Conflict-proposal pagination uses a stable cursor so
concurrent proposals do not shift already paged rows; a new history request can
show later proposals.

### Backlog task API and save contract

The authenticated, project-authorized task endpoints are:

- `GET /api/projects/{project_id}/backlog/tasks` returns the current saved
  `BACKLOG.md` content, digest and `revision_number`, parsed tasks, and a summary.
- `POST /api/projects/{project_id}/backlog/tasks` adds a task. Supply
  `expected_revision`, permanent `id`, one-line `title`, and Markdown `body` with
  one `Depends on` declaration. The new task is always a draft (`[-]`).
- `PUT /api/projects/{project_id}/backlog/tasks/{task_id}` edits a planning task.
  Supply `expected_revision`, `status` (`"-"` for draft or `" "` for ready),
  `title`, and `body`; an optional `dependencies` list explicitly updates the
  declaration.
- `PUT /api/projects/{project_id}/documents/backlog` saves the complete Markdown
  document, with `expected_revision` and `content`.

Use the task view's `revision_number` as `expected_revision` for the next save.
`ready` means the task has the `[ ]` marker; `eligible` means it is ready and all
its prerequisites have `[x]`. A ready task can therefore still be waiting. Draft
(`[-]`), ready (`[ ]`), and dependency eligibility are distinct. This summary is
read-only; the IMP-014 task-list editor provides separate direct-edit and draft/ready
controls. Neither a ready marker nor eligibility approves the saved
backlog revision. Backlog approval/download is separate from these endpoints.

Task IDs are permanent; tasks cannot be deleted or renamed. New tasks need a
unique valid ID/title, exactly one valid `Depends on` declaration, and draft (`[-]`)
status, whether added through the task route or a whole-document save. Dependencies
must refer to existing tasks and cannot be self-referential or cyclic. Task edits
can move only between draft and ready. Runner-owned execution states (`[~]`, `[x]`,
`[!]`) and their task blocks are not editable through this API; existing
line-oriented `Branch:`/`PR:` metadata is runner-owned as well. Recognized compact,
spaced, bold, list and indented metadata lines must be preserved; incidental inline
prose or fenced examples mentioning those labels are not metadata. Whole-document
saves must preserve existing outcomes and metadata and cannot introduce that
metadata on a new task. The API follows the root `scripts/backlog.py` syntax and
eligibility contract with additional validation for safe editing.

Malformed backlog syntax, invalid task edits, or whole-document saves that try to
change protected content return HTTP 422 and do not save a revision. A valid write
based on an old `expected_revision` returns HTTP 409; the attempted document text
is kept as a conflict proposal rather than replacing the current head. A task PUT
against a runner-owned execution task is also rejected with HTTP 409 as read-only.
In particular, do not retry a validation error as if it were a stale-save
conflict.

The task editor separates a task body from a following non-task level-two (`##`)
heading, while the root helper scans the broader task interval for dependencies
and runner metadata. A dependency declaration in preserved section text is still
part of that task's parsed interval; use the `dependencies` field to change it
without editing the preserved text. Preserve the heading and its Markdown
boundary: an edit that would absorb or hide it (for example, by omitting a needed
line break) is rejected with 422 rather than silently repaired. A heading-looking
line inside a fenced code block is not a section boundary; keep fences balanced,
and do not append a task after an unclosed fence. A valid task may end at actual
end-of-file without a trailing newline when no later section would be merged.

### Human-only saved-pair review and approval

The IMP-013 candidate adds direct human editing and comparison of the saved
`PROJECT.md` and `AGENTS.md` drafts, followed by one approval bound to their exact
current revisions. A project owner or administrator may use this workflow; it
does not require or start an OpenCode session, model, or agent proposal. Approval
history records prior approved revision pairs. Editing either document creates a
new immutable revision and makes the current pair unapproved until the newly saved
pair is reviewed and explicitly approved. Approval records a human decision for
the validated saved pair; it does not certify that the decisions are true or
sufficient.

Draft saves may retain raw HTML as Markdown content, but its tags, attributes, and
descendant text never count as evidence for a required decision. The server uses
the bounded Markdown evidence grammar described in `PROJECT.md`: required section
headings must be present, and substantive text in section prose, list items, or
table data cells may supply decisions; headings alone do not. Ordinary emphasis,
inline-code values, and link labels may contribute. Fenced or indented code
examples, comments, attributes, destinations, image alt text, reference definitions,
markup-only content, ambiguous boundaries, and explicit undecided values cannot
satisfy required decisions. This is not an HTML/CSS visibility detector. The
check also rejects unchanged starter content, unresolved placeholders, and
remaining starter checklist/setup notes, but does not judge whether an otherwise
valid choice is substantively correct.

Approval is server-side and tied to the current pair. A failed content check
returns HTTP 422 with document-specific validation errors; a stale submitted
revision pair returns HTTP 409 with the latest saved pair rather than
approving a different version. Reconcile the comparison and explicitly retry;
stale conflicts do not discard either saved revision or unsaved editor text.
Only a successful explicit action creates an approval record. Status reflects
whether that recorded pair is still the current valid pair; previous approval
records remain in history after a later edit.

The API also mirrors current document heads as files named `PROJECT.md`,
`AGENTS.md`, and `BACKLOG.md` under an opaque project-ID directory in
`IMPOSTR_WORKSPACE_ROOT` (Compose currently mounts `/workspaces` as a bounded
256 MiB `tmpfs`, mode `0700`, with `noexec`, `nosuid`, and `nodev`). Workspace
directories use mode `0700` and document files mode `0600`, owned by the API user.
They are a disposable cache, not an agent workspace, approval surface, or source
of truth.
Authorized document reads rebuild the mirror from the current PostgreSQL heads.
Mirror write failures do not replace or roll back PostgreSQL data; the cache is
discarded and a later authorized read rebuilds it. The bounded cache can evict old
entries, so do not back it up or edit it as durable data.

The named `postgres-data` volume persists across ordinary `docker compose down`;
`down -v` removes it. Keep database backups outside the repository, protected
from other local users, and treat dumps as sensitive project/account data; do not
commit them. A copy of the workspace mirror
does not recover project ownership/history, and a database dump does not reproduce
uncommitted application code. Match the application/migration version when
restoring.

**Backup/restore status:** No backup/restore procedure or restore drill is
verified. The safe approach to test is a PostgreSQL-native archive (for example,
`pg_dump` in custom format) stored with owner-only permissions outside the repo,
restored with PostgreSQL tooling (for example, `pg_restore`) into a new, uniquely
named Compose project with a fresh volume. Do not use the live project volume as a
restore target or publish the test stack on the same front-door port. Verify
migration head `20260929_0005`, project ownership, all three current drafts,
revision/proposal/approval history, and normal authorization against synthetic
data; then
remove only that test project's resources and verify the original stack/data
remain untouched. These tool choices and steps are guidance, not verified
commands. Record the recovery drill as unverified until actually exercised. Do not
use Alembic downgrade or `docker compose down -v` on the source stack as recovery.

## Restart, updates, and troubleshooting

- Restart the existing services without rebuilding: `docker compose -p
  impostr-verify1 restart`.
- After changing image inputs, rebuild with `docker compose -p impostr-verify1
  build`. If migrations changed, apply `docker compose -p impostr-verify1 run --rm
  api alembic upgrade head` before re-creating the API/front-door containers with
  `docker compose -p impostr-verify1 up -d`.
- Inspect state and logs with `docker compose -p impostr-verify1 ps` and
  `docker compose -p impostr-verify1 logs --tail=100 db api frontdoor`.
- If a service is unhealthy, inspect its logs and `.env` variable names/values
  locally; never paste passwords into an issue or log. Compose requires both
  `POSTGRES_PASSWORD` and `DB_PASSWORD` to be non-empty.
- If database health reports 503 during an outage, inspect the database logs,
  start the database, then wait for the API/front door health checks:

  ```sh
  docker compose -p impostr-verify1 logs --tail=100 db
  docker compose -p impostr-verify1 start db
  docker compose -p impostr-verify1 up -d
  curl --fail --silent --show-error http://127.0.0.1:8080/api/health
  ```

- Stop the stack with `docker compose -p impostr-verify1 down`. The named
  `postgres-data` volume persists by default. Do not use `down -v` for a stack
  containing data you need: it permanently removes that project's database
  volume. Use volume deletion only for an explicitly disposable, isolated test
  stack. Migration `0003` adds project document/revision/proposal tables and the
  owner-scoped name key; `0004` bounds that key; `0005` adds pair-approval records.
  These migrations have no verified backup/restore recovery procedure. Do not use
  a downgrade as routine recovery;
  downgrading `0005` drops approval records, and downgrading `0003` drops project
  document histories and conflict proposals. The database volume is persistent
  local storage, not a tested backup
  or durability guarantee.

## Release boundary

Compose binds the front door to loopback by default and does not publish the
database or API ports. This worktree includes account authentication,
administrator-managed accounts, project creation, private draft/revision history,
and human-only pair approval for `PROJECT.md` and `AGENTS.md`. The human-only
collapsible backlog editor supports title/body/dependency and `[-]`/`[ ]` readiness
edits with local-edit conflict preservation, review of the newer saved version,
and explicit reapplication. Stage 3 reviews the saved three-file tuple, records
final approval, and offers individual exact approved downloads; edits invalidate
that approval until the current tuple is reviewed and reapproved. IMP-014 and
IMP-010 candidate preflight/rendered acceptance passed locally; consult BACKLOG.md
for delivery references. It does not provide chat, agent proposals, runner outcomes,
or runner status editing, and has no agent gateway.
It has no TLS or domain setup, trusted external reverse-proxy/client-IP contract,
verified backup/restore runbook, complete release security gate, or verified agent
isolation. Do not expose it by changing the published binding, firewall, or proxy
configuration.
The agent-runtime gate remains blocked: installed OpenCode agents and a bare
`bwrap` namespace smoke test do not demonstrate a brokered, secret-safe isolated
integration. Do not infer shared-server readiness from local checks.
