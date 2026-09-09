from pathlib import Path

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# This is the final transfer-only normalization step. Several older UI scripts
# rebuild TransfersTab(), so this step deliberately repairs only the two
# requested download controls after those scripts have run. It does not touch
# monitor, server, discovery, FTP workers, or transfer logic.

individual = 'Text(if (entry.directory) "Download Folder" else "Download File")'
if individual not in text:
    old = '''                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }'''
    new = '''                            Button(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }'''
    if old in text:
        text = text.replace(old, new, 1)
    else:
        old = '''                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }'''
        if old in text:
            text = text.replace(old, new, 1)

if individual not in text:
    raise SystemExit("Unable to locate remote item download action")

# Ensure exactly one Download All action immediately before the remote item
# list. The current UI uses a keyed items(remoteFiles, ...) call.
if 'Text("Download All (' not in text:
    marker = '                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->'
    block = '''                item {
                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
                }
'''
    if marker not in text:
        raise SystemExit("Unable to locate remote file list")
    text = text.replace(marker, block + marker, 1)

if 'Text("Download All (' not in text:
    raise SystemExit("Download All control is missing")

path.write_text(text, encoding="utf-8")
print("Final transfer download controls normalized; monitor/server/discovery untouched")
