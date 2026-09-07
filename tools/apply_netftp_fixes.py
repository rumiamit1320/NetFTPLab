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

    # Add the animated FTP server status indicator. It is UI-only: server
    # ownership, lifecycle, ports, and networking architecture remain intact.
    if "private fun ServerStatusAnimation(" not in s:
        imports = '''import androidx.activity.result.contract.ActivityResultContracts
'''
        animation_imports = '''import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
'''
        s = replace_once(s, imports, animation_imports, "Compose animation imports")

        marker = '''    @Composable
    private fun ServerTab() {
'''
        animation = r'''    @Composable
    private fun ServerStatusAnimation(running: Boolean) {
        val transition = rememberInfiniteTransition(label = "ftp-server-status")
        val pulse = transition.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(1800, easing = LinearEasing),
                repeatMode = RepeatMode.Restart
            ),
            label = "server-pulse"
        )
        val sweep = transition.animateFloat(
            initialValue = 0f,
            targetValue = 360f,
            animationSpec = infiniteRepeatable(
                animation = tween(3200, easing = LinearEasing),
                repeatMode = RepeatMode.Restart
            ),
            label = "server-sweep"
        )
        val statusColor = if (running) Color(0xFF34D399) else Color(0xFF64748B)
        val pulseValue = pulse.value

        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Canvas(
                modifier = Modifier.size(148.dp),
                contentDescription = if (running) "FTP server running" else "FTP server stopped"
            ) {
                val center = Offset(size.width / 2f, size.height / 2f)
                val baseRadius = size.minDimension * 0.22f
                if (running) {
                    drawCircle(
                        color = statusColor.copy(alpha = 0.05f + 0.08f * (1f - pulseValue)),
                        radius = baseRadius + size.minDimension * 0.24f * pulseValue,
                        center = center
                    )
                    drawCircle(
                        color = statusColor.copy(alpha = 0.10f + 0.10f * (1f - pulseValue)),
                        radius = baseRadius + size.minDimension * 0.14f * pulseValue,
                        center = center,
                        style = Stroke(width = 3.dp.toPx())
                    )
                    drawArc(
                        color = statusColor,
                        startAngle = sweep.value,
                        sweepAngle = 105f,
                        useCenter = false,
                        topLeft = Offset(18.dp.toPx(), 18.dp.toPx()),
                        size = Size(size.width - 36.dp.toPx(), size.height - 36.dp.toPx()),
                        style = Stroke(width = 5.dp.toPx())
                    )
                    drawArc(
                        color = statusColor.copy(alpha = 0.35f),
                        startAngle = sweep.value + 180f,
                        sweepAngle = 55f,
                        useCenter = false,
                        topLeft = Offset(28.dp.toPx(), 28.dp.toPx()),
                        size = Size(size.width - 56.dp.toPx(), size.height - 56.dp.toPx()),
                        style = Stroke(width = 3.dp.toPx())
                    )
                } else {
                    drawCircle(
                        color = statusColor.copy(alpha = 0.08f),
                        radius = baseRadius + 16.dp.toPx(),
                        center = center,
                        style = Stroke(width = 3.dp.toPx())
                    )
                }
                drawCircle(color = statusColor.copy(alpha = 0.16f), radius = baseRadius + 5.dp.toPx(), center = center)
                drawCircle(color = statusColor, radius = baseRadius, center = center)
                drawCircle(color = Color(0xFF080B10), radius = baseRadius * 0.38f, center = center)
            }
            Spacer(Modifier.height(2.dp))
            Text(
                if (running) "FTP SERVER ONLINE" else "FTP SERVER OFFLINE",
                style = MaterialTheme.typography.labelLarge,
                color = statusColor
            )
        }
    }

    @Composable
    private fun ServerTab() {
'''
        s = replace_once(s, marker, animation, "ServerTab declaration")

    old_status = '''            Text(
                if (serverRunning) "RUNNING • ${localIpv4() ?: "0.0.0.0"}:$serverPort" else "STOPPED"
            )
            Spacer(Modifier.height(8.dp))
            Button(
'''
    new_status = '''            ServerStatusAnimation(serverRunning)
            Spacer(Modifier.height(4.dp))
            Text(
                if (serverRunning) "RUNNING • ${localIpv4() ?: "0.0.0.0"}:$serverPort" else "STOPPED"
            )
            Spacer(Modifier.height(8.dp))
            Button(
'''
    if old_status in s:
        s = s.replace(old_status, new_status, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("NetFTPLab fixes and server animation applied")


if __name__ == "__main__":
    main()
