from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Required marker not found: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Android 13+: use Activity Result so the server notification is posted
    # after the permission callback instead of racing the permission dialog.
    if "notificationPermissionLauncher" not in s:
        marker = '''    private val shareDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importToServer(uri)
    }
'''
        launcher = marker + '''
    private val notificationPermissionLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted && serverRunning) showServerNotification()
        else if (!granted) log("SERVER", "Notification permission denied; FTP server remains available in-app")
    }
'''
        s = replace_once(s, marker, launcher, "shareDocument declaration")

    old_permission = '''        if (android.os.Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
        }
'''
    new_permission = '''        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
'''
    if old_permission in s:
        s = s.replace(old_permission, new_permission, 1)

    # Replace the complete-file resume bug. A cache whose size already equals
    # the remote SIZE is complete: hash it and publish it instead of REST total.
    start = s.find("    private fun download(entry: RemoteEntry) {")
    end = s.find("    private fun verifyRemote(", start)
    if start < 0 or end < 0:
        raise SystemExit("download/verifyRemote markers not found")

    download = r'''    private fun download(entry: RemoteEntry) {
        val client = ftp ?: return
        if (entry.directory) return
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val outFile = File(transferRoot, entry.name).canonicalFile
                if (!outFile.path.startsWith(transferRoot.canonicalPath + File.separator)) {
                    throw IOException("Unsafe filename")
                }

                val total = client.remoteSize(entry.name).takeIf { it >= 0 } ?: entry.size
                val existing = if (outFile.exists()) outFile.length() else 0L

                if (total >= 0L && existing >= total) {
                    val localHash = sha256(outFile)
                    val remoteHash = client.remoteSha256(entry.name)
                    val verified = remoteHash.takeIf { it.isNotBlank() }
                        ?.let { localHash.equals(it, true) }
                    if (verified == false) {
                        throw IOException("Cached file SHA-256 does not match remote file")
                    }
                    transfer = TransferState(
                        active = false,
                        direction = "DOWNLOAD",
                        name = entry.name,
                        done = total,
                        total = total,
                        message = "Already complete",
                        sha256Local = localHash,
                        sha256Remote = remoteHash,
                        verified = verified
                    )
                    publishToDownloads(outFile, entry.name)
                    log("DATA", "Download cache already complete; published ${entry.name} to Downloads")
                    return@launch
                }

                val resume = if (existing > 0L && total > 0L) min(existing, total) else 0L
                val startTime = System.currentTimeMillis()
                transfer = TransferState(
                    active = true,
                    direction = "DOWNLOAD",
                    name = entry.name,
                    done = resume,
                    total = total,
                    message = if (resume > 0L) "Resuming" else "Starting"
                )

                RandomAccessFile(outFile, "rw").use { raf ->
                    raf.setLength(resume)
                    raf.seek(resume)
                    val output = object : OutputStream() {
                        override fun write(b: Int) = raf.write(b)
                        override fun write(b: ByteArray, off: Int, len: Int) = raf.write(b, off, len)
                    }
                    client.download(entry.name, output, resume) { done, receivedTotal ->
                        val elapsed = maxOf(1L, System.currentTimeMillis() - startTime)
                        transfer = transfer.copy(
                            done = done,
                            total = receivedTotal,
                            speedBps = done * 1000L / elapsed,
                            message = "Transferring"
                        )
                    }
                    output.flush()
                }

                val localHash = sha256(outFile)
                val remoteHash = client.remoteSha256(entry.name)
                val verified = remoteHash.takeIf { it.isNotBlank() }
                    ?.let { localHash.equals(it, true) }
                if (verified == false) throw IOException("SHA-256 verification failed")

                publishToDownloads(outFile, entry.name)
                transfer = transfer.copy(
                    active = false,
                    message = "Complete — saved to Downloads",
                    sha256Local = localHash,
                    sha256Remote = remoteHash,
                    verified = verified
                )
                session = session.copy(bytes = session.bytes + outFile.length())
                log("DATA", "Saved ${entry.name} to public Downloads; SHA-256 $localHash")
            } catch (e: Exception) {
                transfer = transfer.copy(active = false, message = "Download failed: ${e.message}")
                log("ERROR", "Download failed: ${e.message}")
            }
        }
    }

    private fun publishToDownloads(source: File, displayName: String) {
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            val resolver = contentResolver
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, displayName)
                put(MediaStore.Downloads.MIME_TYPE, mimeTypeFor(displayName))
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("Cannot create public Downloads entry")
            try {
                resolver.openOutputStream(uri)?.use { output ->
                    source.inputStream().use { input -> input.copyTo(output, 64 * 1024) }
                } ?: throw IOException("Cannot open public Downloads output")
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            } catch (e: Exception) {
                resolver.delete(uri, null, null)
                throw e
            }
        } else {
            @Suppress("DEPRECATION")
            val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).apply { mkdirs() }
            val destination = File(dir, displayName).canonicalFile
            if (!destination.path.startsWith(dir.canonicalPath + File.separator)) {
                throw IOException("Unsafe Downloads filename")
            }
            source.inputStream().use { input ->
                destination.outputStream().use { output -> input.copyTo(output, 64 * 1024) }
            }
        }
        transfer = transfer.copy(message = "Saved to Downloads")
    }

    private fun mimeTypeFor(name: String): String = when (name.substringAfterLast('.', "").lowercase(Locale.US)) {
        "pdf" -> "application/pdf"
        "txt", "log" -> "text/plain"
        "csv" -> "text/csv"
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
    s = s[:start] + download + s[end:]

    # Keep the UI wording aligned with the actual destination.
    s = s.replace("Local transfer directory: ${transferRoot.absolutePath}", "Download destination: public Downloads")

    MAIN.write_text(s, encoding="utf-8")
    print("NetFTPLab fixes applied")


if __name__ == "__main__":
    main()
