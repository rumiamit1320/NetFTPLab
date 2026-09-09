from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")

HELPERS = r'''    private suspend fun deleteRemoteEntry(entry: RemoteEntry) {
        val client = ftp ?: return
        if (entry.directory) {
            val children = parseListing(client.list(entry.path), entry.path)
            for (child in children) deleteRemoteEntry(child)
            client.deleteDirectory(entry.path)
        } else {
            client.delete(entry.path)
        }
    }

    private fun queueDeleteRemote(entries: List<RemoteEntry>) {
        if (entries.isEmpty() || ftp == null || uploadQueueRunning || downloadQueueRunning) return
        lifecycleScope.launch(Dispatchers.IO) {
            transfer = TransferState(active = true, direction = "DELETE", name = "${entries.size} item(s)", message = "Deleting")
            try {
                for (entry in entries) deleteRemoteEntry(entry)
                withContext(Dispatchers.Main) {
                    selectedRemoteNames.clear()
                    transfer = TransferState(message = "Deleted ${entries.size} item(s)")
                }
                refreshRemote()
            } catch (e: Exception) {
                log("ERROR", "Delete failed: ${e.message}")
                withContext(Dispatchers.Main) { transfer = TransferState(message = "Delete failed: ${e.message}") }
            }
        }
    }

    private fun deleteLocalEntry(file: File): Boolean = try {
        file.deleteRecursively()
    } catch (_: Exception) { false }

    private fun shareFiles(files: List<File>) {
        val existing = files.filter { it.isFile && it.exists() }
        if (existing.isEmpty()) {
            log("DATA", "Nothing available locally to share")
            return
        }
        try {
            val uris = existing.map { file -> FileProvider.getUriForFile(this, "${BuildConfig.APPLICATION_ID}.fileprovider", file) }
            val intent = if (uris.size == 1) {
                Intent(Intent.ACTION_SEND).apply {
                    type = mimeTypeFor(existing.first().name)
                    putExtra(Intent.EXTRA_STREAM, uris.first())
                }
            } else {
                Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                    type = "*/*"
                    putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
                }
            }
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            intent.clipData = ClipData.newUri(contentResolver, existing.first().name, uris.first()).also { clip ->
                uris.drop(1).forEach { clip.addItem(ClipData.Item(it)) }
            }
            startActivity(Intent.createChooser(intent, "Share files"))
        } catch (e: Exception) {
            log("ERROR", "Share failed: ${e.message}")
        }
    }

    private fun shareRemoteEntries(entries: List<RemoteEntry>) {
        val files = entries.flatMap { entry ->
            val root = File(transferRoot, entry.path).canonicalFile
            if (entry.directory && root.isDirectory) root.walkTopDown().filter { it.isFile }.toList() else listOf(root)
        }
        shareFiles(files)
    }

    private fun serverSelectionFiles(selection: List<File>): List<File> = selection.flatMap {
        if (it.isDirectory) it.walkTopDown().filter { child -> child.isFile }.toList() else listOf(it)
    }

    private fun mimeTypeFor(name: String): String = when (name.substringAfterLast('.', "").lowercase(Locale.US)) {
        "pdf" -> "application/pdf"
        "txt", "log", "csv" -> "text/plain"
        "json" -> "application/json"
        "xml" -> "application/xml"
        "jpg", "jpeg" -> "image/jpeg"
        "png" -> "image/png"
        "gif" -> "image/gif"
        "mp3" -> "audio/mpeg"
        "mp4" -> "video/mp4"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        "zip" -> "application/zip"
        else -> "application/octet-stream"
    }

'''


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")
    if "private fun shareFiles(" not in s:
        marker = "    @Composable\n    private fun TransfersTab() {"
        if marker not in s:
            raise SystemExit("TransfersTab marker not found")
        s = s.replace(marker, HELPERS + marker, 1)
    MAIN.write_text(s, encoding="utf-8")
    print("Added transfer delete/share/mime helpers")


if __name__ == "__main__":
    main()
