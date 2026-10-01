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

## Operator-only chat-safety prototype (IMP-002)

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
chat, tool/question/proposal, or release acceptance. IMP-002 remains blocked; this
result does not authorize an operator rerun, runner launch, or new scope.

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
`0700`; the fixture creates handoff files as mode `0600`. If tool permissions for
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
owned by the operator with mode `0700` and available through the permitted file
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
