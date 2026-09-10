from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def require_once(text: str, marker: str, block: str) -> str:
    if block.strip() in text:
        return text
    if marker not in text:
        raise SystemExit(f"marker not found: {marker!r}")
    return text.replace(marker, block + "\n" + marker, 1)


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # State for the destructive confirmation dialog.
    s = require_once(
        s,
        '    private var showQr by mutableStateOf(false)',
        '    private var showClearServerDialog by mutableStateOf(false)'
    )

    # Keep all server-storage operations confined to serverRoot. Nothing outside
    # the embedded FTP server directory can be deleted by these controls.
    helper = '''    private fun serverStorageBytes(): Long = serverFiles.sumOf { file ->
        if (file.isDirectory) file.walkTopDown().filter { it.isFile }.sumOf { it.length() } else file.length()
    }

    private fun formatStorageBytes(bytes: Long): String {
        if (bytes < 1024L) return "$bytes B"
        if (bytes < 1024L * 1024L) return "%.1f KB".format(Locale.US, bytes / 1024.0)
        if (bytes < 1024L * 1024L * 1024L) return "%.1f MB".format(Locale.US, bytes / (1024.0 * 1024.0))
        return "%.2f GB".format(Locale.US, bytes / (1024.0 * 1024.0 * 1024.0))
    }

    private fun openServerStorage() {
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            }
            startActivity(intent)
            log("SERVER", "Opened Android storage picker for server storage")
        } catch (e: Exception) {
            log("ERROR", "Could not open storage browser: ${e.message}")
        }
    }

    private fun clearServerStorage() {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val root = serverRoot.canonicalFile
                val children = root.listFiles()?.toList().orEmpty()
                var deleted = 0
                var failed = 0
                for (child in children) {
                    val target = child.canonicalFile
                    if (!target.path.startsWith(root.path + File.separator)) {
                        failed++
                        continue
                    }
                    if (target.deleteRecursively()) deleted++ else failed++
                }
                withContext(Dispatchers.Main) {
                    refreshServerFiles()
                    transfer = TransferState(message = if (failed == 0) "Server storage cleared" else "Cleared $deleted item(s); $failed could not be removed")
                    log("SERVER", "Server storage cleared: $deleted item(s), $failed failed")
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    transfer = TransferState(message = "Clear server storage failed: ${e.message}")
                    log("ERROR", "Clear server storage failed: ${e.message}")
                }
            }
        }
    }
'''
    s = require_once(s, '    private fun deleteServerFile(file: File) {', helper)

    # Add a dedicated storage-management card to the existing Server tab.
    marker = '''            Spacer(Modifier.height(10.dp))
            Text("PHONE ↔ LAPTOP", style = MaterialTheme.typography.titleMedium)'''
    card = '''            Spacer(Modifier.height(10.dp))
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("SERVER STORAGE", style = MaterialTheme.typography.titleMedium)
                    Text("${serverFiles.size} item(s) • ${formatStorageBytes(serverStorageBytes())} stored in NetFTPShare")
                    Text("These are the copies kept by the phone FTP server. Clearing them does not delete the original files elsewhere on the phone.")
                    Spacer(Modifier.height(8.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        OutlinedButton(
                            onClick = { openServerStorage() },
                            modifier = Modifier.weight(1f)
                        ) { Text("Open Storage") }
                        Button(
                            onClick = { showClearServerDialog = true },
                            enabled = serverFiles.isNotEmpty(),
                            modifier = Modifier.weight(1f)
                        ) { Text("Clear All") }
                    }
                }
            }

            if (showClearServerDialog) {
                AlertDialog(
                    onDismissRequest = { showClearServerDialog = false },
                    title = { Text("Clear server storage?") },
                    text = {
                        Text("This will permanently delete ${serverFiles.size} item(s) (${formatStorageBytes(serverStorageBytes())}) stored by the phone FTP server. Original files outside NetFTPShare will not be deleted.")
                    },
                    confirmButton = {
                        TextButton(onClick = {
                            showClearServerDialog = false
                            clearServerStorage()
                        }) { Text("Clear") }
                    },
                    dismissButton = {
                        TextButton(onClick = { showClearServerDialog = false }) { Text("Cancel") }
                    }
                )
            }

'''
    if 'Text("SERVER STORAGE", style = MaterialTheme.typography.titleMedium)' not in s:
        if marker not in s:
            raise SystemExit("Server tab insertion marker not found")
        s = s.replace(marker, card + marker, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("Added safe FTP server storage management controls")


if __name__ == "__main__":
    main()
