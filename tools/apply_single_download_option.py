from pathlib import Path
import re

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# This is the last transfer-control normalization step. Earlier reliability and
# visual patches may leave a compact per-item Download action. Normalize that
# action without touching the transfer workers or protocol code.
individual = 'Text(if (entry.directory) "Download Folder" else "Download File")'
if individual not in text:
    old_compact = '''                            OutlinedButton(\n                                onClick = { queueDownloads(listOf(entry)) },\n                                enabled = !downloadQueueRunning && !uploadQueueRunning\n                            ) { Text("Download") }'''
    if old_compact in text:
        text = text.replace(old_compact, '''                            Button(\n                                onClick = { queueDownloads(listOf(entry)) },\n                                enabled = !downloadQueueRunning && !uploadQueueRunning,\n                                modifier = Modifier.fillMaxWidth()\n                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }''', 1)
    else:
        old_icon = '''                            if (!entry.directory) IconButton(onClick = { queueDownloads(listOf(entry)) }, enabled = !downloadQueueRunning) { Icon(Icons.Default.Download, "Download") }'''
        if old_icon in text:
            text = text.replace(old_icon, '''                            Button(\n                                onClick = { queueDownloads(listOf(entry)) },\n                                enabled = !downloadQueueRunning && !uploadQueueRunning,\n                                modifier = Modifier.fillMaxWidth()\n                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }''', 1)

# Add the Download All action immediately before the remote-item list. This
# location is inside the existing scrollable LazyColumn and does not replace
# any other Transfer-tab functionality.
all_text = 'Text("Download All (${selectableFiles.size})")'
if all_text not in text:
    marker = '            items(remoteFiles) { entry ->'
    block = '''            item {\n                Button(\n                    onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },\n                    enabled = connectedTarget.isNotBlank() && remoteFiles.any { !it.directory } && !downloadQueueRunning && !uploadQueueRunning,\n                    modifier = Modifier.fillMaxWidth()\n                ) { Text("Download All (${selectableFiles.size})") }\n            }\n\n'''
    if marker not in text:
        raise SystemExit("Unable to locate remote file list")
    text = text.replace(marker, block + marker, 1)

if individual not in text:
    raise SystemExit("Individual file/folder download control is missing")
if all_text not in text:
    raise SystemExit("Download All control is missing")

path.write_text(text, encoding="utf-8")
print("Final transfer download controls normalized; monitor/server/discovery untouched")
