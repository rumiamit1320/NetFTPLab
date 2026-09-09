#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/src/main/java/com/netftplab/MainActivity.kt"
MONITOR = ROOT / "app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt"

# Restore the exact monitor implementation that was present immediately before this UI repair.
GOOD_MONITOR_COMMIT = "5e6ce02a00c719fa1995180a00411d8d5d019008"
proc = subprocess.run(["git", "show", f"{GOOD_MONITOR_COMMIT}:app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt"], cwd=ROOT, text=True, capture_output=True, check=False)
if proc.returncode != 0 or not proc.stdout.strip():
    raise SystemExit("Unable to restore working AdvancedNetworkMonitor.kt")
MONITOR.write_text(proc.stdout, encoding="utf-8")

text = MAIN.read_text(encoding="utf-8")

# Remove only the temporary ARP-neighbor addition; preserve the original service scan.
text = re.sub(r'\n    private fun arpNeighborIps\(\): Set<String> \{.*?\n    \}\n', '\n', text, count=1, flags=re.S)
text = text.replace('            val neighborIps = arpNeighborIps().filter { it.startsWith("$subnet.") }.toSet()\n', '', 1)
text = re.sub(r'            val serviceIps = found\.map \{ it\.ip \}\.toSet\(\)\n            neighborIps\.filter \{ it != localIpv4\(\) && it !in serviceIps \}\.forEach \{ ip ->\n                found \+= Device\(ip, host = "Unknown", services = emptyList\(\), latencyMs = null\)\n            \}\n            withContext\(Dispatchers\.Main\) \{\n                discovered\.addAll\(found\.distinctBy \{ it\.ip \}\.sortedBy \{ it\.ip\.substringAfterLast\('\.'\)\.toIntOrNull\(\) \?: 999 \}\)\n                log\("DISCOVERY", "Scan complete: \$\{found\.size\} LAN devices/neighbors; \$\{serviceIps\.size\} service-bearing"\)\n                scanning = false\n            \}', '''            withContext(Dispatchers.Main) {
                discovered.addAll(found.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 })
                log("DISCOVERY", "Scan complete: ${found.size} active service-bearing devices")
                scanning = false
            }''', text, count=1, flags=re.S)

# The transfer controls are already present in the current source. Fail rather than touching other UI if they ever disappear.
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in text:
    raise SystemExit("Individual download action is missing; refusing to modify unrelated UI")
if 'Text("Download All (${remoteFiles.count { !it.directory }})")' not in text:
    raise SystemExit("Download All action is missing; refusing to modify unrelated UI")

MAIN.write_text(text, encoding="utf-8")
print("Preserved existing monitor/device/transfer architecture; verified download controls")
