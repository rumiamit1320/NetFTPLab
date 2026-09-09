from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = MAIN.read_text(encoding="utf-8")

# Transfer controls are generated in one place by apply_multi_file_transfer.py.
# Keep this late workflow step strictly verification-only so it cannot replace
# or regress the working transfer UI.
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in text:
    raise SystemExit("Individual file/folder download control is missing")
if 'Text("Download All (${selectableFiles.size})")' not in text:
    raise SystemExit("Download All control is missing")
if 'Text("Download ($selectedCount)")' not in text:
    raise SystemExit("Selected-download control is missing")

print("Final transfer correction verified; no monitor/server/discovery/source rewrite")
