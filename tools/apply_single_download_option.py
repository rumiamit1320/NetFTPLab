from pathlib import Path

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

old = '''                            if (!entry.directory) IconButton(onClick = { queueDownloads(listOf(entry)) }, enabled = !downloadQueueRunning) { Icon(Icons.Default.Download, "Download") }'''
new = '''                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text("Download") }'''

if new in text:
    print("Single download action already present; no change needed")
elif old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Added explicit single-item Download button to remote Transfer tab")
else:
    raise SystemExit("Expected remote-item download action marker not found; refusing to modify source")
