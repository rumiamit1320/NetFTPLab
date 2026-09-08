from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def find_matching_brace(s: str, open_pos: int) -> int:
    depth = 0
    in_string = False
    escape = False
    in_line_comment = False
    in_block_comment = False
    i = open_pos
    while i < len(s):
        c = s[i]
        n = s[i + 1] if i + 1 < len(s) else ""
        if in_line_comment:
            if c == "\n": in_line_comment = False
        elif in_block_comment:
            if c == "*" and n == "/": in_block_comment = False; i += 1
        elif in_string:
            if escape: escape = False
            elif c == "\\": escape = True
            elif c == '"': in_string = False
        else:
            if c == '/' and n == '/': in_line_comment = True; i += 1
            elif c == '/' and n == '*': in_block_comment = True; i += 1
            elif c == '"': in_string = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return i
        i += 1
    raise ValueError("Unmatched brace")


def extract_function(s: str, marker: str):
    start = s.find(marker)
    if start < 0: raise SystemExit(f"Missing function marker: {marker}")
    brace = s.find('{', start)
    if brace < 0: raise SystemExit(f"Missing function body: {marker}")
    end = find_matching_brace(s, brace) + 1
    return start, end, s[start:end]


def make_suspend_function(fn: str, old_name: str, new_name: str) -> str:
    fn = fn.replace(f"private fun {old_name}", f"private suspend fun {new_name}", 1)
    launch = "        lifecycleScope.launch(Dispatchers.IO) {\n"
    if launch not in fn: raise SystemExit(f"Expected coroutine wrapper missing in {old_name}")
    fn = fn.replace(launch, "", 1)
    tail = "\n        }\n    }"
    if not fn.endswith(tail): raise SystemExit(f"Unexpected ending for {old_name}")
    fn = fn[:-len(tail)] + "\n    }"
    return fn


def main():
    s = MAIN.read_text(encoding="utf-8")

    # Android document picker: allow selecting several source files in one action.
    old_launcher = '''    private val uploadDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) uploadUri(uri)
    }
'''
    new_launcher = '''    private val uploadDocument = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) queueUploads(uris)
    }
'''
    if old_launcher not in s: raise SystemExit("Upload picker block not found")
    s = s.replace(old_launcher, new_launcher, 1)

    # Queue state lives in MainActivity, preserving FtpClient/FtpServer architecture.
    state_anchor = '    private var showQr by mutableStateOf(false)\n'
    state_insert = '''    private var showQr by mutableStateOf(false)
    private val uploadQueue = ArrayDeque<Uri>()
    private val downloadQueue = ArrayDeque<RemoteEntry>()
    private var uploadQueueRunning by mutableStateOf(false)
    private var downloadQueueRunning by mutableStateOf(false)
    private val selectedRemoteNames = mutableStateListOf<String>()
'''
    if state_anchor not in s: raise SystemExit("State anchor not found")
    s = s.replace(state_anchor, state_insert, 1)

    # Convert existing single-file upload/download operations into suspend workers.
    us, ue, ufn = extract_function(s, '    private fun uploadUri(uri: Uri) {')
    new_u_fn = make_suspend_function(ufn, 'uploadUri', 'uploadUriNow')
    s = s[:us] + new_u_fn + s[ue:]

    ds, de, dfn = extract_function(s, '    private fun download(entry: RemoteEntry) {')
    new_d_fn = make_suspend_function(dfn, 'download', 'downloadNow')
    s = s[:ds] + new_d_fn + s[de:]

    # Sequential queues keep the existing persistent FTP control connection and
    # single-transfer integrity/resume logic intact; only orchestration changes.
    upload_anchor = '    private suspend fun uploadUriNow(uri: Uri) {'
    upload_start = s.find(upload_anchor)
    if upload_start < 0: raise SystemExit("uploadUriNow not found")
    queue_code = '''    private fun queueUploads(uris: List<Uri>) {
        uploadQueue.addAll(uris)
        transfer = transfer.copy(active = false, message = "Queued ${uris.size} file(s)")
        log("DATA", "Queued ${uris.size} file(s) for upload")
        if (uploadQueueRunning) return
        uploadQueueRunning = true
        lifecycleScope.launch(Dispatchers.IO) {
            while (true) {
                val uri = uploadQueue.removeFirstOrNull() ?: break
                uploadUriNow(uri)
            }
            withContext(Dispatchers.Main) { uploadQueueRunning = false }
        }
    }

'''
    s = s[:upload_start] + queue_code + s[upload_start:]

    download_anchor = '    private suspend fun downloadNow(entry: RemoteEntry) {'
    download_start = s.find(download_anchor)
    if download_start < 0: raise SystemExit("downloadNow not found")
    dq_code = '''    private fun queueDownloads(entries: List<RemoteEntry>) {
        val files = entries.filterNot { it.directory }
        if (files.isEmpty()) return
        downloadQueue.addAll(files)
        selectedRemoteNames.removeAll(files.map { it.name }.toSet())
        transfer = transfer.copy(active = false, message = "Queued ${files.size} file(s) for download")
        log("DATA", "Queued ${files.size} file(s) for download")
        if (downloadQueueRunning) return
        downloadQueueRunning = true
        lifecycleScope.launch(Dispatchers.IO) {
            while (true) {
                val entry = downloadQueue.removeFirstOrNull() ?: break
                downloadNow(entry)
            }
            withContext(Dispatchers.Main) { downloadQueueRunning = false }
        }
    }

'''
    s = s[:download_start] + dq_code + s[download_start:]

    # Replace the transfer-tab remote list with selectable rows and batch actions.
    start = s.find('    @Composable\n    private fun TransfersTab() {')
    end = s.find('\n    private fun copyConsoleLog()', start)
    if start < 0 or end < 0: raise SystemExit("TransfersTab markers not found")
    transfers = '''    @Composable
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
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                            Button(
                                onClick = { uploadDocument.launch(arrayOf("*/*")) },
                                enabled = connectedTarget.isNotBlank() && !uploadQueueRunning,
                                modifier = Modifier.weight(1f)
                            ) { Text("Select files") }
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
                                    progress = { (transfer.done.toFloat() / transfer.total).coerceIn(0f, 1f) },
                                    modifier = Modifier.fillMaxWidth()
                                )
                            }
                            Text("${transfer.message} • ${transfer.done}/${transfer.total} bytes • ${transfer.speedBps} B/s")
                            if (transfer.sha256Local.isNotBlank()) Text("SHA-256 local: ${transfer.sha256Local}")
                            if (transfer.sha256Remote.isNotBlank()) Text("SHA-256 remote: ${transfer.sha256Remote}")
                            transfer.verified?.let { Text(if (it) "Integrity: VERIFIED" else "Integrity: MISMATCH") }
                        }
                    }
                }
            }

            item {
                Text("REMOTE FILES", style = MaterialTheme.typography.titleMedium)
                Text("Select multiple files, then download them sequentially to the phone.")
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(
                        onClick = {
                            selectedRemoteNames.clear()
                            selectedRemoteNames.addAll(remoteFiles.filterNot { it.directory }.map { it.name })
                        },
                        enabled = connectedTarget.isNotBlank() && remoteFiles.any { !it.directory },
                        modifier = Modifier.weight(1f)
                    ) { Text("Select all") }
                    OutlinedButton(
                        onClick = { selectedRemoteNames.clear() },
                        enabled = selectedRemoteNames.isNotEmpty(),
                        modifier = Modifier.weight(1f)
                    ) { Text("Clear") }
                    Button(
                        onClick = {
                            queueDownloads(remoteFiles.filter { selectedRemoteNames.contains(it.name) })
                        },
                        enabled = connectedTarget.isNotBlank() && selectedRemoteNames.isNotEmpty() && !downloadQueueRunning,
                        modifier = Modifier.weight(1f)
                    ) { Text("Download (${selectedRemoteNames.size})") }
                }
            }

            items(remoteFiles) { entry ->
                val selected = selectedRemoteNames.contains(entry.name)
                Card(Modifier.fillMaxWidth().clickable(enabled = connectedTarget.isNotBlank() && !entry.directory) {
                    if (selected) selectedRemoteNames.remove(entry.name) else selectedRemoteNames.add(entry.name)
                }) {
                    Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (!entry.directory) {
                            Checkbox(
                                checked = selected,
                                onCheckedChange = { checked ->
                                    if (checked) selectedRemoteNames.add(entry.name) else selectedRemoteNames.remove(entry.name)
                                }
                            )
                        } else {
                            Spacer(Modifier.width(48.dp))
                        }
                        Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
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
    print("Added multi-file upload/download selection using sequential existing FTP transfers")


if __name__ == "__main__":
    main()
