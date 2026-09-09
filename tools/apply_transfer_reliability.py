from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Required marker not found: {label}")
    return text.replace(old, new, 1)


def replace_function(text: str, signature: str, next_marker: str, body: str) -> str:
    start = text.find(signature)
    end = text.find(next_marker, start)
    if start < 0 or end < 0:
        raise SystemExit(f"Function markers not found: {signature}")
    return text[:start] + body + text[end:]


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Imports required for secure Android Sharesheet/file sharing.
    if "import android.content.Intent" not in s:
        s = replace_once(s, "import android.content.Context\n", "import android.content.Context\nimport android.content.Intent\n", "Intent import")
    if "import androidx.core.content.FileProvider" not in s:
        s = replace_once(s, "import androidx.core.app.NotificationCompat\n", "import androidx.core.app.NotificationCompat\nimport androidx.core.content.FileProvider\n", "FileProvider import")

    s = s.replace(
        'data class RemoteEntry(val name: String, val size: Long, val directory: Boolean)',
        'data class RemoteEntry(val name: String, val size: Long, val directory: Boolean, val path: String = name)',
        1,
    )

    # State used by automatic refresh. It is deliberately UI/client-side; no
    # server socket or FTP-server lifecycle is changed.
    state_marker = '    private val selectedRemoteNames = mutableStateListOf<String>()\n'
    if 'private var remoteRefreshRunning' not in s:
        s = replace_once(
            s,
            state_marker,
            state_marker + '    private var remoteRefreshRunning = false\n    private var transferRefreshJob: Job? = null\n',
            'refresh state',
        )

    # Start one lifecycle-bound refresh loop. FTP LIST is only attempted while
    # the client is idle, preventing the old LIST-vs-STOR/EPSV race.
    if 'transferRefreshJob = lifecycleScope.launch' not in s:
        marker = '        setContent { NetFtpApp() }\n'
        addition = '''        transferRefreshJob = lifecycleScope.launch {
            while (isActive) {
                delay(1800)
                if (serverRunning) withContext(Dispatchers.Main) { refreshServerFiles() }
                if (ftp != null && connectedTarget.isNotBlank() &&
                    !uploadQueueRunning && !downloadQueueRunning && !transfer.active && !remoteRefreshRunning) {
                    refreshRemote()
                }
            }
        }
'''
        s = replace_once(s, marker, addition + marker, 'automatic transfer refresh loop')

    s = s.replace(
        '        try { ftp?.close() } catch (_: Exception) { }\n        server.stop()',
        '        transferRefreshJob?.cancel()\n        try { ftp?.close() } catch (_: Exception) { }\n        server.stop()',
        1,
    )

    # Keep server-side local files visible in the Transfer tab without forcing
    # the user to connect the phone to its own FTP endpoint.
    refresh_server_pattern = re.compile(r'    private fun refreshServerFiles\(\) \{.*?\n    \}\n', re.S)
    m = refresh_server_pattern.search(s)
    if m:
        s = s[:m.start()] + '''    private fun refreshServerFiles() {
        serverFiles.clear()
        val files = serverRoot.listFiles()?.filter { it.exists() }?.sortedWith(
            compareBy<File> { !it.isDirectory }.thenBy { it.name.lowercase(Locale.US) }
        ).orEmpty()
        serverFiles.addAll(files)
    }

''' + s[m.end():]

    refresh_body = r'''    private fun refreshRemote() {
        val client = ftp
        if (client == null || connectedTarget.isBlank()) {
            remoteFiles.clear()
            selectedRemoteNames.clear()
            return
        }
        if (remoteRefreshRunning) return
        remoteRefreshRunning = true
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val parsed = parseListing(client.list())
                withContext(Dispatchers.Main) {
                    remoteFiles.clear()
                    remoteFiles.addAll(parsed)
                    selectedRemoteNames.retainAll(parsed.map { it.path }.toSet())
                    session = session.copy(connected = true)
                }
            } catch (e: Exception) {
                log("ERROR", "LIST failed: ${e.message}")
                if (client === ftp) {
                    try { client.close() } catch (_: Exception) { }
                    ftp = null
                    withContext(Dispatchers.Main) {
                        connectedTarget = ""
                        session = SessionStats()
                        remoteFiles.clear()
                        selectedRemoteNames.clear()
                        transfer = TransferState(message = "Remote FTP disconnected")
                    }
                }
            } finally {
                withContext(Dispatchers.Main) { remoteRefreshRunning = false }
            }
        }
    }

'''
    s = replace_function(s, '    private fun refreshRemote() {', '    private fun parseListing(', refresh_body)

    parse_body = r'''    private fun parseListing(text: String, basePath: String = ""): List<RemoteEntry> {
        val normalizedBase = basePath.trim('/').trim()
        return text.lineSequence()
            .mapNotNull { line ->
                val value = line.trim()
                if (value.isBlank()) return@mapNotNull null
                val parts = value.split(Regex("\\s+"), limit = 9)
                val name = if (parts.size >= 9) parts[8] else value
                if (name == "." || name == "..") return@mapNotNull null
                val directory = parts.size >= 9 && parts[0].startsWith("d")
                val size = if (parts.size >= 9) parts[4].toLongOrNull() ?: 0L else 0L
                val path = if (normalizedBase.isBlank()) name else "$normalizedBase/$name"
                RemoteEntry(name = name, size = size, directory = directory, path = path)
            }
            .toList()
    }

'''
    s = replace_function(s, '    private fun parseListing(', '    private fun queueUploads(', parse_body)

    # Downloads now support both files and directories. Directory transfers are
    # recursive and preserve the remote folder hierarchy in Downloads/.
    queue_body = r'''    private fun queueDownloads(entries: List<RemoteEntry>) {
        if (entries.isEmpty()) return
        downloadQueue.addAll(entries)
        selectedRemoteNames.removeAll(entries.map { it.path }.toSet())
        transfer = transfer.copy(active = false, message = "Queued ${entries.size} item(s) for download")
        log("DATA", "Queued ${entries.size} item(s) for download")
        if (downloadQueueRunning) return
        downloadQueueRunning = true
        lifecycleScope.launch(Dispatchers.IO) {
            while (true) {
                if (downloadQueue.isEmpty()) break
                val entry = downloadQueue.removeFirst()
                if (entry.directory) downloadFolderNow(entry)
                else downloadFileNow(entry)
            }
            withContext(Dispatchers.Main) { downloadQueueRunning = false }
            refreshRemote()
        }
    }

    private suspend fun downloadFolderNow(folder: RemoteEntry) {
        val client = ftp ?: return
        transfer = TransferState(active = true, direction = "DOWNLOAD", name = folder.path, message = "Reading folder")
        try {
            val children = parseListing(client.list(folder.path), folder.path)
            for (child in children) {
                if (child.directory) downloadFolderNow(child) else downloadFileNow(child)
            }
            transfer = transfer.copy(active = false, message = "Folder complete — saved to Downloads")
            log("DATA", "Folder download complete: ${folder.path}")
        } catch (e: Exception) {
            transfer = transfer.copy(active = false, message = "Folder download failed: ${e.message}")
            log("ERROR", "Folder download failed: ${folder.path}: ${e.message}")
        }
    }

    private suspend fun downloadFileNow(entry: RemoteEntry) {
        val client = ftp ?: return
        try {
            val relative = entry.path.trimStart('/').replace("\\", "/")
            val outFile = File(transferRoot, relative).canonicalFile
            if (!outFile.path.startsWith(transferRoot.canonicalPath + File.separator)) throw IOException("Unsafe filename")
            outFile.parentFile?.mkdirs()

            val total = client.remoteSize(entry.path).takeIf { it >= 0 } ?: entry.size
            val existing = if (outFile.exists()) outFile.length() else 0L
            if (total >= 0L && existing == total) {
                val localHash = sha256(outFile)
                val remoteHash = client.remoteSha256(entry.path)
                val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }
                if (verified == false) throw IOException("Cached file SHA-256 does not match remote file")
                transfer = TransferState(false, "DOWNLOAD", entry.path, total, total, 0L, "Already complete", localHash, remoteHash, verified)
                publishToDownloads(outFile, relative)
                log("DATA", "Cached file published: $relative")
                return
            }

            val resume = if (existing > 0L && total > 0L) min(existing, total) else 0L
            val startTime = System.currentTimeMillis()
            transfer = TransferState(true, "DOWNLOAD", entry.path, resume, total, 0L, if (resume > 0) "Resuming" else "Starting")
            RandomAccessFile(outFile, "rw").use { raf ->
                raf.setLength(resume)
                raf.seek(resume)
                val output = object : OutputStream() {
                    override fun write(b: Int) = raf.write(b)
                    override fun write(b: ByteArray, off: Int, len: Int) = raf.write(b, off, len)
                }
                client.download(entry.path, output, resume) { done, receivedTotal ->
                    val elapsed = maxOf(1L, System.currentTimeMillis() - startTime)
                    val speed = done * 1000L / elapsed
                    transfer = transfer.copy(done = done, total = receivedTotal, speedBps = speed, message = "Transferring")
                    session = session.copy(bytes = done, throughputBps = speed)
                }
                output.flush()
            }

            val localHash = sha256(outFile)
            val remoteHash = client.remoteSha256(entry.path)
            val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }
            if (verified == false) throw IOException("SHA-256 verification failed")
            publishToDownloads(outFile, relative)
            transfer = transfer.copy(active = false, message = "Complete — saved to Downloads", sha256Local = localHash, sha256Remote = remoteHash, verified = verified)
            log("DATA", "Saved $relative to public Downloads; SHA-256 $localHash")
        } catch (e: Exception) {
            transfer = transfer.copy(active = false, message = "Download failed: ${e.message}")
            log("ERROR", "Download failed: ${entry.path}: ${e.message}")
        }
    }

'''
    s = replace_function(s, '    private fun queueDownloads(', '    private fun verifyRemote(', queue_body)

    # Replace the Downloads publisher so nested folder downloads preserve their
    # relative folder structure while root files still land directly in Download/.
    publish_body = r'''    private fun publishToDownloads(source: File, relativePath: String) {
        val clean = relativePath.trimStart('/').replace("\\", "/")
        if (clean.isBlank() || clean.contains("../") || clean == "..") throw IOException("Unsafe Downloads path")
        val parent = clean.substringBeforeLast('/', "")
        val displayName = clean.substringAfterLast('/')
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, displayName)
                put(MediaStore.Downloads.MIME_TYPE, mimeTypeFor(displayName))
                put(MediaStore.Downloads.RELATIVE_PATH, if (parent.isBlank()) Environment.DIRECTORY_DOWNLOADS else Environment.DIRECTORY_DOWNLOADS + File.separator + parent)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("Cannot create public Downloads entry")
            try {
                contentResolver.openOutputStream(uri)?.use { output -> source.inputStream().use { input -> input.copyTo(output, 64 * 1024) } }
                    ?: throw IOException("Cannot open public Downloads output")
                values.clear(); values.put(MediaStore.Downloads.IS_PENDING, 0)
                contentResolver.update(uri, values, null, null)
            } catch (e: Exception) {
                contentResolver.delete(uri, null, null)
                throw e
            }
        } else {
            @Suppress("DEPRECATION")
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), parent).canonicalFile
            dir.mkdirs()
            val destination = File(dir, displayName).canonicalFile
            if (!destination.path.startsWith(dir.path + File.separator)) throw IOException("Unsafe Downloads filename")
            source.inputStream().use { input -> destination.outputStream().use { output -> input.copyTo(output, 64 * 1024) } }
        }
    }

'''
    if 'private fun publishToDownloads(' in s:
        s = replace_function(s, '    private fun publishToDownloads(', '    private fun verifyRemote(', publish_body)
    else:
        s = s.replace('    private fun verifyRemote(', publish_body + '    private fun verifyRemote(', 1)

    # Replace the upload progress callback so telemetry gets real transfer bytes
    # and speed instead of the stale session counters.
    old_upload = '''                    transfer = transfer.copy(
                        done = done,
                        total = total,
                        speedBps = done * 1000L / elapsed,
                        message = "Transferring"
                    )
'''
    new_upload = '''                    val speed = done * 1000L / elapsed
                    transfer = transfer.copy(
                        done = done,
                        total = total,
                        speedBps = speed,
                        message = "Transferring"
                    )
                    session = session.copy(bytes = done, throughputBps = speed)
'''
    if old_upload in s:
        s = s.replace(old_upload, new_upload, 1)

    # Recursive remote deletion. This fixes folder deletion for both the phone
    # server and ordinary FTP servers that implement RMD.
    if 'private suspend fun deleteRemoteEntry(' not in s:
        marker = '    private fun copyConsoleLog() {\n'
        delete_code = r'''    private suspend fun deleteRemoteEntry(entry: RemoteEntry) {
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
        if (file.isDirectory) file.listFiles()?.forEach { deleteLocalEntry(it) }
        file.delete()
    } catch (_: Exception) { false }

    private fun shareFiles(files: List<File>) {
        val existing = files.filter { it.isFile && it.exists() }
        if (existing.isEmpty()) {
            log("DATA", "Nothing available locally to share")
            return
        }
        try {
            val uris = existing.map { file ->
                FileProvider.getUriForFile(this, "${BuildConfig.APPLICATION_ID}.fileprovider", file)
            }
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
        if (it.isDirectory) it.walkTopDown().filter(File::isFile).toList() else listOf(it)
    }

'''
        s = replace_once(s, marker, delete_code + marker, 'transfer actions helpers')

    # Replace Transfer tab with a true file-manager style surface. When the
    # embedded phone server is running, its files are shown immediately; no
    # self-connection or IP selection is necessary.
    start = s.find('    @Composable\n    private fun TransfersTab() {')
    end = s.find('\n    private fun copyConsoleLog()', start)
    if start < 0 or end < 0:
        raise SystemExit('TransfersTab markers not found')
    transfers = r'''    @Composable
    private fun TransfersTab() {
        val remoteSelection = remoteFiles.filter { it.path in selectedRemoteNames }
        val localSelection = serverFiles.filter { it.path in selectedRemoteNames }
        val clientMode = connectedTarget.isNotBlank()
        val phoneServerMode = !clientMode && serverRunning

        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text("TRANSFER MANAGER", style = MaterialTheme.typography.labelLarge)
                        Text(
                            when {
                                clientMode -> "REMOTE FTP • $connectedTarget"
                                phoneServerMode -> "PHONE FTP SERVER • ${localIpv4() ?: "LAN"}:$serverPort"
                                else -> "NO ACTIVE FILE SOURCE"
                            },
                            style = MaterialTheme.typography.titleMedium
                        )
                        Text(
                            when {
                                clientMode -> "Remote files update automatically while the client is idle."
                                phoneServerMode -> "Files uploaded from a laptop appear here automatically. No IP selection is required."
                                else -> "Start the phone FTP server or select a device from Devices."
                            }
                        )
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                            if (clientMode) {
                                Button(onClick = { uploadDocument.launch(arrayOf("*/*")) }, enabled = !uploadQueueRunning && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Upload") }
                                OutlinedButton(onClick = { refreshRemote() }, modifier = Modifier.weight(1f)) { Text("Refresh") }
                                OutlinedButton(onClick = { disconnect() }, modifier = Modifier.weight(1f)) { Text("Disconnect") }
                            } else {
                                OutlinedButton(onClick = { refreshServerFiles(); refreshRemote() }, modifier = Modifier.weight(1f)) { Text("Refresh") }
                                OutlinedButton(onClick = { uploadDocument.launch(arrayOf("*/*")) }, enabled = phoneServerMode, modifier = Modifier.weight(1f)) { Text("Add files") }
                            }
                        }
                    }
                }
            }

            if (transfer.active || transfer.message != "Idle") {
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text("${transfer.direction}: ${transfer.name}")
                            if (transfer.total > 0) LinearProgressIndicator(progress = { (transfer.done.toFloat() / transfer.total).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                            Text("${transfer.message} • ${transfer.done}/${transfer.total} bytes • ${transfer.speedBps} B/s")
                            if (transfer.sha256Local.isNotBlank()) Text("SHA-256 local: ${transfer.sha256Local}")
                            if (transfer.sha256Remote.isNotBlank()) Text("SHA-256 remote: ${transfer.sha256Remote}")
                            transfer.verified?.let { Text(if (it) "Integrity: VERIFIED" else "Integrity: MISMATCH") }
                        }
                    }
                }
            }

            if (clientMode) {
                item {
                    Text("REMOTE FILES", style = MaterialTheme.typography.titleMedium)
                    Text("Files and folders. Select folders to download recursively to Download/<folder>.")
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedButton(onClick = { selectedRemoteNames.clear(); selectedRemoteNames.addAll(remoteFiles.map { it.path }) }, enabled = remoteFiles.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Select all") }
                        OutlinedButton(onClick = { selectedRemoteNames.clear() }, enabled = selectedRemoteNames.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Clear") }
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }
                        OutlinedButton(onClick = { shareRemoteEntries(remoteSelection) }, enabled = remoteSelection.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Share") }
                        OutlinedButton(onClick = { queueDeleteRemote(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning && !uploadQueueRunning, modifier = Modifier.weight(1f)) { Text("Delete") }
                    }
                }
                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->
                    val checked = entry.path in selectedRemoteNames
                    Card(Modifier.fillMaxWidth().clickable {
                        if (checked) selectedRemoteNames.remove(entry.path) else selectedRemoteNames.add(entry.path)
                    }) {
                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = checked, onCheckedChange = { if (it) selectedRemoteNames.add(entry.path) else selectedRemoteNames.remove(entry.path) })
                            Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }
                            if (!entry.directory) IconButton(onClick = { queueDownloads(listOf(entry)) }, enabled = !downloadQueueRunning) { Icon(Icons.Default.Download, "Download") }
                        }
                    }
                }
            } else {
                item {
                    Text("PHONE SERVER FILES", style = MaterialTheme.typography.titleMedium)
                    Text("Laptop uploads are shown here automatically while the embedded FTP server is running.")
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedButton(onClick = { selectedRemoteNames.clear(); selectedRemoteNames.addAll(serverFiles.map { it.absolutePath }) }, enabled = serverFiles.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Select all") }
                        OutlinedButton(onClick = { selectedRemoteNames.clear() }, enabled = selectedRemoteNames.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Clear") }
                        OutlinedButton(onClick = { shareFiles(serverSelectionFiles(serverFiles.filter { it.absolutePath in selectedRemoteNames })) }, enabled = selectedRemoteNames.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Share") }
                    }
                }
                items(serverFiles, key = { "local-${it.absolutePath}" }) { file ->
                    val key = file.absolutePath
                    val checked = key in selectedRemoteNames
                    Card(Modifier.fillMaxWidth()) {
                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = checked, onCheckedChange = { if (it) selectedRemoteNames.add(key) else selectedRemoteNames.remove(key) })
                            Icon(if (file.isDirectory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }
                            IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }
                            IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }
                        }
                    }
                }
            }
        }
    }
'''
    s = s[:start] + transfers + s[end:]

    # Replace Server tab with the same reliable local file operations so folder
    # deletion and sharing also work from the dedicated Server screen.
    start = s.find('    @Composable\n    private fun ServerTab() {')
    end = s.find('\n    @Composable\n    private fun QrDialog()', start)
    if start < 0 or end < 0:
        raise SystemExit('ServerTab markers not found')
    server_tab = r'''    @Composable
    private fun ServerTab() {
        Column(
            Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            ServerStatusAnimation(serverRunning)
            Text(if (serverRunning) "RUNNING • ${localIpv4() ?: "0.0.0.0"}:$serverPort" else "STOPPED")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = { toggleServer() }, modifier = Modifier.weight(1f)) { Text(if (serverRunning) "Stop server" else "Start server") }
                OutlinedButton(onClick = { showQr = true }, enabled = serverRunning, modifier = Modifier.weight(1f)) { Text("QR") }
                OutlinedButton(onClick = { refreshServerFiles() }, modifier = Modifier.weight(1f)) { Text("Refresh") }
            }
            Text("SERVER FILES", style = MaterialTheme.typography.titleMedium)
            Text("Changes made from Windows/File Explorer are detected automatically.")
            if (serverFiles.isEmpty()) Text("No files in the FTP share yet.")
            serverFiles.forEach { file ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (file.isDirectory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }
                        IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }
                        IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }
                    }
                }
            }
            Button(onClick = { shareDocument.launch(arrayOf("*/*")) }, modifier = Modifier.fillMaxWidth()) { Text("Add files to server") }
        }
    }
'''
    s = s[:start] + server_tab + s[end:]

    MAIN.write_text(s, encoding="utf-8")
    print("Applied transfer reliability, folder operations, automatic refresh, local server view, and file sharing")


if __name__ == "__main__":
    main()
