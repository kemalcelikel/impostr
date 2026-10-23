# Removed first-version access and attachment scope

Owner removed private HTTPS/phone/LAN access from the current version after IMP-005
delivery. IMP-016 is cancelled, retaining its original blocked/provisioning history
in BACKLOG.md. Do not provision a proxy/certificate/firewall or expose raw LAN HTTP.
Any future remote access needs a new owner request and measured setup.

**Latest IMP-025 runner stop (2026-10-22):** Native repairs3/3 exhausted after reviewed
receiver cleanup fix/76 pure tests. Actual209-input build/PG preservation/fencing/race/
migration0012/API/static passed; first native turn failed `native_stream_invalid`, cause
unknown. All owned cleanup passed twice; full candidate remains uncommitted/undelivered.
Runtime-only1/3 used is separate, not native renewal; OpenCode version/hash unlock stays.
Further general native repair needs bounded owner scope;026/027/011 remain blocked.

**Earlier text-extraction scope, superseded by the native replacement below:**
Earlier plans included PNG/JPEG, standalone UTF-8 text/Markdown and text-only DOCX
attachments. Owner narrowed the feature to text-readable PDFs, at most decimal
50 MB per file, no OCR/scanned-PDF support. Those other upload formats and live
image-understanding tests are removed, not unfinished gates for this version.

Local-use checks cover actual PDF workflow and restorable DB data, not GitHub
publication, remote deployment or multi-user qualification. Live-provider testing
remains deferred by owner; no automatic chat activation or host credential discovery.
Older project/task prose describing broader release gates is historical where it
conflicts with this decision. Keep prior outcomes and budgets intact.

## Native PDF replacement approved 2026-10-13

Owner requested removal of unnecessary local PDF processing after public documentation
and pinned OpenCode source confirmed a native file-input route. Azure lists
`gpt-6.1-sol` as a text/image Responses model; its Responses API accepts PDF input and
supplies extracted text plus page images. OpenCode 1.18.34 attaches PDFs natively.
This is documented support, not a live test of the owner's deployment.

The new target is private original upload → explicit OpenCode PDF attachment → existing
trusted host model relay → Azure Responses. Local qpdf/pdftotext, structural parsing,
inner parser sandbox, extraction jobs/retries and text-coverage preview are retired by
IMP-027 after IMP-025 native handoff and IMP-026 composer pass. PDFs remain the only
upload format. Text-readable-only rejection/coverage rules are removed; provider-side
scan/diagram handling is possible, not a local OCR or guaranteed-fidelity feature.

Azure documents each file under 50 MB and 50 MB combined in a request. PROJECT.md uses
a conservative decimal interpretation: original and combined originals each less than
50,000,000 bytes, including retained history; this tightens the former inclusive file
limit by one byte and adds an aggregate native request bound. Base64/JSON/context bounds
must be implemented, not inferred from the old 128 KiB extracted-text allowance.

IMP-017 stays delivered (`ca09dc3`, `269710f`, `8925dfa`). IMP-018 is superseded without
acceptance; preserve its dirty code, phase-four5/5, phase-five2/5, additional repair3/3,
formatter checkpoint `58bee09` and earlier failures. New native outcomes get their own
explicit finite planning allocation, not renewed old attempts. IMP-011 follows retired
extractor/native delivery and restores originals/metadata rather than extracted text.

No implementation, automatic launch, live-provider test, host-auth discovery, Podman/sbx
migration, installation or publication is authorized by this planning edit. Existing
agent isolation, credential separation, authorization/deletion and Git limits remain.

## Exact OpenCode lock removed by owner 2026-10-22

After native IMP-025 stopped on installed1.19.0 versus reviewed1.18.34, owner explicitly
requested removing the OpenCode version requirement and a ready manual-runner handoff.
Only OpenCode's fixed release/executable-digest admission gates change. Keep other
runtime pins, safe fixed executable access, isolation/credential/config boundaries,
actual protocol checks and exact candidate/frozen source verification. Observed version
or digest is evidence, not a newly approved fixed pin; no per-update approval cycle.

The version/hash unlock remains in force; observed version and digest are not admission
pins, and no runtime cause is inferred. The runtime-only allocation is separate from
the native PDF budget. See `docs/local-development.md` for the latest IMP-025 outcome.
No installation, host auth/config inspection, automatic start or push/PR follows.

## Simplicity and native event fix (2026-10-22)

Owner asked to prioritize simplicity and fix the known PDF event mismatch. Reuse the
SDK, existing relay and fixtures; no new parser, diagnostic framework, service or
compatibility layer. Check actual changed behavior and realistic risks, not mandatory
full matrices/reviews per edit. Keep privacy, authorization, deletion and migration
rules. Prior AGENTS.md and duplicate implementation narrative moved to
docs/agent-history.md; stable task IDs, budgets and delivered history remain intact.

The narrow documented-event metadata repair passed actual native PDF verification and
was delivered with the preserved backend in `a966d77`. New fix1/3 used; originalnative3/3
and runtime-only1/3 preserved. Native composer, extractor retirement and restored local
workflow remain026→027→011; live-model acceptance stays owner-deferred. No automatic
runner/application start, host installation or publication.

## Composer repair and owner-deferred manual testing (2026-10-22)

Owner asked for actual fixture/composer repair, then explicitly stopped additional
automated/browser testing and chose manual acceptance once implementation is finished.
Composer and owned cleanup are delivered in `34dbcb0`: existing web/static/review
evidence was reused, retained empty fixture state was safely removed, and a new fixture
startup/normal Member UI/shutdown completed with owned cleanup. New recovery2/3 used;
old0262/3 and all earlier histories remain. Extra upload/narrow/reconnect/full-app
browser evidence is deferred, not passed and not a queue gate. No copying/transmission
of denied staging files or broader tool permissions was authorized. Continue approved
extractor retirement/local workflow-restore implementation; retain data/privacy
requirements and later owner/provider acceptance. No automatic runner start or push/PR.

## Final packaging and stop instruction (2026-10-22)

Owner explicitly requested finishing without more testing, verification, loops or
comparator refinements. Extractor retirement is committed in `d05233f`; private human
backup/fresh-target restore in `756a3c8`. Original PDFs/history are preserved; no local
parser or host PostgreSQL install remains. The implementation queue through IMP-011
is complete under owner-deferred manual acceptance, not claimed automated completion.

Actual synthetic backup/restore transport and app-role ownership succeeded. Full
constraint comparison remains unresolved; populated-target refusal/rollback and full
restored-read acceptance were not completed by the halted drill. Existing guarded
implementation/review and all attempts remain recorded. No further check/review loop,
provider test, runner/application start, installation or publication follows.

## IMP-025 native stream outcome (latest session)

The actual 209-input synthetic candidate fingerprint
`28b707dc703a2addb08491bf89e98eb678c6907ba945bfae7ee405be5bf23e53` passed build,
fresh PostgreSQL preservation/legacy-fence/send-constraint/capture-delete checks,
migration `0012`, focused API, Ruff lint/format and mypy. Native order failed at
`wait_terminal`: `turn_failed`, durable reason `native_stream_invalid`; its cause is
unestablished. The receiver `.close` list-iterator repair was tested and independently
approved; 76 pure tests passed. Owned cleanup passed twice. No native receiver-byte,
history, follow-up, near-bound, outage or purge acceptance was obtained. The original
native allocation is exhausted at 3/3; runtime-only 1/3 cannot be used as general PDF
renewal. Candidate work remains dirty/uncommitted and IMP-025 is undelivered, so
IMP-026/027/011 remain blocked. Do not reinstate an OpenCode version/hash pin or
attribute the failure to runtime without evidence.
