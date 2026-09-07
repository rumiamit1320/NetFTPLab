package com.netftplab

import android.Manifest
import android.content.*
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import com.google.zxing.BarcodeFormat
import com.google.zxing.MultiFormatWriter
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.*
import java.io.*
import java.net.*
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.min

data class Device(val ip: String, val host: String = "Unknown", val services: List<Int> = emptyList(), val latencyMs: Long? = null)
data class LogLine(val time: String, val layer: String, val text: String)
data class SessionStats(val rttMs: Long = 0, val connected: Boolean = false, val target: String = "", val bytes: Long = 0, val throughputBps: Long = 0)
data class RemoteEntry(val name: String, val size: Long, val directory: Boolean)
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
    private var ftp: FtpClient? = null
    private lateinit var server: FtpServer
    private lateinit var transferRoot: File
    private lateinit var serverRoot: File

    private val openDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) uploadUri(uri)
    }

    private val importToServerDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importToServer(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        transferRoot = File(getExternalFilesDir(null), "NetFTPLabTransfers").apply { mkdirs() }
        serverRoot = File(getExternalFilesDir(null), "NetFTPShare").apply { mkdirs() }
        server = FtpServer(serverRoot, logger = ::log)
        if (android.os.Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
        setContent { NetFtpApp() }
    }

    override fun onDestroy() { try { ftp?.close() } catch (_: Exception) {}; server.stop(); super.onDestroy() }

    private fun log(layer: String, text: String) {
        val t = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())
        runOnUiThread { logs.add(LogLine(t, layer, text)); while (logs.size > 800) logs.removeAt(0); if (layer == "DATA" && text.startsWith("STOR ")) refreshServerFiles() }
    }

    private fun localIpv4(): String? {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val lp = cm.getLinkProperties(cm.activeNetwork) ?: return null
        return lp.linkAddresses.firstOrNull { it.address is Inet4Address }?.address?.hostAddress
    }

    private fun localSubnet(): String? = localIpv4()?.substringBeforeLast('.')

    private fun scanNetwork() {
        if (scanning) return
        scanning = true; discovered.clear(); log("DISCOVERY", "Starting active LAN discovery")
        val subnet = localSubnet()
        if (subnet == null) { log("ERROR", "No IPv4 LAN interface found"); scanning = false; return }
        log("DISCOVERY", "Probing $subnet.0/24: FTP 21/2121, HTTP 80/443")
        lifecycleScope.launch(Dispatchers.IO) {
            val found = Collections.synchronizedList(mutableListOf<Device>())
            coroutineScope {
                (1..254).map { n -> async {
                    val ip = "$subnet.$n"; val open = mutableListOf<Int>(); var latency: Long? = null
                    listOf(21, 2121, 80, 443).forEach { p ->
                        val t = System.currentTimeMillis()
                        try { Socket().use { s -> s.connect(InetSocketAddress(ip, p), 220); if (latency == null) latency = System.currentTimeMillis() - t; open += p } } catch (_: Exception) {}
                    }
                    if (open.isNotEmpty()) found += Device(ip, services = open, latencyMs = latency)
                } }.awaitAll()
            }
            withContext(Dispatchers.Main) {
                discovered.addAll(found.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 })
                log("DISCOVERY", "Scan complete: ${found.size} active service-bearing devices")
                scanning = false
            }
        }
    }

    private fun connect(device: Device) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                ftp?.close()
                val port = when { 2121 in device.services -> 2121; 21 in device.services -> 21; else -> return@launch }
                log("TCP", "Opening FTP control connection ${device.ip}:$port")
                val client = FtpClient(device.ip, port, ::log)
                client.connect(); client.login("anonymous", "anonymous@netftp.local")
                ftp = client
                connectedTarget = "${device.ip}:$port"
                session = SessionStats(rttMs = 0, connected = true, target = connectedTarget)
                refreshRemote()
            } catch (e: Exception) { log("ERROR", "Connection failed: ${e.message}") }
        }
    }

    private fun refreshRemote() {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val listing = ftp?.list() ?: return@launch
                val parsed = parseListing(listing)
                withContext(Dispatchers.Main) { remoteFiles.clear(); remoteFiles.addAll(parsed) }
                log("FTP", "Remote directory refreshed: ${parsed.size} entries")
            } catch (e: Exception) { log("ERROR", "LIST failed: ${e.message}") }
        }
    }

    private fun parseListing(text: String): List<RemoteEntry> = text.lineSequence().mapNotNull { line ->
        val s = line.trim(); if (s.isBlank()) return@mapNotNull null
        val parts = s.split(Regex("\\s+"), limit = 9)
        if (parts.size >= 9) RemoteEntry(parts[8], parts[4].toLongOrNull() ?: 0, parts[0].startsWith("d")) else RemoteEntry(s, 0, false)
    }.filterNot { it.name == "." || it.name == ".." }.toList()

    private fun uploadUri(uri: Uri) {
        val target = connectedTarget; if (target.isBlank()) { log("ERROR", "Connect to an FTP device first"); return }
        val name = queryDisplayName(uri) ?: "upload-${System.currentTimeMillis()}"
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val size = contentLength(uri)
                val remoteExisting = ftp?.remoteSize(name) ?: -1L
                var skip = if (remoteExisting > 0 && size > remoteExisting) remoteExisting else 0L
                val input = contentResolver.openInputStream(uri) ?: throw IOException("Cannot open selected file")
                if (skip > 0) { var left = skip; while (left > 0) { val n = input.skip(left); if (n <= 0) break; left -= n }; skip -= left }
                val started = System.currentTimeMillis()
                transfer = TransferState(true, "UPLOAD", name, skip, size, 0, if (skip > 0) "Resuming" else "Starting")
                ftp?.upload(name, input, size, skip) { done, total ->
                    val elapsed = maxOf(1, System.currentTimeMillis() - started); transfer = transfer.copy(done = done, total = total, speedBps = done * 1000 / elapsed, message = "Transferring")
                }
                input.close(); verifyRemote(name, uri, size)
            } catch (e: Exception) { transfer = transfer.copy(active = false, message = "Upload failed: ${e.message}"); log("ERROR", "Upload failed: ${e.message}") }
            finally { refreshRemote() }
        }
    }

    private fun download(entry: RemoteEntry) {
        if (entry.directory) return
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val outFile = File(transferRoot, entry.name).canonicalFile
                if (!outFile.path.startsWith(transferRoot.canonicalPath + File.separator)) throw IOException("Unsafe filename")
                val remoteSize = ftp?.remoteSize(entry.name) ?: entry.size
                val resume = if (outFile.exists()) min(outFile.length(), remoteSize) else 0L
                val started = System.currentTimeMillis()
                transfer = TransferState(true, "DOWNLOAD", entry.name, resume, remoteSize, 0, if (resume > 0) "Resuming" else "Starting")
                RandomAccessFile(outFile, "rw").use { raf ->
                    raf.setLength(resume); raf.seek(resume)
                    val out = object : OutputStream() {
                        override fun write(b: Int) { raf.write(b) }
                        override fun write(b: ByteArray, off: Int, len: Int) { raf.write(b, off, len) }
                    }
                    ftp?.download(entry.name, out, resume) { done, total ->
                        val elapsed = maxOf(1, System.currentTimeMillis() - started); transfer = transfer.copy(done = done, total = total, speedBps = done * 1000 / elapsed, message = "Transferring")
                    }
                    out.flush()
                }
                val localHash = sha256(outFile); val remoteHash = ftp?.remoteSha256(entry.name).orEmpty()
                val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }
                transfer = transfer.copy(active = false, message = "Complete", sha256Local = localHash, sha256Remote = remoteHash, verified = verified)
                session = session.copy(bytes = session.bytes + outFile.length(), throughputBps = if (outFile.length() > 0) outFile.length() * 1000 / maxOf(1, System.currentTimeMillis() - started))
                log("DATA", "Saved ${outFile.absolutePath}; SHA-256 $localHash")
            } catch (e: Exception) { transfer = transfer.copy(active = false, message = "Download failed: ${e.message}"); log("ERROR", "Download failed: ${e.message}") }
        }
    }

    private fun verifyRemote(name: String, uri: Uri, size: Long) {
        val remoteHash = ftp?.remoteSha256(name).orEmpty(); val localHash = contentSha256(uri)
        val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }
        transfer = transfer.copy(active = false, message = "Complete", sha256Local = localHash, sha256Remote = remoteHash, verified = verified)
        session = session.copy(bytes = session.bytes + size)
        log("DATA", "Upload complete; local SHA-256=$localHash remote SHA-256=${remoteHash.ifBlank { "unsupported" }}")
    }

    private fun contentLength(uri: Uri): Long = contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else -1L } ?: -1L
    private fun queryDisplayName(uri: Uri): String? = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    private fun contentSha256(uri: Uri): String = contentResolver.openInputStream(uri)?.use { sha256(it) } ?: ""
    private fun sha256(file: File): String = FileInputStream(file).use { sha256(it) }
    private fun sha256(input: InputStream): String { val md = MessageDigest.getInstance("SHA-256"); val b = ByteArray(64 * 1024); while (true) { val n = input.read(b); if (n < 0) break; md.update(b, 0, n) }; return md.digest().joinToString("") { "%02x".format(it) } }

    private fun refreshServerFiles() {
        if (!::serverRoot.isInitialized) return
        val files = serverRoot.listFiles()?.sortedWith(compareBy<File>({ !it.isDirectory }, { it.name.lowercase(Locale.US) })).orEmpty()
        serverFiles.clear()
        serverFiles.addAll(files)
    }

    private fun importToServer(uri: Uri) {
        val name = queryDisplayName(uri)?.replace("/", "_")?.replace("\\", "_")?.ifBlank { "shared-${System.currentTimeMillis()}" }
            ?: "shared-${System.currentTimeMillis()}"
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val destination = File(serverRoot, name).canonicalFile
                if (!destination.path.startsWith(serverRoot.canonicalPath + File.separator)) throw IOException("Unsafe filename")
                val input = contentResolver.openInputStream(uri) ?: throw IOException("Cannot open selected file")
                input.use { source -> FileOutputStream(destination).use { out -> source.copyTo(out, 64 * 1024) } }
                withContext(Dispatchers.Main) { refreshServerFiles() }
                log("DATA", "Phone share ready: ${destination.name} (${destination.length()} bytes)")
            } catch (e: Exception) { log("ERROR", "Preparing phone-to-laptop share failed: ${e.message}") }
        }
    }

    private fun deleteServerFile(file: File) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val canonical = file.canonicalFile
                if (!canonical.path.startsWith(serverRoot.canonicalPath + File.separator)) throw IOException("Unsafe path")
                if (canonical.isFile && canonical.delete()) {
                    withContext(Dispatchers.Main) { refreshServerFiles() }
                    log("DATA", "Server share deleted: ${canonical.name}")
                } else log("ERROR", "Could not delete ${canonical.name}")
            } catch (e: Exception) { log("ERROR", "Delete failed: ${e.message}") }
        }
    }

    private fun toggleServer() {
        if (serverRunning) { server.stop(); serverRunning = false; return }
        try { server.start(); serverRunning = true; log("SERVER", "Embedded FTP server active on ${localIpv4() ?: "0.0.0.0"}:$serverPort") }
        catch (e: Exception) { log("ERROR", "Server start failed: ${e.message}") }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable fun NetFtpApp() {
        var tab by remember { mutableIntStateOf(0) }
        MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFF60A5FA), secondary = Color(0xFF34D399), background = Color(0xFF080B10), surface = Color(0xFF11161E))) {
            Scaffold(
                topBar = { TopAppBar(title = { Text("NetFTP Lab") }, actions = { IconButton(onClick = ::scanNetwork) { Icon(Icons.Default.Refresh, "Scan") } }) },
                bottomBar = { NavigationBar { listOf("Devices" to Icons.Default.Devices, "Transfers" to Icons.Default.SwapVert, "Console" to Icons.Default.Terminal, "Network Lab" to Icons.Default.Timeline, "Server" to Icons.Default.Settings).forEachIndexed { i, x -> NavigationBarItem(selected = tab == i, onClick = { tab = i }, icon = { Icon(x.second, null) }, label = { Text(x.first) }) } } }
            ) { pad -> Box(Modifier.padding(pad).fillMaxSize()) {
                when (tab) {
                    0 -> DevicesTab()
                    1 -> TransfersTab()
                    2 -> ConsoleTab()
                    3 -> NetworkLabTab()
                    else -> ServerTab()
                }
                if (showQr) QrDialog()
            } }
        }
    }

    @Composable private fun DevicesTab() {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Button(onClick = ::scanNetwork, enabled = !scanning, modifier = Modifier.fillMaxWidth()) { Text(if (scanning) "Scanning…" else "Scan LAN") }
            Spacer(Modifier.height(12.dp))
            if (discovered.isEmpty()) Text("No devices discovered yet.", style = MaterialTheme.typography.bodyMedium)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(discovered) { d ->
                    Card(Modifier.fillMaxWidth().clickable { connect(d) }) {
                        Column(Modifier.padding(14.dp)) {
                            Text(d.ip, style = MaterialTheme.typography.titleMedium)
                            Text("Services: ${d.services.joinToString()}${d.latencyMs?.let { " • ${it} ms" } ?: ""}")
                        }
                    }
                }
            }
        }
    }

    @Composable private fun TransfersTab() {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text(if (connectedTarget.isBlank()) "Not connected" else "Connected: $connectedTarget", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = { openDocument.launch(arrayOf("*/*")) }, enabled = connectedTarget.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Upload") }
                OutlinedButton(onClick = ::refreshRemote, enabled = connectedTarget.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Refresh") }
            }
            Spacer(Modifier.height(12.dp))
            if (transfer.active || transfer.message != "Idle") {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
                    Text("${transfer.direction}: ${transfer.name}")
                    Spacer(Modifier.height(6.dp))
                    if (transfer.total > 0) LinearProgressIndicator(progress = { (transfer.done.toFloat() / transfer.total).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                    Text("${transfer.message} • ${transfer.done}/${transfer.total} bytes • ${transfer.speedBps} B/s")
                    if (transfer.sha256Local.isNotBlank()) Text("SHA-256 local: ${transfer.sha256Local}")
                    if (transfer.sha256Remote.isNotBlank()) Text("SHA-256 remote: ${transfer.sha256Remote}")
                    transfer.verified?.let { Text(if (it) "Integrity: VERIFIED" else "Integrity: MISMATCH") }
                } }
            }
            Spacer(Modifier.height(12.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(remoteFiles) { f -> Card(Modifier.fillMaxWidth().clickable { download(f) }) { Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) { Icon(if (f.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null); Spacer(Modifier.width(10.dp)); Column { Text(f.name); Text(if (f.directory) "Directory" else "${f.size} bytes") } } } }
            }
        }
    }

    @Composable private fun ConsoleTab() {
        LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) { items(logs) { l -> Text("${l.time} [${l.layer}] ${l.text}", fontFamily = FontFamily.Monospace) } }
    }

    @Composable private fun NetworkLabTab() {
        val scroll = rememberScrollState()
        Column(Modifier.fillMaxSize().verticalScroll(scroll).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("ALOHA / CSMA-CA / TCP congestion models", style = MaterialTheme.typography.titleLarge)
            Text("Pure ALOHA: S = G exp(-2G)")
            Text("Slotted ALOHA: S = G exp(-G)")
            Text("TCP Reno/CUBIC/BBR traces are educational models; the app does not claim physical Wi-Fi collision visibility.")
        }
    }

    @Composable private fun ServerTab() {
        LaunchedEffect(Unit) { refreshServerFiles() }
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Embedded FTP Server", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            Text(if (serverRunning) "RUNNING • ${localIpv4() ?: "0.0.0.0"}:$serverPort" else "STOPPED")
            Spacer(Modifier.height(8.dp))
            Button(onClick = ::toggleServer, modifier = Modifier.fillMaxWidth()) { Text(if (serverRunning) "Stop Server" else "Start Server") }
            Spacer(Modifier.height(12.dp))
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
                Text("Shared folder: NetFTPShare", style = MaterialTheme.typography.titleMedium)
                Text("Files added here are available to the laptop through FTP.")
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(onClick = { importToServerDocument.launch(arrayOf("*/*")) }, modifier = Modifier.weight(1f)) { Text("Add to Share") }
                    OutlinedButton(onClick = ::refreshServerFiles, modifier = Modifier.weight(1f)) { Text("Refresh") }
                }
            } }
            Spacer(Modifier.height(10.dp))
            Text("Shared Files", style = MaterialTheme.typography.titleMedium)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(serverFiles) { f -> Card(Modifier.fillMaxWidth()) { Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) { Column(Modifier.weight(1f)) { Text(f.name); Text("${f.length()} bytes • ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date(f.lastModified()))}") }; IconButton(onClick = { deleteServerFile(f) }) { Icon(Icons.Default.Delete, "Delete") } } } }
            }
            Spacer(Modifier.height(10.dp))
            Text("PHONE → LAPTOP", style = MaterialTheme.typography.titleMedium)
            Text("1. Add a phone file to the share.\n2. Start the server.\n3. On the laptop open ftp://${localIpv4() ?: "PHONE_IP"}:$serverPort\n4. Download the file.")
        }
    }

    @Composable private fun QrDialog() {
        AlertDialog(onDismissRequest = { showQr = false }, confirmButton = { TextButton(onClick = { showQr = false }) { Text("Close") } }, title = { Text("FTP endpoint") }, text = { Text("ftp://${localIpv4() ?: "PHONE_IP"}:$serverPort") })
    }
}
