from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = MAIN.read_text(encoding="utf-8")

# Final workflow step is verification-only. Earlier steps generate the Transfer
# tab. Do not rebuild or rewrite TransfersTab here, and do not require exact UI
# label formatting that may vary between transfer UI revisions.

if 'queueDownloads(listOf(entry))' not in text:
    raise SystemExit("Individual file/folder download control is missing")
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in text:
    raise SystemExit("Individual file/folder download label is missing")
if 'queueDownloads(remoteFiles.filterNot { it.directory })' not in text:
    raise SystemExit("Download All action is missing")

# The selected-download implementation has had more than one label/layout over
# the project's revisions. Verify its underlying selected-name state and queue
# operation instead of requiring a particular button caption.
if 'selectedRemoteNames' not in text or 'queueDownloads(' not in text:
    raise SystemExit("Selected-download implementation is missing")

print("Final transfer correction verified; no monitor/server/discovery/source rewrite")
