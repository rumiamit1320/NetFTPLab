from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")

s = MAIN.read_text(encoding="utf-8")

# The previous patch could place Download All between the closing brace of
# the REMOTE FILES item and items(remoteFiles,...). That makes Button/Spacer
# execute outside a LazyColumn item scope and causes the Compose compiler error.
# Normalize the Download All block and put it inside the existing item block.
all_block = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
'''

# Remove every standalone Download All block first, including the malformed
# version produced by the earlier patch. This is intentionally idempotent.
s = re.sub(
    r'(?m)^\s{20}Button\(\n'
    r'\s{24}onClick = \{ queueDownloads\(remoteFiles\.filterNot \{ it\.directory \}\) \},\n'
    r'\s{24}enabled = remoteFiles\.any \{ !it\.directory \} && connectedTarget\.isNotBlank\(\) && !downloadQueueRunning && !uploadQueueRunning,\n'
    r'\s{24}modifier = Modifier\.fillMaxWidth\(\)\n'
    r'\s{20}\) \{ Text\("Download All \(\$\{remoteFiles\.count \{ !it\.directory \}\}\)"\) \}\n',
    '',
    s,
)

remote_items = '                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->'
if remote_items not in s:
    raise SystemExit("Unable to locate remote file list")

# Insert the button immediately before the selected-item action row, while
# still inside the existing LazyColumn item. This preserves the existing UI
# structure and queue architecture.
selected_row = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }'''
if selected_row in s:
    s = s.replace(selected_row, all_block + '''                    Spacer(Modifier.height(6.dp))
''' + selected_row, 1)
else:
    # Compatible fallback: insert just before the remote items list, which is
    # outside the item block, is NOT safe. Therefore locate the REMOTE FILES
    # item and its closing boundary using the existing selected-action text.
    raise SystemExit("Unable to locate remote selected-download controls")

# Ensure each remote entry retains an explicit action for both files and folders.
old_download = ') { Text("Download") }'
new_download = ') { Text(if (entry.directory) "Download Folder" else "Download File") }'
if 'onClick = { queueDownloads(listOf(entry)) }' in s:
    s = s.replace(old_download, new_download, 1)
else:
    entry_text = '''                            Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }'''
    individual = '''                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }
'''
    if entry_text not in s:
        raise SystemExit("Unable to locate remote entry rendering block")
    s = s.replace(entry_text, entry_text + '\n' + individual, 1)

MAIN.write_text(s, encoding="utf-8")
print("Transfer download controls normalized inside LazyColumn item scope")
