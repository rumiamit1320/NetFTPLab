package com.netftplab

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.ClipData
import android.content.ContentValues
import android.app.NotificationChannel
import android.app.NotificationManager
import androidx.core.app.NotificationCompat
import androidx.core.content.FileProvider
import android.net.ConnectivityManager
import android.net.Uri
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import android.graphics.Canvas
import android.os.Bundle
import android.os.Environment
import android.provider.OpenableColumns
import android.provider.MediaStore
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.Canvas
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.*
import java.io.*
import java.net.*
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.*
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import kotlin.math.min

data class Device(val ip: String, val host: String = "Unknown", val services: List<Int> = emptyList(), val latencyMs: Long? = null)
data class LogLine(val time: String, val layer: String, val text: String)
data class SessionStats(val rttMs: Long = 0, val connected: Boolean = false, val target: String = "", val bytes: Long = 0, val throughputBps: Long = 0)
data class RemoteEntry(val name: String, val size: Long, val directory: Boolean, val path: String = name)
data class TransferState(
    val active: Boolean = false,
    val direction: String = "",
    val name: String = "",
    val done: Long = 0,
    val total: Long = -1,
    val speedBps: Long = 0,
    val message: String = "Idle",
    val sha256Local: String = "",
    val sha256Remote: String = "",
    val verified: Boolean? = null
)

class MainActivity : ComponentActivity() {
    private val discovered = mutableStateListOf<Device>()
    private val logs = mutableStateListOf<LogLine>()
    private val remoteFiles = mutableStateListOf<RemoteEntry>()
    private val serverFiles = mutableStateListOf<File>()

    private var scanning by mutableStateOf(false)
    private var connectedTarget by mutableStateOf("")
    private var serverRunning by mutableStateOf(false)
    private var serverPort by mutableIntStateOf(2121)
    private var transfer by mutableStateOf(TransferState())
    private var session by mutableStateOf(SessionStats())
    private var showQr by mutableStateOf(false)
    private val uploadQueue = ArrayDeque<Uri>()
    private val downloadQueue = ArrayDeque<RemoteEntry>()
    private var uploadQueueRunning by mutableStateOf(false)
    private var downloadQueueRunning by mutableStateOf(false)
    private val selectedRemoteNames = mutableStateListOf<String>()
    private var remoteRefreshRunning = false
    private var transferRefreshJob: Job? = null
    private val notificationChannelId = "netftp_server"

    private var ftp: FtpClient? = null
    private lateinit var server: FtpServer
    private lateinit var transferRoot: File
    private lateinit var serverRoot: File

    private val uploadDocument = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) queueUploads(uris)
    }

    private val shareDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importToServer(uri)
    }

    private val notificationPermissionLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted && serverRunning) showServerNotification()
        else if (!granted) log("SERVER", "Notification permission denied; FTP server remains available in-app")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        transferRoot = File(getExternalFilesDir(null), "NetFTPLabTransfers").apply { mkdirs() }
        serverRoot = File(getExternalFilesDir(null), "NetFTPShare").apply { mkdirs() }
        server = FtpServer(serverRoot, logger = ::log)
        createNotificationChannel()
        refreshServerFiles()
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        transferRefreshJob = lifecycleScope.launch {
            while (isActive) {
                delay(1800)
                if (serverRunning) withContext(Dispatchers.Main) { refreshServerFiles() }
                if (ftp != null && connectedTarget.isNotBlank() &&
                    !uploadQueueRunning && !downloadQueueRunning && !transfer.active && !remoteRefreshRunning) {
                    refreshRemote()
                }
            }
        }
        setContent { NetFtpApp() }
    }

    override fun onDestroy() {
        transferRefreshJob?.cancel()
        try { ftp?.close() } catch (_: Exception) { }
        server.stop()
        cancelServerNotification()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(
                notificationChannelId,
                "NetFTP Server",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "NetFTP Lab embedded FTP server status" }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun showServerNotification() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return
        val notification = NotificationCompat.Builder(this, notificationChannelId)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("NetFTP Lab FTP server")
            .setContentText("Server running on ${localIpv4() ?: "LAN"}:$serverPort")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        getSystemService(NotificationManager::class.java).notify(2121, notification)
    }

    private fun cancelServerNotification() {
        getSystemService(NotificationManager::class.java).cancel(2121)
    }

    private fun log(layer: String, text: String) {
        val time = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())
        runOnUiThread {
            logs.add(LogLine(time, layer, text))
            while (logs.size > 800) logs.removeAt(0)
            if (layer == "DATA" && text.startsWith("STOR ")) refreshServerFiles()
        }
    }

    private fun localIpv4(): String? {
        val interfaces = try { NetworkInterface.getNetworkInterfaces()?.toList().orEmpty() } catch (_: Exception) { emptyList() }
        val preferred = interfaces.sortedBy { iface -> if (iface.name.equals("wlan0", true) || iface.name.startsWith("wlan", true)) 0 else 1 }
        for (iface in preferred) {
            if (!iface.isUp || iface.isLoopback) continue
            for (address in iface.inetAddresses.toList()) {
                val ip = address.hostAddress ?: continue
                if (address is Inet4Address && !address.isLoopbackAddress && !address.isLinkLocalAddress) return ip
            }
        }
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val lp = cm.activeNetwork?.let { cm.getLinkProperties(it) }
        return lp?.linkAddresses?.firstOrNull { it.address is Inet4Address && !it.address.isLoopbackAddress && !it.address.isLinkLocalAddress }?.address?.hostAddress
    }

    private fun localSubnet(): String? = localIpv4()?.substringBeforeLast('.')

    private fun arpNeighborIps(): Set<String> {
        return try {
            File("/proc/net/arp").useLines { lines ->
                lines.drop(1).mapNotNull { line ->
                    val parts = line.trim().split(Regex("\\s+"))
                    parts.firstOrNull()?.takeIf { ip ->
                        ip.count { it == '.' } == 3 && ip != "0.0.0.0"
                    }
                }.toSet()
            }
        } catch (_: Exception) {
            emptySet()
        }
    }

    private fun scanNetwork() {
        if (scanning) return
        scanning = true
        discovered.clear()
        log("DISCOVERY", "Starting active LAN discovery")
        val subnet = localSubnet()
        if (subnet == null) {
            log("ERROR", "No IPv4 LAN interface found")
            scanning = false
            return
        }
        log("DISCOVERY", "Probing $subnet.0/24: FTP 21/2121, HTTP 80/443")
        lifecycleScope.launch(Dispatchers.IO) {
            val found = Collections.synchronizedList(mutableListOf<Device>())
            val neighborIps = arpNeighborIps().filter { it.startsWith("$subnet.") }.toSet()
            coroutineScope {
                (1..254).map { n ->
                    async {
                        val ip = "$subnet.$n"
                        val open = mutableListOf<Int>()
                        var latency: Long? = null
                        listOf(21, 2121, 80, 443).forEach { port ->
                            val start = System.currentTimeMillis()
                            try {
                                Socket().use { socket ->
                                    socket.connect(InetSocketAddress(ip, port), 220)
                                    if (latency == null) latency = System.currentTimeMillis() - start
                                    open += port
                                }
                            } catch (_: Exception) { }
                        }
                        if (open.isNotEmpty()) {
                            val resolvedName = try {
                                val hostName = InetAddress.getByName(ip).canonicalHostName
                                if (hostName.isNullOrBlank() || hostName == ip) "Unknown" else hostName
                            } catch (_: Exception) { "Unknown" }
                            found += Device(ip, host = resolvedName, services = open, latencyMs = latency)
                        }
                    }
                }.awaitAll()
            }
            val serviceIps = found.map { it.ip }.toSet()
            neighborIps.filter { it != localIpv4() && it !in serviceIps }.forEach { ip ->
                found += Device(ip, host = "Unknown", services = emptyList(), latencyMs = null)
            }
            withContext(Dispatchers.Main) {
                discovered.addAll(found.distinctBy { it.ip }.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 })
                log("DISCOVERY", "Scan complete: ${found.size} LAN devices/neighbors; ${serviceIps.size} service-bearing")
                scanning = false
            }
        }
    }

    private fun connect(device: Device) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                ftp?.close()
                val port = when {
                    2121 in device.services -> 2121
                    21 in device.services -> 21
                    else -> return@launch
                }
                log("TCP", "Opening FTP control connection ${device.ip}:$port")
                val client = FtpClient(device.ip, port, ::log)
                client.connect()
                client.login("anonymous", "anonymous@netftp.local")
                ftp = client
                connectedTarget = "${device.ip}:$port"
                session = SessionStats(rttMs = device.latencyMs ?: 0L, connected = true, target = connectedTarget)
                log("TCP", "FTP session established to $connectedTarget")
                refreshRemote()
            } catch (e: Exception) {
                ftp = null
                connectedTarget = ""
                session = SessionStats()
                log("ERROR", "Connection failed: ${e.message}")
            }
        }
    }

    private fun disconnect() {
        try { ftp?.quit() } catch (_: Exception) {
            try { ftp?.close() } catch (_: Exception) { }
        }
        ftp = null
        connectedTarget = ""
        session = SessionStats()
        remoteFiles.clear()
        transfer = TransferState(message = "Disconnected")
        log("TCP", "FTP client disconnected")
    }

    private fun refreshRemote() {
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

    private fun parseListing(text: String, basePath: String = ""): List<RemoteEntry> {
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

    private fun queueUploads(uris: List<Uri>) {
        uploadQueue.addAll(uris)
        transfer = transfer.copy(active = false, message = "Queued ${uris.size} file(s)")
        log("DATA", "Queued ${uris.size} file(s) for upload")
        if (uploadQueueRunning) return
        uploadQueueRunning = true
        lifecycleScope.launch(Dispatchers.IO) {
            while (true) {
                if (uploadQueue.isEmpty()) break
                val uri = uploadQueue.removeFirst()
                uploadUriNow(uri)
            }
            withContext(Dispatchers.Main) { uploadQueueRunning = false }
            // Refresh only after the complete upload queue has finished, so
            // LIST cannot overlap the next upload's SIZE/EPSV/STOR sequence.
            refreshRemote()
        }
    }

    private suspend fun uploadUriNow(uri: Uri) {
        val client = ftp
        if (client == null || connectedTarget.isBlank()) {
            transfer = TransferState(message = "Not connected — select a device in Devices first")
            log("ERROR", "Upload requested without an FTP client connection")
            return
        }
        val name = queryDisplayName(uri) ?: "upload-${System.currentTimeMillis()}"
            try {
                val size = contentLength(uri)
                val existing = client.remoteSize(name)
                var skip = if (existing > 0 && size > existing) existing else 0L
                val input = contentResolver.openInputStream(uri)
                    ?: throw IOException("Cannot open selected file")
                if (skip > 0) {
                    var left = skip
                    while (left > 0) {
                        val skipped = input.skip(left)
                        if (skipped <= 0) break
                        left -= skipped
                    }
                    skip -= left
                }
                val start = System.currentTimeMillis()
                transfer = TransferState(
                    active = true,
                    direction = "UPLOAD",
                    name = name,
                    done = skip,
                    total = size,
                    message = if (skip > 0) "Resuming" else "Starting"
                )
                client.upload(name, input, size, skip) { done, total ->
                    val elapsed = maxOf(1L, System.currentTimeMillis() - start)
                    val speed = done * 1000L / elapsed
                    transfer = transfer.copy(
                        done = done,
                        total = total,
                        speedBps = speed,
                        message = "Transferring"
                    )
                    session = session.copy(bytes = done, throughputBps = speed)
                }
                input.close()
                verifyRemote(name, uri, size)
            } catch (e: Exception) {
                transfer = transfer.copy(active = false, message = "Upload failed: ${e.message}")
                log("ERROR", "Upload failed: ${e.message}")
            }
    }

    private fun queueDownloads(entries: List<RemoteEntry>) {
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

    private fun publishToDownloads(source: File, relativePath: String) {
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

    private fun verifyRemote(name: String, uri: Uri, size: Long) {
        val remoteHash = ftp?.remoteSha256(name).orEmpty()
        val localHash = contentSha256(uri)
        transfer = transfer.copy(
            active = false,
            message = "Complete",
            sha256Local = localHash,
            sha256Remote = remoteHash,
            verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }
        )
        session = session.copy(bytes = session.bytes + size)
        log("DATA", "Upload complete; local SHA-256=$localHash remote SHA-256=${remoteHash.ifBlank { "unsupported" }}")
    }

    private fun contentLength(uri: Uri): Long {
        return contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst() && !cursor.isNull(0)) cursor.getLong(0) else -1L
        } ?: -1L
    }

    private fun queryDisplayName(uri: Uri): String? {
        return contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        }
    }

    private fun contentSha256(uri: Uri): String {
        return contentResolver.openInputStream(uri)?.use { sha256(it) } ?: ""
    }

    private fun sha256(file: File): String = FileInputStream(file).use { sha256(it) }

    private fun sha256(input: InputStream): String {
        val md = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            md.update(buffer, 0, n)
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    private fun refreshServerFiles() {
        serverFiles.clear()
        val files = serverRoot.listFiles()?.filter { it.exists() }?.sortedWith(
            compareBy<File> { !it.isDirectory }.thenBy { it.name.lowercase(Locale.US) }
        ).orEmpty()
        serverFiles.addAll(files)
    }




















    private fun importToServer(uri: Uri) {
        val name = (queryDisplayName(uri)
            ?.replace("/", "_")
            ?.replace("\\", "_")
            ?.ifBlank { "shared-${System.currentTimeMillis()}" }
            ?: "shared-${System.currentTimeMillis()}")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val destination = File(serverRoot, name).canonicalFile
                if (!destination.path.startsWith(serverRoot.canonicalPath + File.separator)) {
                    throw IOException("Unsafe filename")
                }
                contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(destination).use { output ->
                        input.copyTo(output, 64 * 1024)
                    }
                } ?: throw IOException("Cannot open selected file")
                withContext(Dispatchers.Main) { refreshServerFiles() }
                log("DATA", "Phone share ready: ${destination.name} (${destination.length()} bytes)")
            } catch (e: Exception) {
                log("ERROR", "Preparing phone-to-laptop share failed: ${e.message}")
            }
        }
    }

    private fun saveServerFileToPhone(file: File) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val source = file.canonicalFile
                if (!source.path.startsWith(serverRoot.canonicalPath + File.separator) || !source.isFile) throw IOException("Invalid shared file")
                if (android.os.Build.VERSION.SDK_INT >= 29) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, source.name)
                        put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
                        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/NetFTPLab")
                        put(MediaStore.Downloads.IS_PENDING, 1)
                    }
                    val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                        ?: throw IOException("Cannot create Downloads entry")
                    try {
                        contentResolver.openOutputStream(uri)?.use { output -> source.inputStream().use { it.copyTo(output, 64 * 1024) } }
                            ?: throw IOException("Cannot open Downloads output")
                        values.clear(); values.put(MediaStore.Downloads.IS_PENDING, 0)
                        contentResolver.update(uri, values, null, null)
                    } catch (e: Exception) {
                        contentResolver.delete(uri, null, null)
                        throw e
                    }
                    withContext(Dispatchers.Main) {
                        transfer = TransferState(direction = "SERVER → DOWNLOADS", name = source.name, done = source.length(), total = source.length(), message = "Saved to Downloads/NetFTPLab")
                    }
                    log("DATA", "Saved ${source.name} to public Downloads/NetFTPLab (${source.length()} bytes)")
                } else {
                    val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "NetFTPLab").apply { mkdirs() }
                    val destination = File(dir, source.name).canonicalFile
                    source.inputStream().use { input -> destination.outputStream().use { output -> input.copyTo(output, 64 * 1024) } }
                    transfer = TransferState(direction = "SERVER → DOWNLOADS", name = source.name, done = destination.length(), total = destination.length(), message = "Saved to Downloads/NetFTPLab")
                    log("DATA", "Saved ${source.name} to public Downloads/NetFTPLab (${destination.length()} bytes)")
                }
            } catch (e: Exception) {
                log("ERROR", "Saving to Downloads failed: ${e.message}")
            }
        }
    }

    private fun deleteServerFile(file: File) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val target = file.canonicalFile
                if (!target.path.startsWith(serverRoot.canonicalPath + File.separator)) {
                    throw IOException("Unsafe path")
                }
                if (target.isFile && target.delete()) {
                    withContext(Dispatchers.Main) { refreshServerFiles() }
                    log("DATA", "Server share deleted: ${target.name}")
                } else {
                    log("ERROR", "Could not delete ${target.name}")
                }
            } catch (e: Exception) {
                log("ERROR", "Delete failed: ${e.message}")
            }
        }
    }

    private fun toggleServer() {
        if (serverRunning) {
            server.stop()
            serverRunning = false
            cancelServerNotification()
            log("SERVER", "Embedded FTP server stopped")
        } else {
            try {
                server.start()
                serverRunning = true
                showServerNotification()
                log("SERVER", "Embedded FTP server active on ${localIpv4() ?: "0.0.0.0"}:$serverPort")
            } catch (e: Exception) {
                log("ERROR", "Server start failed: ${e.message}")
            }
        }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun NetFtpApp() {
        var tab by remember { mutableIntStateOf(0) }
        val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
        val scope = rememberCoroutineScope()
        val closeDrawer: () -> Unit = { scope.launch { drawerState.close() }; Unit }
        MaterialTheme(
            colorScheme = darkColorScheme(
                primary = Color(0xFF60A5FA),
                secondary = Color(0xFF34D399),
                background = Color(0xFF080B10),
                surface = Color(0xFF11161E)
            )
        ) {
            ModalNavigationDrawer(
                drawerState = drawerState,
                drawerContent = {
                    AdvancedNetworkDrawer(
                        drawerState = drawerState,
                        transfer = transfer,
                        session = session,
                        logs = logs,
                        serverRunning = serverRunning,
                        connectedTarget = connectedTarget,
                        onClose = closeDrawer
                    )
                }
            ) {
                Scaffold(
                    topBar = {
                        TopAppBar(
                            navigationIcon = {
                                IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                    Icon(Icons.Default.Menu, "Advanced network monitor")
                                }
                            },
                            title = { Text("NetFTP Lab") },
                            actions = {
                                IconButton(onClick = { scanNetwork() }) {
                                    Icon(Icons.Default.Refresh, "Scan")
                                }
                            }
                        )
                    },
                    bottomBar = {
                        NavigationBar {
                            val tabs = listOf(
                                "Devices" to Icons.Default.Devices,
                                "Transfers" to Icons.Default.SwapVert,
                                "Console" to Icons.Default.Terminal,
                                "Network Lab" to Icons.Default.Timeline,
                                "Server" to Icons.Default.Settings
                            )
                            tabs.forEachIndexed { index, item ->
                                NavigationBarItem(
                                    selected = tab == index,
                                    onClick = { tab = index },
                                    icon = { Icon(item.second, null) },
                                    label = { Text(item.first) }
                                )
                            }
                        }
                    }
                ) { padding ->
                    Box(Modifier.padding(padding).fillMaxSize()) {
                        when (tab) {
                            0 -> DevicesTab()
                            1 -> TransfersTab()
                            2 -> ConsoleTab()
                            3 -> NetworkLabTab()
                            else -> ServerTab()
                        }
                        if (showQr) QrDialog()
                    }
                }
            }
        }
    }

    @Composable
    private fun DevicesTab() {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Button(
                onClick = { scanNetwork() },
                enabled = !scanning,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (scanning) "Scanning…" else "Scan LAN")
            }
            Spacer(Modifier.height(12.dp))
            if (discovered.isEmpty()) Text("No devices discovered yet.")
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(discovered) { device ->
                    Card(
                        Modifier.fillMaxWidth().clickable { connect(device) }
                    ) {
                        Column(Modifier.padding(14.dp)) {
                            Text(
                                if (device.host.isBlank() || device.host == "Unknown") device.ip
                                else device.host,
                                style = MaterialTheme.typography.titleMedium
                            )
                            Text(
                                "IP: ${device.ip}" +
                                    " • Services: ${device.services.joinToString()}" +
                                    (device.latencyMs?.let { " • $it ms" } ?: "")
                            )
                        }
                    }
                }
            }
        }
    }

    private suspend fun deleteRemoteEntry(entry: RemoteEntry) {
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
            val uris = existing.map { file -> FileProvider.getUriForFile(this, "${packageName}.fileprovider", file) }
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

    @Composable
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
                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }
                        OutlinedButton(onClick = { shareRemoteEntries(remoteSelection) }, enabled = remoteSelection.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Share") }
                        OutlinedButton(onClick = { queueDeleteRemote(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning && !uploadQueueRunning, modifier = Modifier.weight(1f)) { Text("Delete") }
                    }
                }
                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->
                    val checked = entry.path in selectedRemoteNames
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                                Checkbox(checked = checked, onCheckedChange = {
                                    if (it) {
                                        if (entry.path !in selectedRemoteNames) selectedRemoteNames.add(entry.path)
                                    } else {
                                        selectedRemoteNames.remove(entry.path)
                                    }
                                })
                                Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(entry.name)
                                    Text(if (entry.directory) "Folder" else "${entry.size} bytes")
                                }
                            }
                            Button(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Icon(Icons.Default.Download, null)
                                Spacer(Modifier.width(6.dp))
                                Text(if (entry.directory) "Download Folder" else "Download File")
                            }
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

    private fun copyConsoleLog() {
        val text = logs.joinToString("\n") { "${it.time} ${it.layer.padEnd(10)} ${it.text}" }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
        clipboard.setPrimaryClip(android.content.ClipData.newPlainText("NetFTP Lab Console", text))
        log("UI", "Console log copied to clipboard (${logs.size} lines)")
    }

    @Composable
    private fun ConsoleTab() {
        Column(Modifier.fillMaxSize().padding(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("PROTOCOL CONSOLE", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { copyConsoleLog() }) { Text("Copy") }
                TextButton(onClick = { logs.clear() }) { Text("Clear") }
            }
            LazyColumn(
                Modifier.fillMaxSize().background(Color(0xFF05070A)).padding(8.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp)
            ) {
                items(logs) { line ->
                    Text(
                        "${line.time} ${line.layer.padEnd(10)} ${line.text}",
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }

    @Composable
    private fun NetworkLabTab() {
        var mode by remember { mutableStateOf("ALOHA") }
        var offeredLoad by remember { mutableFloatStateOf(1f) }
        var congestion by remember { mutableStateOf("RENO") }
        val throughput = when (mode) {
            "SLOTTED" -> NetworkLab.slottedThroughput(offeredLoad.toDouble())
            "CSMA/CA" -> NetworkLab.csmaCaThroughput(offeredLoad.toDouble())
            else -> NetworkLab.alohaThroughput(offeredLoad.toDouble())
        }

        Column(
            Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("NETWORK LAB", style = MaterialTheme.typography.headlineSmall)
            Text("MAC models are educational; ordinary Android apps cannot read every Wi-Fi collision.")

            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("ALOHA", "SLOTTED", "CSMA/CA").forEach { selectedMode ->
                    OutlinedButton(onClick = { mode = selectedMode }) {
                        Text(if (mode == selectedMode) "[$selectedMode]" else selectedMode)
                    }
                }
            }

            Text("Offered load G: %.2f".format(offeredLoad))
            Slider(
                value = offeredLoad,
                onValueChange = { offeredLoad = it },
                valueRange = 0.05f..4f
            )

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("Throughput S = %.4f".format(throughput))
                    Text(
                        "Contention/collision index = %.1f%%".format(
                            (1.0 - throughput).coerceIn(0.0, 1.0) * 100.0
                        )
                    )
                }
            }

            Spacer(Modifier.height(10.dp))
            Text("TCP CONGESTION CONTROL", style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("RENO", "CUBIC", "BBR").forEach { selected ->
                    OutlinedButton(onClick = { congestion = selected }) {
                        Text(if (congestion == selected) "[$selected]" else selected)
                    }
                }
            }

            val trace = NetworkLab.cwndTrace(congestion)
            val maxY = trace.maxOf { it.y }.coerceAtLeast(1f)
            trace.takeLast(20).forEach { point ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${point.x.toInt()}", Modifier.width(30.dp))
                    LinearProgressIndicator(
                        progress = { (point.y / maxY).coerceIn(0f, 1f) },
                        modifier = Modifier.weight(1f)
                    )
                    Text(" %.1f".format(point.y), Modifier.width(45.dp))
                }
            }
            Text("cwnd trace is modeled, not kernel TCP telemetry.")
        }
    }

    @Composable
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
        LaunchedEffect(Unit) { refreshServerFiles() }
        Column(
            Modifier.fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {
            Text("Embedded FTP Server", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            ServerStatusAnimation(serverRunning)
            Text(
                if (serverRunning) "RUNNING • ${localIpv4() ?: "0.0.0.0"}:$serverPort" else "STOPPED"
            )
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = { toggleServer() },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (serverRunning) "Stop Server" else "Start Server")
            }

            Spacer(Modifier.height(12.dp))
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("Phone share folder: NetFTPShare", style = MaterialTheme.typography.titleMedium)
                    Text("Add to Share is phone → laptop only. FTP client Upload is a separate operation in Transfers.")
                    Spacer(Modifier.height(8.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Button(
                            onClick = { shareDocument.launch(arrayOf("*/*")) },
                            modifier = Modifier.weight(1f)
                        ) { Text("Add to Share") }
                        OutlinedButton(
                            onClick = { refreshServerFiles() },
                            modifier = Modifier.weight(1f)
                        ) { Text("Refresh") }
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Text("SHARED / INCOMING FILES", style = MaterialTheme.typography.titleMedium)
            Text("Laptop uploads and phone-shared files are stored in this FTP server folder.")
            Spacer(Modifier.height(6.dp))

            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                serverFiles.forEach { file ->
                    Card(Modifier.fillMaxWidth()) {
                        Row(
                            Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(file.name)
                                Text(
                                    "${file.length()} bytes • " +
                                        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                                            .format(Date(file.lastModified()))
                                )
                            }
                            if (file.isFile) {
                                IconButton(onClick = { saveServerFileToPhone(file) }) {
                                    Icon(Icons.Default.Download, "Save to phone")
                                }
                                IconButton(onClick = { shareFiles(listOf(file)) }) {
                                    Icon(Icons.Default.Share, "Share")
                                }
                            }
                            IconButton(onClick = {
                                if (deleteLocalEntry(file)) refreshServerFiles()
                            }) {
                                Icon(Icons.Default.Delete, "Delete")
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Text("PHONE ↔ LAPTOP", style = MaterialTheme.typography.titleMedium)
            Text(
                "Phone → laptop: Add to Share → Start Server → laptop opens " +
                    "ftp://${localIpv4() ?: "PHONE_IP"}:$serverPort.\n" +
                    "Laptop → phone: upload to this server → the file appears above → " +
                    "tap the Download icon to copy it into the phone transfer area."
            )
            Spacer(Modifier.height(6.dp))
            OutlinedButton(
                onClick = { showQr = true },
                enabled = localIpv4() != null,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Show QR / FTP Endpoint") }
        }
    }

    @Composable
    private fun QrDialog() {
        val ip = localIpv4()
        val endpoint = if (ip != null) "ftp://$ip:$serverPort" else ""
        AlertDialog(
            onDismissRequest = { showQr = false },
            confirmButton = { TextButton(onClick = { showQr = false }) { Text("Close") } },
            title = { Text("FTP endpoint") },
            text = {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    if (endpoint.isNotBlank()) {
                        val matrix = remember(endpoint) { QRCodeWriter().encode(endpoint, BarcodeFormat.QR_CODE, 640, 640) }
                        Canvas(Modifier.fillMaxWidth().aspectRatio(1f).padding(8.dp)) {
                            val sx = size.width / matrix.width
                            val sy = size.height / matrix.height
                            for (y in 0 until matrix.height) for (x in 0 until matrix.width) {
                                if (matrix.get(x, y)) drawRect(
                                    color = Color.Black,
                                    topLeft = androidx.compose.ui.geometry.Offset(x * sx, y * sy),
                                    size = androidx.compose.ui.geometry.Size(sx + 0.5f, sy + 0.5f)
                                )
                            }
                        }
                        Text(endpoint, fontFamily = FontFamily.Monospace)
                    } else Text("No LAN IPv4 address available")
                }
            }
        )
    }

}
