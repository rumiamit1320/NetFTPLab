package com.netftplab

import android.Manifest
import android.content.Context
import android.content.ContentValues
import android.app.NotificationChannel
import android.app.NotificationManager
import androidx.core.app.NotificationCompat
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
    private val notificationChannelId = "netftp_server"

    private var ftp: FtpClient? = null
    private lateinit var server: FtpServer
    private lateinit var transferRoot: File
    private lateinit var serverRoot: File

    private val uploadDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) uploadUri(uri)
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
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { NetFtpApp() }
    }
    override fun onDestroy() {
        try { ftp?.close() } catch (_: Exception) { }
        server.stop(); cancelServerNotification(); super.onDestroy()
    }
    private fun createNotificationChannel() {
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(notificationChannelId, "NetFTP Server", NotificationManager.IMPORTANCE_LOW).apply { description = "NetFTP Lab embedded FTP server status" }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }
    private fun showServerNotification() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return
        val notification = NotificationCompat.Builder(this, notificationChannelId).setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("NetFTP Lab FTP server").setContentText("Server running on ${localIpv4() ?: "LAN"}:$serverPort").setOngoing(true).setOnlyAlertOnce(true).setPriority(NotificationCompat.PRIORITY_LOW).build()
        getSystemService(NotificationManager::class.java).notify(2121, notification)
    }
    private fun cancelServerNotification() { getSystemService(NotificationManager::class.java).cancel(2121) }
    private fun log(layer: String, text: String) {
        val time = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())
        runOnUiThread { logs.add(LogLine(time, layer, text)); while (logs.size > 800) logs.removeAt(0); if (layer == "DATA" && text.startsWith("STOR ")) refreshServerFiles() }
    }
    private fun localIpv4(): String? {
        val interfaces = try { NetworkInterface.getNetworkInterfaces()?.toList().orEmpty() } catch (_: Exception) { emptyList() }
        val preferred = interfaces.sortedBy { iface -> if (iface.name.equals("wlan0", true) || iface.name.startsWith("wlan", true)) 0 else 1 }
        for (iface in preferred) { if (!iface.isUp || iface.isLoopback) continue; for (address in iface.inetAddresses.toList()) { val ip = address.hostAddress ?: continue; if (address is Inet4Address && !address.isLoopbackAddress && !address.isLinkLocalAddress) return ip } }
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val lp = cm.activeNetwork?.let { cm.getLinkProperties(it) }
        return lp?.linkAddresses?.firstOrNull { it.address is Inet4Address && !it.address.isLoopbackAddress && !it.address.isLinkLocalAddress }?.address?.hostAddress
    }
    private fun localSubnet(): String? = localIpv4()?.substringBeforeLast('.')
    private fun scanNetwork() {
        if (scanning) return; scanning = true; discovered.clear(); log("DISCOVERY", "Starting active LAN discovery")
        val subnet = localSubnet(); if (subnet == null) { log("ERROR", "No IPv4 LAN interface found"); scanning = false; return }
        log("DISCOVERY", "Probing $subnet.0/24: FTP 21/2121, HTTP 80/443")
        lifecycleScope.launch(Dispatchers.IO) {
            val found = Collections.synchronizedList(mutableListOf<Device>()); coroutineScope {
                (1..254).map { n -> async { val ip = "$subnet.$n"; val open = mutableListOf<Int>(); var latency: Long? = null; listOf(21, 2121, 80, 443).forEach { port -> val start = System.currentTimeMillis(); try { Socket().use { socket -> socket.connect(InetSocketAddress(ip, port), 220); if (latency == null) latency = System.currentTimeMillis() - start; open += port } } catch (_: Exception) {} }; if (open.isNotEmpty()) found += Device(ip, services = open, latencyMs = latency) } }.awaitAll()
            }
            withContext(Dispatchers.Main) { discovered.addAll(found.sortedBy { it.ip.substringAfterLast('.').toIntOrNull() ?: 999 }); log("DISCOVERY", "Scan complete: ${found.size} active service-bearing devices"); scanning = false }
        }
    }
    private fun connect(device: Device) {
        lifecycleScope.launch(Dispatchers.IO) { try { ftp?.close(); val port = when { 2121 in device.services -> 2121; 21 in device.services -> 21; else -> return@launch }; log("TCP", "Opening FTP control connection ${device.ip}:$port"); val client = FtpClient(device.ip, port, ::log); client.connect(); client.login("anonymous", "anonymous@netftp.local"); ftp = client; connectedTarget = "${device.ip}:$port"; session = SessionStats(connected = true, target = connectedTarget); log("TCP", "FTP session established to $connectedTarget"); refreshRemote() } catch (e: Exception) { ftp = null; connectedTarget = ""; session = SessionStats(); log("ERROR", "Connection failed: ${e.message}") } }
    }
    private fun disconnect() { try { ftp?.quit() } catch (_: Exception) { try { ftp?.close() } catch (_: Exception) {} }; ftp = null; connectedTarget = ""; session = SessionStats(); remoteFiles.clear(); transfer = TransferState(message = "Disconnected"); log("TCP", "FTP client disconnected") }
    private fun refreshRemote() { val client = ftp ?: return; lifecycleScope.launch(Dispatchers.IO) { try { val parsed = parseListing(client.list()); withContext(Dispatchers.Main) { remoteFiles.clear(); remoteFiles.addAll(parsed); session = session.copy(connected = true) } } catch (e: Exception) { log("ERROR", "LIST failed: ${e.message}"); if (client === ftp) { ftp = null; withContext(Dispatchers.Main) { connectedTarget = ""; session = SessionStats() } } } } }
    private fun parseListing(text: String): List<RemoteEntry> = text.lineSequence().mapNotNull { line -> val value = line.trim(); if (value.isBlank()) return@mapNotNull null; val parts = value.split(Regex("\\s+"), limit = 9); if (parts.size >= 9) RemoteEntry(parts[8], parts[4].toLongOrNull() ?: 0L, parts[0].startsWith("d")) else RemoteEntry(value, 0L, false) }.filterNot { it.name == "." || it.name == ".." }.toList()
    private fun uploadUri(uri: Uri) { val client = ftp; if (client == null || connectedTarget.isBlank()) { transfer = TransferState(message = "Not connected — select a device in Devices first"); log("ERROR", "Upload requested without an FTP client connection"); return }; val name = queryDisplayName(uri) ?: "upload-${System.currentTimeMillis()}"; lifecycleScope.launch(Dispatchers.IO) { try { val size = contentLength(uri); val existing = client.remoteSize(name); var skip = if (existing > 0 && size > existing) existing else 0L; val input = contentResolver.openInputStream(uri) ?: throw IOException("Cannot open selected file"); if (skip > 0) { var left = skip; while (left > 0) { val skipped = input.skip(left); if (skipped <= 0) break; left -= skipped }; skip -= left }; val start = System.currentTimeMillis(); transfer = TransferState(true, "UPLOAD", name, skip, size, message = if (skip > 0) "Resuming" else "Starting"); client.upload(name, input, size, skip) { done, total -> val elapsed = maxOf(1L, System.currentTimeMillis() - start); transfer = transfer.copy(done = done, total = total, speedBps = done * 1000L / elapsed, message = "Transferring") }; input.close(); verifyRemote(name, uri, size) } catch (e: Exception) { transfer = transfer.copy(active = false, message = "Upload failed: ${e.message}"); log("ERROR", "Upload failed: ${e.message}") } finally { refreshRemote() } } }
    private fun download(entry: RemoteEntry) { val client = ftp ?: return; if (entry.directory) return; lifecycleScope.launch(Dispatchers.IO) { try { val outFile = File(transferRoot, entry.name).canonicalFile; if (!outFile.path.startsWith(transferRoot.canonicalPath + File.separator)) throw IOException("Unsafe filename"); val total = client.remoteSize(entry.name).takeIf { it >= 0 } ?: entry.size; val existing = if (outFile.exists()) outFile.length() else 0L; if (total >= 0L && existing >= total) { val localHash = sha256(outFile); val remoteHash = client.remoteSha256(entry.name); val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }; if (verified == false) throw IOException("Cached file SHA-256 does not match remote file"); transfer = TransferState(false, "DOWNLOAD", entry.name, total, total, message = "Already complete", sha256Local = localHash, sha256Remote = remoteHash, verified = verified); publishToDownloads(outFile, entry.name); log("DATA", "Download cache already complete; published ${entry.name} to Downloads"); return@launch }; val resume = if (existing > 0L && total > 0L) min(existing, total) else 0L; val startTime = System.currentTimeMillis(); transfer = TransferState(true, "DOWNLOAD", entry.name, resume, total, message = if (resume > 0L) "Resuming" else "Starting"); RandomAccessFile(outFile, "rw").use { raf -> raf.setLength(resume); raf.seek(resume); val output = object : OutputStream() { override fun write(b: Int) = raf.write(b); override fun write(b: ByteArray, off: Int, len: Int) = raf.write(b, off, len) }; client.download(entry.name, output, resume) { done, receivedTotal -> val elapsed = maxOf(1L, System.currentTimeMillis() - startTime); transfer = transfer.copy(done = done, total = receivedTotal, speedBps = done * 1000L / elapsed, message = "Transferring") }; output.flush() }; val localHash = sha256(outFile); val remoteHash = client.remoteSha256(entry.name); val verified = remoteHash.takeIf { it.isNotBlank() }?.let { localHash.equals(it, true) }; transfer = transfer.copy(active = false, done = outFile.length(), total = total, speedBps = 0L, message = "Complete — saved to Downloads", sha256Local = localHash, sha256Remote = remoteHash, verified = verified); publishToDownloads(outFile, entry.name); log("DATA", "Saved ${entry.name} to public Downloads; SHA-256 $localHash") } catch (e: Exception) { transfer = transfer.copy(active = false, message = "Download failed: ${e.message}"); log("ERROR", "Download failed: ${e.message}") } } }

    private fun toggleServer() {
        if (serverRunning) { server.stop(); serverRunning = false; cancelServerNotification(); log("SERVER", "Embedded FTP server stopped") }
        else { try { server.start(); serverRunning = true; showServerNotification(); log("SERVER", "Embedded FTP server active on ${localIpv4() ?: "0.0.0.0"}:$serverPort") } catch (e: Exception) { log("ERROR", "Server start failed: ${e.message}") } }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun NetFtpApp() {
        var tab by remember { mutableIntStateOf(0) }
        val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
        val scope = rememberCoroutineScope()
        val closeDrawer: () -> Unit = { scope.launch { drawerState.close() }; Unit }
        MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFF60A5FA), secondary = Color(0xFF34D399), background = Color(0xFF080B10), surface = Color(0xFF11161E))) {
            ModalNavigationDrawer(drawerState = drawerState, drawerContent = { AdvancedNetworkDrawer(drawerState, transfer, session, logs, serverRunning, connectedTarget, closeDrawer) }) {
                Scaffold(topBar = { TopAppBar(navigationIcon = { IconButton(onClick = { scope.launch { drawerState.open() } }) { Icon(Icons.Default.Menu, "Advanced network monitor") } }, title = { Text("NetFTP Lab") }, actions = { IconButton(onClick = { scanNetwork() }) { Icon(Icons.Default.Refresh, "Scan") } }) }, bottomBar = {
                    NavigationBar {
                        val tabs = listOf("Devices" to Icons.Default.Devices, "Transfers" to Icons.Default.SwapVert, "Console" to Icons.Default.Terminal, "Network Lab" to Icons.Default.Timeline, "Server" to Icons.Default.Settings)
                        tabs.forEachIndexed { index, item -> NavigationBarItem(selected = tab == index, onClick = { tab = index }, icon = { Icon(item.second, null) }, label = { Text(item.first) }) }
                    }
                }) { padding -> Box(Modifier.padding(padding).fillMaxSize()) { when (tab) { 0 -> DevicesTab(); 1 -> TransfersTab(); 2 -> ConsoleTab(); 3 -> NetworkLabTab(); else -> ServerTab() }; if (showQr) QrDialog() } }
            }
        }
    }
