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

    # State for the destructive confirmation dialog and the in-app server folder browser.
    s = require_once(
        s,
        '    private var showQr by mutableStateOf(false)',
        '    private var showClearServerDialog by mutableStateOf(false)\n    private var showDeleteTypeDialog by mutableStateOf(false)\n    private var serverBrowserPath by mutableStateOf("")'
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

    private fun serverRelativePath(file: File): String {
        val root = serverRoot.canonicalFile
        val target = file.canonicalFile
        if (target == root) return ""
        if (!target.path.startsWith(root.path + File.separator)) throw IOException("Unsafe server path")
        return target.relativeTo(root).path.replace(File.separatorChar, '/')
    }

    private fun serverFilesAt(relativePath: String): List<File> {
        val root = serverRoot.canonicalFile
        val current = if (relativePath.isBlank()) root else File(root, relativePath).canonicalFile
        if (current != root && !current.path.startsWith(root.path + File.separator)) throw IOException("Unsafe server path")
        return current.listFiles()?.sortedWith(compareBy<File> { !it.isDirectory }.thenBy(String.CASE_INSENSITIVE_ORDER) { it.name }).orEmpty()
    }

    private fun openServerStorage() {
        // The FTP share lives in the app's external-files directory. ACTION_OPEN_DOCUMENT_TREE
        // cannot reliably jump to this app-private directory, so show the actual serverRoot
        // contents in our own browser instead of an unrelated Android folder picker.
        serverBrowserPath = ""
        log("SERVER", "Opened NetFTPShare folder browser: ${serverRoot.absolutePath}")
    }

    private fun deleteServerFilesByExtensions(extensions: Set<String>) {
        if (extensions.isEmpty()) return
        lifecycleScope.launch(Dispatchers.IO) {
            var deleted = 0
            var failed = 0
            try {
                val root = serverRoot.canonicalFile
                root.walkTopDown().filter { it.isFile }.forEach { file ->
                    val ext = file.extension.lowercase(Locale.US)
                    if (ext.isNotBlank() && ext in extensions) {
                        try {
                            if (file.canonicalFile.path.startsWith(root.path + File.separator) && file.delete()) deleted++ else failed++
                        } catch (_: Exception) { failed++ }
                    }
                }
                withContext(Dispatchers.Main) {
                    refreshServerFiles()
                    showDeleteTypeDialog = false
                    transfer = TransferState(message = if (failed == 0) "Deleted $deleted file(s)" else "Deleted $deleted file(s); $failed failed")
                    log("SERVER", "Delete by file type: $deleted deleted, $failed failed")
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    showDeleteTypeDialog = false
                    transfer = TransferState(message = "Delete by type failed: ${e.message}")
                    log("ERROR", "Delete by type failed: ${e.message}")
                }
            }
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
                    serverBrowserPath = ""
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

    # Replace the previous storage card with a card that opens the real NetFTPShare
    # directory and exposes delete-by-extension controls.
    start = s.find('            Card(Modifier.fillMaxWidth()) {\n                Column(Modifier.padding(14.dp)) {\n                    Text("SERVER STORAGE"')
    if start == -1:
        marker = '''            Spacer(Modifier.height(10.dp))
            Text("PHONE ↔ LAPTOP", style = MaterialTheme.typography.titleMedium)'''
        card = '''            Spacer(Modifier.height(10.dp))
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("SERVER STORAGE", style = MaterialTheme.typography.titleMedium)
                    Text("${serverFiles.size} item(s) • ${formatStorageBytes(serverStorageBytes())} stored in NetFTPShare")
                    Text("This browser opens the actual directory used by the embedded FTP server.")
                    Spacer(Modifier.height(8.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Button(
                            onClick = { openServerStorage() },
                            modifier = Modifier.weight(1f)
                        ) { Text("Open NetFTPShare") }
                        OutlinedButton(
                            onClick = { showDeleteTypeDialog = true },
                            enabled = serverFiles.any { it.walkTopDown().any { child -> child.isFile && child.extension.isNotBlank() } },
                            modifier = Modifier.weight(1f)
                        ) { Text("Delete by Type") }
                    }
                    Spacer(Modifier.height(8.dp))
                    Button(
                        onClick = { showClearServerDialog = true },
                        enabled = serverFiles.isNotEmpty(),
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Clear All") }
                }
            }

            if (serverBrowserPath.isNotEmpty() || showDeleteTypeDialog || serverBrowserPath.isBlank()) {
                if (serverBrowserPath.isNotBlank() || serverFiles.isNotEmpty()) {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text("NetFTPShare", style = MaterialTheme.typography.titleMedium)
                            Text(if (serverBrowserPath.isBlank()) "/" else "/$serverBrowserPath")
                            Spacer(Modifier.height(8.dp))
                            val browserFiles = try { serverFilesAt(serverBrowserPath) } catch (_: Exception) { emptyList() }
                            if (serverBrowserPath.isNotBlank()) {
                                OutlinedButton(onClick = {
                                    serverBrowserPath = serverBrowserPath.substringBeforeLast('/', "")
                                }) { Text("← Parent") }
                            }
                            if (browserFiles.isEmpty()) {
                                Text("Empty folder")
                            } else {
                                browserFiles.forEach { file ->
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                                    ) {
                                        Icon(if (file.isDirectory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                                        Spacer(Modifier.width(8.dp))
                                        Column(Modifier.weight(1f)) {
                                            Text(file.name)
                                            Text(if (file.isDirectory) "Folder" else "${formatStorageBytes(file.length())} • .${file.extension.ifBlank { "unknown" }}")
                                        }
                                        if (file.isDirectory) {
                                            TextButton(onClick = { serverBrowserPath = serverRelativePath(file) }) { Text("Open") }
                                        } else {
                                            TextButton(onClick = { deleteServerFile(file) }) { Text("Delete") }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (showDeleteTypeDialog) {
                val extensionCounts = serverFiles
                    .flatMap { root -> root.walkTopDown().filter { it.isFile && it.extension.isNotBlank() }.toList() }
                    .groupingBy { it.extension.lowercase(Locale.US) }
                    .eachCount()
                var selectedExtensions by remember { mutableStateOf(setOf<String>()) }
                AlertDialog(
                    onDismissRequest = { showDeleteTypeDialog = false },
                    title = { Text("Delete by file type") },
                    text = {
                        Column(Modifier.verticalScroll(rememberScrollState())) {
                            Text("Select extensions to permanently delete from NetFTPShare.")
                            Spacer(Modifier.height(8.dp))
                            extensionCounts.toSortedMap().forEach { (extension, count) ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(
                                        checked = extension in selectedExtensions,
                                        onCheckedChange = { checked ->
                                            selectedExtensions = if (checked) selectedExtensions + extension else selectedExtensions - extension
                                        }
                                    )
                                    Text(".$extension  ($count file${if (count == 1) "" else "s"})")
                                }
                            }
                        }
                    },
                    confirmButton = {
                        TextButton(
                            enabled = selectedExtensions.isNotEmpty(),
                            onClick = { deleteServerFilesByExtensions(selectedExtensions) }
                        ) { Text("Delete selected") }
                    },
                    dismissButton = { TextButton(onClick = { showDeleteTypeDialog = false }) { Text("Cancel") } }
                )
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
        if marker not in s:
            raise SystemExit("Server tab insertion marker not found")
        s = s.replace(marker, card + marker, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("Fixed NetFTPShare browser and added delete-by-type controls")


if __name__ == "__main__":
    main()
