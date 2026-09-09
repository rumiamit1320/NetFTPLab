from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = MAIN.read_text(encoding="utf-8")

# Final transfer-only normalization. Earlier workflow steps can rebuild the
# TransfersTab() with different row shapes. Normalize the remote item block here
# so every remote entry has exactly ONE visible full-width download button.
# Nothing in the monitor, server, discovery, FTP client, or queue workers is
# changed by this script.

list_markers = [
    '                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->',
    '                items(remoteFiles) { entry ->',
]
marker = next((m for m in list_markers if m in text), None)
if marker is None:
    raise SystemExit("Unable to locate remote file list")

# Ensure Download All exists immediately before the remote list.
if 'queueDownloads(remoteFiles.filterNot { it.directory })' not in text:
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

# Replace only the remote item lambda. This removes the duplicate IconButton and
# the previously inserted button outside the Card, while preserving selection,
# file metadata, and the existing queueDownloads() operation.
item_start = text.find(marker)
else_marker = '            } else {'
item_end = text.find(else_marker, item_start)
if item_start < 0 or item_end < 0:
    raise SystemExit("Unable to locate remote item section")

remote_items = '''                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->
                    val checked = entry.path in selectedRemoteNames
                    Card(Modifier.fillMaxWidth()) {
                        Column(
                            Modifier.padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = {
                                        if (it) {
                                            if (entry.path !in selectedRemoteNames) selectedRemoteNames.add(entry.path)
                                        } else {
                                            selectedRemoteNames.remove(entry.path)
                                        }
                                    }
                                )
                                Icon(
                                    if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile,
                                    null
                                )
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(entry.name)
                                    Text(if (entry.directory) "Folder" else "${entry.size} bytes")
                                }
                            }
                            Button(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Icon(Icons.Default.Download, null)
                                Spacer(Modifier.width(6.dp))
                                Text(if (entry.directory) "Download Folder" else "Download File")
                            }
                        }
                    }
                }
'''

text = text[:item_start] + remote_items + text[item_end:]

# Verify the final source contains exactly one individual button implementation
# inside the remote list and one Download All action.
if text.count('Text(if (entry.directory) "Download Folder" else "Download File")') != 1:
    raise SystemExit("Remote item download control was not normalized to exactly one")
if 'queueDownloads(listOf(entry))' not in text:
    raise SystemExit("Individual file/folder download action is missing")
if 'queueDownloads(remoteFiles.filterNot { it.directory })' not in text:
    raise SystemExit("Download All action is missing")

MAIN.write_text(text, encoding="utf-8")
print("Remote transfer controls normalized: one Download File/Folder button per item plus Download All; monitor/server/discovery untouched")
