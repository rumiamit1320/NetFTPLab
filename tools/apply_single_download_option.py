from pathlib import Path

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# Final transfer-only normalization. Earlier workflow steps can rebuild the
# TransfersTab() with different row shapes. Do not depend on a particular
# OutlinedButton/Card layout; anchor only on the remote-file LazyColumn.
# Nothing outside the Transfer-tab download controls is changed here.

list_markers = [
    'items(remoteFiles, key = { "remote-${it.path}" }) { entry ->',
    'items(remoteFiles) { entry ->',
]
marker = next((m for m in list_markers if m in text), None)
if marker is None:
    raise SystemExit("Unable to locate remote file list")

# Ensure exactly one Download All action immediately before the remote list.
if 'Text("Download All (' not in text:
    block = '''                item {
                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = connectedTarget.isNotBlank() && remoteFiles.any { !it.directory } && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Download All (${remoteFiles.count { !it.directory }})")
                    }
                }
'''
    text = text.replace(marker, block + marker, 1)

# Ensure an individual action exists without assuming the previous row layout.
# If an older script already supplied one, leave it untouched. Otherwise put a
# full-width action at the start of each remote-item lambda, before its Card.
individual = 'Text(if (entry.directory) "Download Folder" else "Download File")'
if individual not in text:
    action = '''                Button(
                    onClick = { queueDownloads(listOf(entry)) },
                    enabled = connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(if (entry.directory) "Download Folder" else "Download File")
                }
'''
    text = text.replace(marker, marker + "\n" + action, 1)

if individual not in text:
    raise SystemExit("Unable to create remote item download action")
if 'Text("Download All (' not in text:
    raise SystemExit("Unable to create Download All control")

path.write_text(text, encoding="utf-8")
print("Final transfer download controls normalized; monitor/server/discovery untouched")
