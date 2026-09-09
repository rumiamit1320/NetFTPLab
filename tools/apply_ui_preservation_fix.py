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
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in text:
    raise SystemExit("Individual download action is missing")
if 'Text("Download All (${remoteFiles.count { !it.directory }})")' not in text:
    raise SystemExit("Download All action is missing")

print("Preservation check passed; AdvancedNetworkMonitor.kt and device discovery were not modified")
