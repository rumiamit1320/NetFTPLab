from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Required marker not found: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # The server-status animation is a UI element only. Keep exactly one
    # instance; do not alter FtpServer or any networking/server lifecycle code.
    duplicate_animation = '''            ServerStatusAnimation(serverRunning)\n            Spacer(Modifier.height(4.dp))\n            ServerStatusAnimation(serverRunning)\n'''
    single_animation = '''            ServerStatusAnimation(serverRunning)\n'''
    if duplicate_animation in s:
        s = s.replace(duplicate_animation, single_animation, 1)

    start = s.find("    @Composable\n    private fun TransfersTab() {")
    end = s.find("\n    private fun copyConsoleLog()", start)
    if start < 0 or end < 0:
        raise SystemExit("TransfersTab markers not found")

    transfers_tab = '''    @Composable
    private fun TransfersTab() {
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
                            ) { Text("Upload") }
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
                Text("Tap a remote file to download it to the phone.")
            }

            items(remoteFiles) { entry ->
                Card(
                    Modifier.fillMaxWidth().clickable(
                        enabled = connectedTarget.isNotBlank() && !entry.directory
                    ) { download(entry) }
                ) {
                    Row(
                        Modifier.padding(14.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
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

    s = s[:start] + transfers_tab + s[end:]
    MAIN.write_text(s, encoding="utf-8")
    print("Transfer tab made fully scrollable; server animation kept UI-only")


if __name__ == "__main__":
    main()
