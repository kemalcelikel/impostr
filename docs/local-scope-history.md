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

Earlier plans included PNG/JPEG, standalone UTF-8 text/Markdown and text-only DOCX
attachments. Owner narrowed the feature to text-readable PDFs, at most decimal
50 MB per file, no OCR/scanned-PDF support. Those other upload formats and live
image-understanding tests are removed, not unfinished gates for this version.

Local-use checks cover actual PDF workflow and restorable DB data, not GitHub
publication, remote deployment or multi-user qualification. Live-provider testing
remains deferred by owner; no automatic chat activation or host credential discovery.
Older project/task prose describing broader release gates is historical where it
conflicts with this decision. Keep prior outcomes and budgets intact.
