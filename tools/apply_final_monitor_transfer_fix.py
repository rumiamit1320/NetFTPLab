from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
s = MAIN.read_text(encoding="utf-8")

# Idempotent transfer-UI patch. Earlier workflow steps may already have
# converted the individual action into the full-width form. Never fail merely
# because that conversion has already happened.
all_text = 'Text("Download All (${remoteFiles.count { !it.directory }})")'
individual_text = 'Text(if (entry.directory) "Download Folder" else "Download File")'

# Add Download All only when it is not already present.
if all_text not in s:
    selected_row = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }'''
    all_block = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
'''
    if selected_row not in s:
        raise SystemExit("Unable to locate remote selected-download controls")
    s = s.replace(selected_row, all_block + '''                    Spacer(Modifier.height(6.dp))
''' + selected_row, 1)

# Convert the old compact individual action only when it is actually present.
# If the full-width form is already present, leave it completely untouched.
if individual_text not in s:
    raise SystemExit("Individual download action is missing")

full_width_marker = '''Button(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }'''
if full_width_marker not in s:
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

# Hard verification.
if all_text not in s:
    raise SystemExit("Download All control missing")
if individual_text not in s:
    raise SystemExit("Individual download control missing")

MAIN.write_text(s, encoding="utf-8")
print("Transfer download controls verified/normalized; no monitor/server/discovery changes")
