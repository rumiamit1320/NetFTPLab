from pathlib import Path
import re

path = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# Final transfer-only normalization. Earlier patches can rebuild the remote
# item row, so match the actual current Compose structure rather than relying
# on an obsolete indentation/marker. Do not touch monitor, server, discovery,
# FTP workers, or transfer logic.
individual = 'Text(if (entry.directory) "Download Folder" else "Download File")'
if individual not in text:
    pattern = re.compile(
        r'''(?P<indent>\s*)OutlinedButton\(\s*\n'
        r'''(?P=indent)    onClick = \{ queueDownloads\(listOf\(entry\)\) \},\s*\n'
        r'''(?P=indent)    enabled = !downloadQueueRunning && !uploadQueueRunning\s*\n'
        r'''(?P=indent)\) \{ Text\(if \(entry\.directory\) "Download Folder" else "Download File"\) \}\s*'''
    )
    replacement = '''\\g<indent>Button(
\\g<indent>    onClick = { queueDownloads(listOf(entry)) },
\\g<indent>    enabled = !downloadQueueRunning && !uploadQueueRunning,
\\g<indent>    modifier = Modifier.fillMaxWidth()
\\g<indent>) { Text(if (entry.directory) "Download Folder" else "Download File") }
'''
    text, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        # Also support the older compact one-line form if a previous patch
        # leaves that form in the working tree.
        compact = re.compile(
            r'''(?P<indent>\s*)OutlinedButton\(onClick = \{ queueDownloads\(listOf\(entry\)\) \},\s*\n'
            r'''(?P=indent)    enabled = !downloadQueueRunning && !uploadQueueRunning\s*\n'
            r'''(?P=indent)\) \{ Text\(if \(entry\.directory\) "Download Folder" else "Download File"\) \}'''
        )
        text, count = compact.subn(replacement.rstrip("\\n"), text, count=1)
    if count == 0:
        raise SystemExit("Unable to locate remote item download action")

# Download All is already part of the remote-files header. Accept either the
# current dynamic count or the older selectable-files count; never insert a
# second Download All button.
if 'Text("Download All (' not in text:
    raise SystemExit("Download All control is missing")

if individual not in text:
    raise SystemExit("Individual file/folder download control is missing")

path.write_text(text, encoding="utf-8")
print("Final transfer download controls normalized; monitor/server/discovery untouched")
