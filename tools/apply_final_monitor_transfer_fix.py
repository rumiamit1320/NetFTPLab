from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
s = MAIN.read_text(encoding="utf-8")

# Keep Download All inside the existing REMOTE FILES LazyColumn item.
all_block = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
'''
s = re.sub(
    r'(?m)^\s{20}Button\(\n'
    r'\s{24}onClick = \{ queueDownloads\(remoteFiles\.filterNot \{ it\.directory \}\) \},\n'
    r'\s{24}enabled = remoteFiles\.any \{ !it\.directory \} && connectedTarget\.isNotBlank\(\) && !downloadQueueRunning && !uploadQueueRunning,\n'
    r'\s{24}modifier = Modifier\.fillMaxWidth\(\)\n'
    r'\s{20}\) \{ Text\("Download All \(\$\{remoteFiles\.count \{ !it\.directory \}\}\)"\) \}\n',
    '', s
)
selected_row = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }'''
if selected_row not in s:
    raise SystemExit("Unable to locate remote selected-download controls")
s = s.replace(selected_row, all_block + '''                    Spacer(Modifier.height(6.dp))
''' + selected_row, 1)

# Make each individual download action a full-width row below the metadata.
# This avoids the narrow-phone layout clipping the action at the right edge.
old = '''                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = checked, onCheckedChange = { if (it) selectedRemoteNames.add(entry.path) else selectedRemoteNames.remove(entry.path) })
                            Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }
                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }
                        }'''
new = '''                        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                                Checkbox(checked = checked, onCheckedChange = { if (it) selectedRemoteNames.add(entry.path) else selectedRemoteNames.remove(entry.path) })
                                Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }
                            }
                            Button(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }
                        }'''
if old not in s:
    raise SystemExit("Unable to locate individual remote download row")
s = s.replace(old, new, 1)

# Hard verification: these controls must be present in the generated source.
if 'Text("Download All (${remoteFiles.count { !it.directory }})")' not in s:
    raise SystemExit("Download All control missing")
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in s:
    raise SystemExit("Individual download control missing")

MAIN.write_text(s, encoding="utf-8")
print("Made Download All and individual file/folder download controls full-width and visible; no monitor/server changes")
