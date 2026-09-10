from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")

NAMES = [
    "serverStorageBytes",
    "formatStorageBytes",
    "openServerStorage",
    "clearServerStorage",
    "serverRelativePath",
    "serverFilesAt",
    "deleteServerFilesByExtensions",
]


def remove_function_defs(source: str, name: str) -> str:
    needle = f"    private fun {name}("
    while True:
        start = source.find(needle)
        if start < 0:
            return source
        brace = source.find("{", start)
        if brace < 0:
            raise SystemExit(f"Opening brace not found for {name}")
        depth = 0
        i = brace
        while i < len(source):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(source) and source[end] in "\n\r":
                        end += 1
                    source = source[:start] + source[end:]
                    break
            i += 1
        else:
            raise SystemExit(f"Unterminated function {name}")


def main():
    s = MAIN.read_text(encoding="utf-8")

    # Earlier storage patches inserted the same helper functions more than once.
    # Remove every copy, then install exactly one canonical implementation.
    for name in NAMES:
        s = remove_function_defs(s, name)

    canonical = r'''    private fun serverStorageBytes(): Long = serverFiles.sumOf { file ->
        if (file.isDirectory) file.walkTopDown().filter { it.isFile }.sumOf { it.length() } else file.length()
    }

    private fun formatStorageBytes(bytes: Long): String {
        if (bytes < 1024L) return "$bytes B"
        if (bytes < 1024L * 1024L) return "%.1f KB".format(Locale.US, bytes / 1024.0)
        if (bytes < 1024L * 1024L * 1024L) return "%.1f MB".format(Locale.US, bytes / (1024.0 * 1024.0))
        return "%.2f GB".format(Locale.US, bytes / (1024.0 * 1024.0 * 1024.0))
    }

    private fun openServerStorage() {
        serverBrowserPath = ""
        showServerBrowser = true
        log("SERVER", "Opened actual NetFTPShare folder: ${serverRoot.absolutePath}")
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
        return current.listFiles()?.sortedWith(compareBy<File> { !it.isDirectory }.thenBy { it.name.lowercase(Locale.US) }).orEmpty()
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

    marker = "    private fun deleteServerFile(file: File) {"
    if marker not in s:
        raise SystemExit("deleteServerFile marker not found")
    s = s.replace(marker, canonical + marker, 1)
    MAIN.write_text(s, encoding="utf-8")
    print("Normalized server storage helper functions")


if __name__ == "__main__":
    main()
