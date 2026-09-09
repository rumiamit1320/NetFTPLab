#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/src/main/java/com/netftplab/MainActivity.kt"
MONITOR = ROOT / "app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt"

# Restore the known-good real-time monitor implementation exactly.
GOOD_MONITOR_COMMIT = "3c08ec6351955f7c291d3da81652622d30b3aa29"
proc = subprocess.run(
    ["git", "show", f"{GOOD_MONITOR_COMMIT}:app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt"],
    cwd=ROOT, text=True, capture_output=True, check=False,
)
if proc.returncode != 0 or not proc.stdout.strip():
    raise SystemExit("Unable to restore known-good AdvancedNetworkMonitor.kt")
MONITOR.write_text(proc.stdout, encoding="utf-8")

text = MAIN.read_text(encoding="utf-8")

# Keep the existing TCP service scan and additionally show LAN neighbors
# already present in Android's ARP/neighbor table.
if "private fun arpNeighborIps()" not in text:
    marker = "    private fun localSubnet(): String? = localIpv4()?.substringBeforeLast('.')\n"
    helper = '''\n    private fun arpNeighborIps(): Set<String> {\n        return try {\n            File("/proc/net/arp").useLines { lines ->\n                lines.drop(1).mapNotNull { line ->\n                    val parts = line.trim().split(Regex("\\\\s+"))\n                    parts.firstOrNull()?.takeIf { ip ->\n                        ip.count { it == '.' } == 3 && ip != "0.0.0.0"\n                    }\n                }.toSet()\n            }\n        } catch (_: Exception) {\n            emptySet()\n        }\n    }\n'''
    if marker not in text:
        raise SystemExit("localSubnet marker not found")
    text = text.replace(marker, marker + helper, 1)

old = '''        lifecycleScope.launch(Dispatchers.IO) {\n            val found = Collections.synchronizedList(mutableListOf<Device>())\n            coroutineScope {'''
new = '''        lifecycleScope.launch(Dispatchers.IO) {\n            val found = Collections.synchronizedList(mutableListOf<Device>())\n            val neighborIps = arpNeighborIps().filter { it.startsWith("$subnet.") }.toSet()\n            coroutineScope {'''
if old in text:
    text = text.replace(old, new, 1)

old2 = '''            withContext(Dispatchers.Main) {\n                discovered.addAll(found.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 })\n                log("DISCOVERY", "Scan complete: ${found.size} active service-bearing devices")\n                scanning = false\n            }'''
new2 = '''            val serviceIps = found.map { it.ip }.toSet()\n            neighborIps.filter { it != localIpv4() && it !in serviceIps }.forEach { ip ->\n                found += Device(ip, host = "Unknown", services = emptyList(), latencyMs = null)\n            }\n            withContext(Dispatchers.Main) {\n                discovered.addAll(found.distinctBy { it.ip }.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 })\n                log("DISCOVERY", "Scan complete: ${found.size} LAN devices/neighbors; ${serviceIps.size} service-bearing")\n                scanning = false\n            }'''
if old2 not in text:
    raise SystemExit("scan completion block not found")
text = text.replace(old2, new2, 1)

# Put each individual download action on its own full-width row so it remains
# visible on narrow phone layouts. Download All/selected controls are untouched.
pattern = r'''                items\(remoteFiles, key = \{ "remote-\$\{it\.path\}" \}\) \{ entry ->.*?\n                \}\n            \} else \{'''
replacement = '''                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->\n                    val checked = entry.path in selectedRemoteNames\n                    Card(Modifier.fillMaxWidth()) {\n                        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {\n                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {\n                                Checkbox(checked = checked, onCheckedChange = {\n                                    if (it) {\n                                        if (entry.path !in selectedRemoteNames) selectedRemoteNames.add(entry.path)\n                                    } else {\n                                        selectedRemoteNames.remove(entry.path)\n                                    }\n                                })\n                                Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)\n                                Spacer(Modifier.width(10.dp))\n                                Column(Modifier.weight(1f)) {\n                                    Text(entry.name)\n                                    Text(if (entry.directory) "Folder" else "${entry.size} bytes")\n                                }\n                            }\n                            Button(\n                                onClick = { queueDownloads(listOf(entry)) },\n                                enabled = !downloadQueueRunning && !uploadQueueRunning,\n                                modifier = Modifier.fillMaxWidth()\n                            ) {\n                                Icon(Icons.Default.Download, null)\n                                Spacer(Modifier.width(6.dp))\n                                Text(if (entry.directory) "Download Folder" else "Download File")\n                            }\n                        }\n                    }\n                }\n            } else {'''
text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
if count != 1:
    raise SystemExit("remote file item block not found")
MAIN.write_text(text, encoding="utf-8")
print("Restored known-good monitor; preserved transfer controls; added LAN-neighbor visibility")
