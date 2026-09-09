from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")

s = MAIN.read_text(encoding="utf-8")
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in s:
    raise SystemExit("Remote single-download action is missing; refusing an unsafe broad rewrite")

# Explicit all-items action; selected-item Download(N) remains unchanged.
download_all_button = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.toList()) },
                        enabled = remoteFiles.isNotEmpty() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.size})") }
                    Spacer(Modifier.height(6.dp))
'''
anchor = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { queueDownloads(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning, modifier = Modifier.weight(1f)) { Text("Download (${remoteSelection.size})") }
                        OutlinedButton(onClick = { shareRemoteEntries(remoteSelection) }, enabled = remoteSelection.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Share") }
                        OutlinedButton(onClick = { queueDeleteRemote(remoteSelection) }, enabled = remoteSelection.isNotEmpty() && !downloadQueueRunning && !uploadQueueRunning, modifier = Modifier.weight(1f)) { Text("Delete") }
                    }
'''
if download_all_button not in s:
    if anchor not in s:
        raise SystemExit("Remote transfer action row not found")
    s = s.replace(anchor, anchor + download_all_button, 1)

# Preserve the existing phone-server save action.
old_local = '''                            Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }
                            IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }
                            IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }'''
new_local = '''                            Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }
                            if (file.isFile) {
                                IconButton(onClick = { saveServerFileToPhone(file) }) { Icon(Icons.Default.Download, "Save to Downloads") }
                            }
                            IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }
                            IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }'''
if new_local not in s and old_local in s:
    s = s.replace(old_local, new_local, 1)
MAIN.write_text(s, encoding="utf-8")

m = MON.read_text(encoding="utf-8")

# Collapse any duplicate throughput label rows.
row = '                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")\n'
m = re.sub(r'(?:' + re.escape(row) + r'){1,}', '                Text("Live app throughput: ${formatMbps(currentMbps)} Mbps")\n', m)

# LaunchedEffect(Unit) otherwise captures the initial idle TransferState and
# SessionStats. Keep one sampler, but make it observe current Compose state.
old_state = '''    var wifi by remember { mutableStateOf(WifiSnapshot()) }
    val samples = remember { mutableStateListOf<LiveNetSample>() }
    var liveDeviceRxBps by remember { mutableLongStateOf(0L) }
    var liveDeviceTxBps by remember { mutableLongStateOf(0L) }
    val startMs = remember { System.currentTimeMillis() }

    LaunchedEffect(Unit) {'''
new_state = '''    var wifi by remember { mutableStateOf(WifiSnapshot()) }
    val samples = remember { mutableStateListOf<LiveNetSample>() }
    var liveDeviceRxBps by remember { mutableLongStateOf(0L) }
    var liveDeviceTxBps by remember { mutableLongStateOf(0L) }
    val latestTransfer = rememberUpdatedState(transfer)
    val latestSession = rememberUpdatedState(session)
    val startMs = remember { System.currentTimeMillis() }

    LaunchedEffect(Unit) {'''
if new_state not in m:
    if old_state not in m:
        raise SystemExit("Monitor state marker not found")
    m = m.replace(old_state, new_state, 1)

old_loop = '''            val transferBps = max(transfer.speedBps, session.throughputBps)
            val measured = when {
                transfer.direction == "SERVER → DOWNLOADS" -> 0L
                transfer.active && transferBps > 0L -> transferBps
                transfer.message.contains("Complete", true) && transferBps > 0L -> transferBps
                else -> appBps
            }
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
new_loop = '''            val liveTransfer = latestTransfer.value
            val liveSession = latestSession.value
            val transferBps = max(liveTransfer.speedBps, liveSession.throughputBps)
            val measured = when {
                liveTransfer.direction == "SERVER → DOWNLOADS" -> 0L
                liveTransfer.active && transferBps > 0L -> transferBps
                liveTransfer.message.contains("Complete", true) && transferBps > 0L -> transferBps
                else -> appBps
            }
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
if new_loop not in m:
    if old_loop not in m:
        raise SystemExit("Monitor sampling loop marker not found")
    m = m.replace(old_loop, new_loop, 1)

m = m.replace(
    'StatRow("Network", networkStateText(context, liveDeviceRxBps, liveDeviceTxBps))',
    'StatRow("Network", networkStateText(context, liveDeviceRxBps, liveDeviceTxBps, transfer.direction, transfer.active, transfer.speedBps))',
    1
)

old_fn = '''private fun networkStateText(context: Context, liveRxBps: Long, liveTxBps: Long): String {
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val network = cm.activeNetwork ?: return "No active network"
    val caps = cm.getNetworkCapabilities(network) ?: return "Network capabilities unavailable"
    val transport = when {
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Cellular"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "VPN"
        else -> "Other"
    }
    val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    val metered = !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    val live = "live ↓${formatRate(liveRxBps)} ↑${formatRate(liveTxBps)}"
    val capacity = "link capacity ↓${caps.linkDownstreamBandwidthKbps} kbps ↑${caps.linkUpstreamBandwidthKbps} kbps"
    return "$transport • ${if (validated) "validated" else "local/unvalidated"} • ${if (metered) "metered" else "unmetered"} • $live • $capacity"
}'''
new_fn = '''private fun networkStateText(
    context: Context,
    liveRxBps: Long,
    liveTxBps: Long,
    transferDirection: String,
    transferActive: Boolean,
    transferBps: Long
): String {
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val network = cm.activeNetwork ?: return "No active network"
    val caps = cm.getNetworkCapabilities(network) ?: return "Network capabilities unavailable"
    val transport = when {
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Cellular"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "VPN"
        else -> "Other"
    }
    val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    val metered = !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    val ftpRx = if (transferActive && transferDirection == "DOWNLOAD") transferBps else 0L
    val ftpTx = if (transferActive && transferDirection == "UPLOAD") transferBps else 0L
    val liveRx = max(liveRxBps, ftpRx)
    val liveTx = max(liveTxBps, ftpTx)
    val live = "live ↓${formatRate(liveRx)} ↑${formatRate(liveTx)}"
    val capacity = "link capacity ↓${caps.linkDownstreamBandwidthKbps} kbps ↑${caps.linkUpstreamBandwidthKbps} kbps"
    return "$transport • ${if (validated) "validated" else "local/unvalidated"} • ${if (metered) "metered" else "unmetered"} • $live • $capacity"
}'''
if new_fn not in m:
    if old_fn not in m:
        raise SystemExit("networkStateText marker not found")
    m = m.replace(old_fn, new_fn, 1)

MON.write_text(m, encoding="utf-8")
print("Added Download All and fixed live transfer telemetry state capture")
