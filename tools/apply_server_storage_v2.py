from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main():
    s = MAIN.read_text(encoding="utf-8")

    # Normalize state declarations added by earlier attempts.
    s = re.sub(r'(?m)^    private var showClearServerDialog by mutableStateOf\(false\)\n(?:    private var showClearServerDialog by mutableStateOf\(false\)\n)+',
               '    private var showClearServerDialog by mutableStateOf(false)\n', s)
    def add_state(line, marker):
        nonlocal s
        if line not in s:
            if marker not in s:
                raise SystemExit(f"state marker not found: {marker}")
            s = s.replace(marker, marker + "\n" + line, 1)
    add_state('    private var showDeleteTypeDialog by mutableStateOf(false)', '    private var showClearServerDialog by mutableStateOf(false)')
    add_state('    private var showServerBrowser by mutableStateOf(false)', '    private var showDeleteTypeDialog by mutableStateOf(false)')
    add_state('    private var serverBrowserPath by mutableStateOf("")', '    private var showServerBrowser by mutableStateOf(false)')

    # Replace whatever implementation currently exists with the real server-root browser opener.
    pattern = r'(?s)    private fun openServerStorage\(\) \{.*?\n    \}\n\n    private fun'
    replacement = '''    private fun openServerStorage() {
        serverBrowserPath = ""
        showServerBrowser = true
        log("SERVER", "Opened actual NetFTPShare folder: ${serverRoot.absolutePath}")
    }

    private fun'''
    if re.search(pattern, s):
        s = re.sub(pattern, replacement, s, count=1)
    elif 'private fun openServerStorage()' not in s:
        raise SystemExit('openServerStorage function not found')

    helpers = '''    private fun serverRelativePath(file: File): String {
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
        return current.listFiles()?.sortedWith(compareBy<File> { !it.isDirectory }.thenBy { it.name.lowercase(Locale.US) }).orEmpty()
    }

    private fun deleteServerFilesByExtensions(extensions: Set<String>) {
        if (extensions.isEmpty()) return
        lifecycleScope.launch(Dispatchers.IO) {
            var deleted = 0
            var failed = 0
            val root = serverRoot.canonicalFile
            root.walkTopDown().filter { it.isFile }.forEach { file ->
                val ext = file.extension.lowercase(Locale.US)
                if (ext in extensions) {
                    try {
                        val safe = file.canonicalFile.path.startsWith(root.path + File.separator)
                        if (safe && file.delete()) deleted++ else failed++
                    } catch (_: Exception) { failed++ }
                }
            }
            withContext(Dispatchers.Main) {
                refreshServerFiles()
                showDeleteTypeDialog = false
                transfer = TransferState(message = "Deleted $deleted file(s)" + if (failed > 0) "; $failed failed" else "")
                log("SERVER", "Delete by file type: $deleted deleted, $failed failed")
            }
        }
    }
'''
    if 'private fun serverFilesAt(' not in s:
        marker = '    private fun deleteServerFile(file: File) {'
        if marker not in s:
            raise SystemExit('deleteServerFile marker not found')
        s = s.replace(marker, helpers + '\n' + marker, 1)

    ui = '''            if (showServerBrowser) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text("NetFTPShare — Actual Server Folder", style = MaterialTheme.typography.titleMedium)
                        Text(if (serverBrowserPath.isBlank()) "/" else "/$serverBrowserPath")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (serverBrowserPath.isNotBlank()) {
                                OutlinedButton(onClick = { serverBrowserPath = serverBrowserPath.substringBeforeLast('/', "") }) { Text("← Parent") }
                            }
                            OutlinedButton(onClick = { refreshServerFiles() }) { Text("Refresh") }
                            OutlinedButton(onClick = { showServerBrowser = false }) { Text("Close") }
                        }
                        Spacer(Modifier.height(6.dp))
                        val entries = try { serverFilesAt(serverBrowserPath) } catch (_: Exception) { emptyList() }
                        if (entries.isEmpty()) Text("Folder is empty")
                        entries.forEach { file ->
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                                Column(Modifier.weight(1f)) {
                                    Text(file.name)
                                    Text(if (file.isDirectory) "Folder" else "${formatStorageBytes(file.length())} • .${file.extension.ifBlank { "unknown" }}")
                                }
                                if (file.isDirectory) TextButton(onClick = { serverBrowserPath = serverRelativePath(file) }) { Text("Open") }
                                else TextButton(onClick = { deleteServerFile(file) }) { Text("Delete") }
                            }
                        }
                    }
                }
            }

            if (showDeleteTypeDialog) {
                val counts = serverRoot.walkTopDown().filter { it.isFile && it.extension.isNotBlank() }
                    .groupingBy { it.extension.lowercase(Locale.US) }.eachCount().toSortedMap()
                var selected by remember { mutableStateOf(setOf<String>()) }
                AlertDialog(
                    onDismissRequest = { showDeleteTypeDialog = false },
                    title = { Text("Delete by file type") },
                    text = {
                        Column(Modifier.verticalScroll(rememberScrollState())) {
                            Text("Select extensions to delete recursively from NetFTPShare.")
                            counts.forEach { (ext, count) ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(checked = ext in selected, onCheckedChange = { checked -> selected = if (checked) selected + ext else selected - ext })
                                    Text(".$ext ($count)")
                                }
                            }
                            if (counts.isEmpty()) Text("No file extensions found.")
                        }
                    },
                    confirmButton = { TextButton(enabled = selected.isNotEmpty(), onClick = { deleteServerFilesByExtensions(selected) }) { Text("Delete selected") } },
                    dismissButton = { TextButton(onClick = { showDeleteTypeDialog = false }) { Text("Cancel") } }
                )
            }

            OutlinedButton(
                onClick = { showDeleteTypeDialog = true },
                enabled = serverFiles.any { it.isFile && it.extension.isNotBlank() },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Delete by Type") }

'''
    if 'NetFTPShare — Actual Server Folder' not in s:
        marker = '            Text("PHONE ↔ LAPTOP", style = MaterialTheme.typography.titleMedium)'
        if marker not in s:
            raise SystemExit('PHONE ↔ LAPTOP marker not found')
        s = s.replace(marker, ui + marker, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("Server storage controls applied")


if __name__ == "__main__":
    main()
