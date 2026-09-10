from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def require_once(text: str, marker: str, block: str) -> str:
    if block.strip() in text:
        return text
    if marker not in text:
        raise SystemExit(f"marker not found: {marker!r}")
    return text.replace(marker, block + "\n" + marker, 1)


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SystemExit(f"replacement target not found: {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    s = require_once(
        s,
        '    private var showQr by mutableStateOf(false)',
        '    private var showClearServerDialog by mutableStateOf(false)\n    private var showDeleteTypeDialog by mutableStateOf(false)\n    private var showServerBrowser by mutableStateOf(false)\n    private var serverBrowserPath by mutableStateOf("")'
    )

    # Replace the old generic Android picker with an in-app browser rooted at the
    # exact directory used by the embedded FTP server.
    old_open = '''    private fun openServerStorage() {
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
'''
    new_open = '''    private fun openServerStorage() {
        // NetFTPShare is the embedded server's actual root. Android's generic
        // ACTION_OPEN_DOCUMENT_TREE picker cannot reliably target this app-private
        // directory, so show the real directory in the app's browser.
        serverBrowserPath = ""
        showServerBrowser = true
        log("SERVER", "Opened actual NetFTPShare folder: ${serverRoot.absolutePath}")
    }
'''
    if old_open in s:
        s = replace_once(s, old_open, new_open)

    # Add only helpers that do not already exist in the original storage patch.
    helper = '''    private fun serverRelativePath(file: File): String {
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
'''
    s = require_once(s, '    private fun deleteServerFile(file: File) {', helper)

    # Add a dedicated Delete by Type button below the existing Open Storage/Clear All row.
    if 'Text("Delete by Type")' not in s:
        anchor = '''                    Row(
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
'''
        extra = anchor + '''                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { showDeleteTypeDialog = true },
                        enabled = serverFiles.any { root -> root.walkTopDown().any { it.isFile && it.extension.isNotBlank() } },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Delete by Type") }
'''
        if anchor not in s:
            raise SystemExit("SERVER STORAGE button row not found")
        s = s.replace(anchor, extra, 1)

    browser = '''            if (showServerBrowser) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text("NetFTPShare — Actual Server Folder", style = MaterialTheme.typography.titleMedium)
                        Text(if (serverBrowserPath.isBlank()) "/" else "/$serverBrowserPath")
                        Spacer(Modifier.height(8.dp))
                        val browserFiles = try { serverFilesAt(serverBrowserPath) } catch (_: Exception) { emptyList() }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (serverBrowserPath.isNotBlank()) {
                                OutlinedButton(onClick = {
                                    serverBrowserPath = serverBrowserPath.substringBeforeLast('/', "")
                                }) { Text("← Parent") }
                            }
                            OutlinedButton(onClick = { refreshServerFiles() }) { Text("Refresh") }
                            OutlinedButton(onClick = { showServerBrowser = false }) { Text("Close") }
                        }
                        Spacer(Modifier.height(8.dp))
                        if (browserFiles.isEmpty()) {
                            Text("Folder is empty")
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
                            if (extensionCounts.isEmpty()) Text("No file extensions found.")
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

'''
    if 'NetFTPShare — Actual Server Folder' not in s:
        marker = '''            Spacer(Modifier.height(10.dp))
            Text("PHONE ↔ LAPTOP", style = MaterialTheme.typography.titleMedium)'''
        if marker not in s:
            raise SystemExit("Server tab insertion marker not found")
        s = s.replace(marker, browser + marker, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("Fixed actual NetFTPShare browser and added delete-by-file-type UI")


if __name__ == "__main__":
    main()
