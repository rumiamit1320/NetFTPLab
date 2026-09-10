from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = MAIN.read_text(encoding="utf-8")

# Keep the existing Transfer-tab layout and behavior. Only make the remote
# download section visible when remote entries are available; connection state
# continues to control whether download actions are enabled.
old = '''            if (clientMode) {
                item {
                    Text("REMOTE FILES", style = MaterialTheme.typography.titleMedium)'''
new = '''            if (clientMode || remoteFiles.isNotEmpty()) {
                item {
                    Text("REMOTE FILES", style = MaterialTheme.typography.titleMedium)'''
if old in text:
    text = text.replace(old, new, 1)
else:
    raise SystemExit("Remote files section marker not found")

if 'queueDownloads(listOf(entry))' not in text:
    raise SystemExit("Individual file/folder download control is missing")
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in text:
    raise SystemExit("Individual file/folder download label is missing")
if 'queueDownloads(remoteFiles.filterNot { it.directory })' not in text:
    raise SystemExit("Download All action is missing")
if 'selectedRemoteNames' not in text or 'queueDownloads(' not in text:
    raise SystemExit("Selected-download implementation is missing")

MAIN.write_text(text, encoding="utf-8")
print("Remote download section visibility corrected; no FTP/server/discovery/throughput changes")
