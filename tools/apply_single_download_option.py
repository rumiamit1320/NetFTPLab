from pathlib import Path

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# Transfer-only normalization. Earlier patches may rebuild the remote item row,
# so support the concrete forms used by the existing Compose UI. Nothing here
# touches monitor, server, discovery, FTP workers, or transfer logic.
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

# Download All already exists in the current remote-files header. Accept any
# dynamic count expression and never create a duplicate button.
if 'Text("Download All (' not in text:
    raise SystemExit("Download All control is missing")

if individual not in text:
    raise SystemExit("Unable to locate remote item download action")

path.write_text(text, encoding="utf-8")
print("Final transfer download controls normalized; monitor/server/discovery untouched")
