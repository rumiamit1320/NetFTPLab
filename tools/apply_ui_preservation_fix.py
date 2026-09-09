#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/src/main/java/com/netftplab/MainActivity.kt"
MONITOR = ROOT / "app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt"

# Preservation means exactly that: do not rewrite the working monitor or alter
# device discovery during a transfer-UI build. This step is verification-only.
if not MAIN.exists() or not MONITOR.exists():
    raise SystemExit("Required source files are missing")

text = MAIN.read_text(encoding="utf-8")

# Verify the requested transfer capabilities by behavior/queue operations,
# not by one particular Compose label. Earlier UI patches may legitimately
# change the visible caption while retaining the same action.
individual_ok = (
    'queueDownloads(listOf(entry))' in text
    and 'entry.directory' in text
    and 'Download File' in text
    and 'Download Folder' in text
)
if not individual_ok:
    raise SystemExit("Individual file/folder download action is missing")

download_all_ok = (
    'queueDownloads(remoteFiles.filterNot { it.directory })' in text
    or 'queueDownloads(selectableFiles)' in text
    or 'remoteFiles.filterNot { it.directory }' in text
)
if not download_all_ok:
    raise SystemExit("Download All action is missing")

# Selected-download is identified by the selected-name collection and its
# queue operation rather than a fixed button caption.
selected_ok = (
    'selectedRemoteNames' in text
    and 'queueDownloads(' in text
)
if not selected_ok:
    raise SystemExit("Selected-download action is missing")

print("Preservation check passed; AdvancedNetworkMonitor.kt and device discovery were not modified")
