from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main():
    s = MAIN.read_text(encoding="utf-8")

    # Normalize queue loops for Kotlin/JVM compatibility.
    s = s.replace(
        "val uri = uploadQueue.removeFirstOrNull() ?: break",
        "if (uploadQueue.isEmpty()) break\n                val uri = uploadQueue.removeFirst()",
    )
    s = s.replace(
        "val entry = downloadQueue.removeFirstOrNull() ?: break",
        "if (downloadQueue.isEmpty()) break\n                val entry = downloadQueue.removeFirst()",
    )
    s = s.replace(
        "val uri = if (uploadQueue.isEmpty()) break\n                uploadQueue.removeFirst()",
        "if (uploadQueue.isEmpty()) break\n                val uri = uploadQueue.removeFirst()",
    )
    s = s.replace(
        "val entry = if (downloadQueue.isEmpty()) break\n                downloadQueue.removeFirst()",
        "if (downloadQueue.isEmpty()) break\n                val entry = downloadQueue.removeFirst()",
    )
    s = s.replace("                    return@downloadNow\n", "                    return\n")
    s = s.replace("                    return@launch\n", "                    return\n")

    # Replace the transfer list with a selectable multi-file UI while keeping
    # the existing persistent FTP client and queue workers unchanged.
    start_marker = "    @Composable\n    private fun TransfersTab() {\n"
    end_marker = "    private fun copyConsoleLog() {\n"
    start = s.find(start_marker)
    end = s.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("TransfersTab markers not found")

    transfers = r'''    @Composable
    private fun TransfersTab() {
        val selectableFiles = remoteFiles.filterNot { it.directory }
        val selectedCount = selectedRemoteNames.size

        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text("FTP CLIENT CONNECTION", style = MaterialTheme.typography.labelLarge)
                        Text(
                            if (connectedTarget.isBlank()) "NOT CONNECTED" else "CONNECTED • $connectedTarget",
                            style = MaterialTheme.typography.titleMedium
                        )
                        if (connectedTarget.isBlank()) {
                            Text("Select an FTP device from Devices to enable client transfers.")
                        } else {
                            Text("Control channel: TCP ${connectedTarget.substringAfter(':')}")
                            Text("Remote directory: ${remoteFiles.size} entries")
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Button(
                                onClick = { uploadDocument.launch(arrayOf("*/*")) },
                                enabled = connectedTarget.isNotBlank(),
                                modifier = Modifier.weight(1f)
                            ) { Text("Upload files") }
                            OutlinedButton(
                                onClick = { refreshRemote() },
                                enabled = connectedTarget.isNotBlank(),
                                modifier = Modifier.weight(1f)
                            ) { Text("Refresh") }
                            OutlinedButton(
                                onClick = { disconnect() },
                                enabled = connectedTarget.isNotBlank(),
                                modifier = Modifier.weight(1f)
                            ) { Text("Disconnect") }
                        }
                    }
                }
            }

            if (transfer.active || transfer.message != "Idle") {
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text("${transfer.direction}: ${transfer.name}")
                            if (transfer.total > 0) {
                                LinearProgressIndicator(
                                    progress = {
                                        (transfer.done.toFloat() / transfer.total).coerceIn(0f, 1f)
                                    },
                                    modifier = Modifier.fillMaxWidth()
                                )
                            }
                            Text("${transfer.message} • ${transfer.done}/${transfer.total} bytes • ${transfer.speedBps} B/s")
                            if (transfer.sha256Local.isNotBlank()) Text("SHA-256 local: ${transfer.sha256Local}")
                            if (transfer.sha256Remote.isNotBlank()) Text("SHA-256 remote: ${transfer.sha256Remote}")
                            transfer.verified?.let {
                                Text(if (it) "Integrity: VERIFIED" else "Integrity: MISMATCH")
                            }
                        }
                    }
                }
            }

            item {
                Text("REMOTE FILES", style = MaterialTheme.typography.titleMedium)
                Text("Select one or more files, then download them sequentially over the existing FTP connection.")
                Spacer(Modifier.height(6.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    OutlinedButton(
                        onClick = {
                            selectedRemoteNames.clear()
                            selectedRemoteNames.addAll(selectableFiles.map { it.name })
                        },
                        enabled = selectableFiles.isNotEmpty(),
                        modifier = Modifier.weight(1f)
                    ) { Text("Select all") }
                    OutlinedButton(
                        onClick = { selectedRemoteNames.clear() },
                        enabled = selectedCount > 0,
                        modifier = Modifier.weight(1f)
                    ) { Text("Clear") }
                    Button(
                        onClick = {
                            val chosen = remoteFiles.filter { !it.directory && it.name in selectedRemoteNames }
                            queueDownloads(chosen)
                        },
                        enabled = connectedTarget.isNotBlank() && selectedCount > 0 && !downloadQueueRunning,
                        modifier = Modifier.weight(1f)
                    ) { Text("Download ($selectedCount)") }
                }
            }

            items(remoteFiles) { entry ->
                val checked = entry.name in selectedRemoteNames
                Card(
                    Modifier.fillMaxWidth().clickable(
                        enabled = connectedTarget.isNotBlank() && !entry.directory
                    ) {
                        if (checked) selectedRemoteNames.remove(entry.name)
                        else selectedRemoteNames.add(entry.name)
                    }
                ) {
                    Row(
                        Modifier.padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (!entry.directory) {
                            Checkbox(
                                checked = checked,
                                onCheckedChange = { value ->
                                    if (value) selectedRemoteNames.add(entry.name)
                                    else selectedRemoteNames.remove(entry.name)
                                }
                            )
                        } else {
                            Spacer(Modifier.width(48.dp))
                        }
                        Icon(
                            if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile,
                            null
                        )
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(entry.name)
                            Text(if (entry.directory) "Directory" else "${entry.size} bytes")
                        }
                    }
                }
            }
        }
    }

'''
    s = s[:start] + transfers + s[end:]
    MAIN.write_text(s, encoding="utf-8")
    print("Fixed queue compatibility and applied multi-file transfer selection UI")


if __name__ == "__main__":
    main()
