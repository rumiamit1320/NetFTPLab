from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = MAIN.read_text(encoding="utf-8")

# This late workflow step must never rebuild TransfersTab(). Earlier workflow
# steps are responsible for generating the complete transfer UI. Here we only
# verify that the requested controls survived all preceding steps.
individual_markers = (
    'Text(if (entry.directory) "Download Folder" else "Download File")',
    'queueDownloads(listOf(entry))',
)
download_all_markers = (
    'Text("Download All (${selectableFiles.size})")',
    'queueDownloads(remoteFiles.filterNot { it.directory })',
    'remoteFiles.filterNot { it.directory }',
)
selected_marker = 'Text("Download ($selectedCount)")'

if not all(marker in text for marker in individual_markers):
    raise SystemExit("Individual file/folder download control is missing")
if not any(marker in text for marker in download_all_markers):
    raise SystemExit("Download All control is missing")
if selected_marker not in text:
    raise SystemExit("Selected-download control is missing")

print("Final transfer correction verified; no monitor/server/discovery/source rewrite")
