from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")

# Keep an unmistakable per-item action in the remote Transfer list. If a prior
# patch already supplied it, do not touch that UI block.
s = MAIN.read_text(encoding="utf-8")
if 'Text(if (entry.directory) "Download Folder" else "Download File")' not in s:
    raise SystemExit("Remote single-download action is missing; refusing an unsafe broad rewrite")

# Also provide a local Save to Downloads action for files shown in PHONE SERVER FILES.
# This does not alter the FTP server or transfer architecture; it simply exposes
# the existing saveServerFileToPhone() operation from the Transfer tab.
old_local = '''                            Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }\n                            IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }\n                            IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }'''
new_local = '''                            Column(Modifier.weight(1f)) { Text(file.name); Text(if (file.isDirectory) "Folder" else "${file.length()} bytes") }\n                            if (file.isFile) {\n                                IconButton(onClick = { saveServerFileToPhone(file) }) { Icon(Icons.Default.Download, "Save to Downloads") }\n                            }\n                            IconButton(onClick = { shareFiles(serverSelectionFiles(listOf(file))) }) { Icon(Icons.Default.Share, "Share") }\n                            IconButton(onClick = { if (deleteLocalEntry(file)) refreshServerFiles() }) { Icon(Icons.Default.Delete, "Delete") }'''
if new_local not in s and old_local in s:
    s = s.replace(old_local, new_local, 1)
    MAIN.write_text(s, encoding="utf-8")
    print("Added Save to Downloads action to phone-server files")
else:
    print("Phone-server Transfer action already present or marker not applicable")

m = MON.read_text(encoding="utf-8")

# Collapse all consecutive duplicate throughput rows. Earlier patch layers used
# slightly different counts, so normalize rather than replacing a fixed pair.
row = '                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")\n'
m = re.sub(r'(?:' + re.escape(row) + r'){2,}', row, m)
m = m.replace(row, '                Text("Live app throughput: ${formatMbps(currentMbps)} Mbps")\n', 1)

# Add live device-wide RX/TX rates alongside the negotiated link capacity.
old_sampling = '''    var wifi by remember { mutableStateOf(WifiSnapshot()) }\n    val samples = remember { mutableStateListOf<LiveNetSample>() }\n    val startMs = remember { System.currentTimeMillis() }\n\n    LaunchedEffect(Unit) {\n        var lastRx = TrafficStats.getUidRxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastTx = TrafficStats.getUidTxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastTime = System.currentTimeMillis()'''
new_sampling = '''    var wifi by remember { mutableStateOf(WifiSnapshot()) }\n    val samples = remember { mutableStateListOf<LiveNetSample>() }\n    var liveDeviceRxBps by remember { mutableLongStateOf(0L) }\n    var liveDeviceTxBps by remember { mutableLongStateOf(0L) }\n    val startMs = remember { System.currentTimeMillis() }\n\n    LaunchedEffect(Unit) {\n        var lastRx = TrafficStats.getUidRxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastTx = TrafficStats.getUidTxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastDeviceRx = TrafficStats.getTotalRxBytes().coerceAtLeast(0L)\n        var lastDeviceTx = TrafficStats.getTotalTxBytes().coerceAtLeast(0L)\n        var lastTime = System.currentTimeMillis()'''
if new_sampling not in m:
    if old_sampling not in m:
        raise SystemExit("Monitor sampling marker not found")
    m = m.replace(old_sampling, new_sampling, 1)

old_measure = '''            val elapsed = max(1L, now - lastTime)\n            val delta = max(0L, (rx - lastRx) + (tx - lastTx))\n            val appBps = delta * 1000L / elapsed\n            val measured = when {\n                transfer.active && transfer.speedBps > 0L -> transfer.speedBps\n                transfer.direction == "SERVER → DOWNLOADS" -> 0L\n                transfer.speedBps > 0L && transfer.message.contains("Complete", true) -> transfer.speedBps\n                else -> appBps\n            }\n            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))\n            while (samples.size > 90) samples.removeAt(0)\n            lastRx = rx; lastTx = tx; lastTime = now\n            delay(1000)'''
new_measure = '''            val deviceRx = TrafficStats.getTotalRxBytes().coerceAtLeast(0L)\n            val deviceTx = TrafficStats.getTotalTxBytes().coerceAtLeast(0L)\n            val elapsed = max(1L, now - lastTime)\n            val delta = max(0L, (rx - lastRx) + (tx - lastTx))\n            val appBps = delta * 1000L / elapsed\n            liveDeviceRxBps = max(0L, deviceRx - lastDeviceRx) * 1000L / elapsed\n            liveDeviceTxBps = max(0L, deviceTx - lastDeviceTx) * 1000L / elapsed\n            val transferBps = max(transfer.speedBps, session.throughputBps)\n            val measured = when {\n                transfer.direction == "SERVER → DOWNLOADS" -> 0L\n                transfer.active && transferBps > 0L -> transferBps\n                transfer.message.contains("Complete", true) && transferBps > 0L -> transferBps\n                else -> appBps\n            }\n            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))\n            while (samples.size > 90) samples.removeAt(0)\n            lastRx = rx; lastTx = tx; lastDeviceRx = deviceRx; lastDeviceTx = deviceTx; lastTime = now\n            delay(1000)'''
if new_measure not in m:
    if old_measure not in m:
        raise SystemExit("Monitor measurement marker not found")
    m = m.replace(old_measure, new_measure, 1)

m = m.replace('StatRow("Network", networkStateText(context))',
              'StatRow("Network", networkStateText(context, liveDeviceRxBps, liveDeviceTxBps))', 1)

old_fn = '''private fun networkStateText(context: Context): String {\n    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager\n    val network = cm.activeNetwork ?: return "No active network"\n    val caps = cm.getNetworkCapabilities(network) ?: return "Network capabilities unavailable"\n    val transport = when {\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Cellular"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "VPN"\n        else -> "Other"\n    }\n    val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)\n    val metered = !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)\n    return "$transport • ${if (validated) "validated" else "local/unvalidated"} • ${if (metered) "metered" else "unmetered"} • ↓${caps.linkDownstreamBandwidthKbps} kbps ↑${caps.linkUpstreamBandwidthKbps} kbps"\n}'''
new_fn = '''private fun networkStateText(context: Context, liveRxBps: Long, liveTxBps: Long): String {\n    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager\n    val network = cm.activeNetwork ?: return "No active network"\n    val caps = cm.getNetworkCapabilities(network) ?: return "Network capabilities unavailable"\n    val transport = when {\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Cellular"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"\n        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "VPN"\n        else -> "Other"\n    }\n    val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)\n    val metered = !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)\n    val live = "live ↓${formatRate(liveRxBps)} ↑${formatRate(liveTxBps)}"\n    val capacity = "link capacity ↓${caps.linkDownstreamBandwidthKbps} kbps ↑${caps.linkUpstreamBandwidthKbps} kbps"\n    return "$transport • ${if (validated) "validated" else "local/unvalidated"} • ${if (metered) "metered" else "unmetered"} • $live • $capacity"\n}\n\nprivate fun formatRate(bytesPerSecond: Long): String = when {\n    bytesPerSecond >= 1_000_000L -> "%.2f MB/s".format(bytesPerSecond / 1_000_000.0)\n    bytesPerSecond >= 1_000L -> "%.1f kB/s".format(bytesPerSecond / 1_000.0)\n    else -> "${bytesPerSecond} B/s"\n}'''
if new_fn not in m:
    if old_fn not in m:
        raise SystemExit("networkStateText marker not found")
    m = m.replace(old_fn, new_fn, 1)

MON.write_text(m, encoding="utf-8")
print("Corrected live network state, transfer rate selection, and duplicate throughput rows")
