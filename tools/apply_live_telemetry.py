from pathlib import Path

MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")
MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MON.read_text(encoding="utf-8")
    if "import android.net.TrafficStats" not in s:
        s = s.replace("import android.net.wifi.WifiInfo\n", "import android.net.wifi.WifiInfo\nimport android.net.TrafficStats\nimport android.os.Process\nimport android.net.ConnectivityManager\nimport android.net.NetworkCapabilities\n")

    s = s.replace(
        "private data class LiveNetSample(val timeMs: Long, val throughputBps: Long, val rssiDbm: Int, val snrDb: Int?)",
        "private data class LiveNetSample(val timeMs: Long, val throughputBps: Long, val rssiDbm: Int, val snrDb: Int?, val appBytesBps: Long = 0L)",
        1,
    )

    s = s.replace(
        "    val startMs = remember { System.currentTimeMillis() }\n\n    LaunchedEffect(Unit) {\n        while (true) {\n            wifi = readWifiSnapshot(context)\n            samples.add(LiveNetSample(System.currentTimeMillis(), transfer.speedBps, wifi.rssiDbm, wifi.snrDb))\n            while (samples.size > 90) samples.removeAt(0)\n            delay(1000)\n        }\n    }",
        "    val startMs = remember { System.currentTimeMillis() }\n\n    LaunchedEffect(Unit) {\n        var lastRx = TrafficStats.getUidRxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastTx = TrafficStats.getUidTxBytes(Process.myUid()).coerceAtLeast(0L)\n        var lastTime = System.currentTimeMillis()\n        while (true) {\n            wifi = readWifiSnapshot(context)\n            val now = System.currentTimeMillis()\n            val rx = TrafficStats.getUidRxBytes(Process.myUid()).coerceAtLeast(0L)\n            val tx = TrafficStats.getUidTxBytes(Process.myUid()).coerceAtLeast(0L)\n            val elapsed = max(1L, now - lastTime)\n            val delta = max(0L, (rx - lastRx) + (tx - lastTx))\n            val appBps = delta * 1000L / elapsed\n            val measured = if (appBps > 0L) appBps else transfer.speedBps\n            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))\n            while (samples.size > 90) samples.removeAt(0)\n            lastRx = rx; lastTx = tx; lastTime = now\n            delay(1000)\n        }\n    }",
        1,
    )

    s = s.replace(
        "    val currentMbps = transfer.speedBps / 125_000.0\n    val peakMbps = samples.maxOfOrNull { it.throughputBps }?.div(125_000.0) ?: 0.0\n    val avgMbps = if (samples.isEmpty()) 0.0 else samples.map { it.throughputBps }.average() / 125_000.0",
        "    val currentMbps = (samples.lastOrNull()?.throughputBps ?: transfer.speedBps) / 125_000.0\n    val peakMbps = samples.maxOfOrNull { it.throughputBps }?.div(125_000.0) ?: 0.0\n    val avgMbps = if (samples.isEmpty()) 0.0 else samples.map { it.throughputBps }.average() / 125_000.0",
        1,
    )

    s = s.replace(
        '                Text("Session bytes ${formatBytes(session.bytes)}")',
        '                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")\n                Text("Session bytes ${formatBytes(session.bytes)}")',
        1,
    )

    # Replace the RF/network snapshot so the drawer reports actual Android
    # network capabilities in addition to the existing Wi-Fi RF estimates.
    old = 'private fun readWifiSnapshot(context: Context): WifiSnapshot = try {'
    start = s.find(old)
    end = s.find('\nprivate fun readChannelWidth', start)
    if start >= 0 and end >= 0:
        replacement = r'''private fun readWifiSnapshot(context: Context): WifiSnapshot = try {
    val manager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    val info = manager.connectionInfo ?: return WifiSnapshot()
    val rssi = info.rssi; val freq = info.frequency
    val band = when { freq in 2400..2500 -> "2.4 GHz"; freq in 4900..5900 -> "5 GHz"; freq in 5925..7125 -> "6 GHz"; else -> "Unknown" }
    val assumedNoise = when (band) { "2.4 GHz" -> -92; "5 GHz" -> -95; "6 GHz" -> -96; else -> -95 }
    val snr = if (rssi > -127) rssi - assumedNoise else null
    val standard = if (android.os.Build.VERSION.SDK_INT >= 30) standardName(info.wifiStandard) else "Unknown"
    val width = readChannelWidth(info)
    val confidence = when { rssi <= -127 -> 0; freq <= 0 -> 25; else -> 60 }
    WifiSnapshot(
        rssi,
        freq,
        if (android.os.Build.VERSION.SDK_INT >= 31) info.rxLinkSpeedMbps else 0,
        if (android.os.Build.VERSION.SDK_INT >= 31) info.txLinkSpeedMbps else 0,
        "$standard • $band",
        width,
        snr,
        if (rssi > -127) assumedNoise else null,
        classifyNoise(rssi, snr, band),
        confidence
    )
} catch (_: Exception) { WifiSnapshot() }
'''
        s = s[:start] + replacement + s[end:]

    # Add a separate real network-state card based on ConnectivityManager.
    if 'private fun networkStateText(' not in s:
        insert_at = s.find('@Composable private fun MonitorCard')
        helper = r'''private fun networkStateText(context: Context): String {
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
    return "$transport • ${if (validated) "validated" else "local/unvalidated"} • ${if (metered) "metered" else "unmetered"} • ↓${caps.linkDownstreamBandwidthKbps} kbps ↑${caps.linkUpstreamBandwidthKbps} kbps"
}

'''
        if insert_at < 0:
            raise SystemExit('MonitorCard marker not found')
        s = s[:insert_at] + helper + s[insert_at:]

    old_state = '''            MonitorCard("NETWORK STATE") {
                StatRow("FTP server", if (serverRunning) "ONLINE :2121" else "OFFLINE")
                StatRow("FTP client", if (connectedTarget.isBlank()) "NOT CONNECTED" else connectedTarget)
                StatRow("Monitor uptime", formatDuration(uptimeSec)); StatRow("Samples", samples.size.toString())
            }'''
    new_state = '''            MonitorCard("NETWORK STATE") {
                StatRow("Network", networkStateText(context))
                StatRow("FTP server", if (serverRunning) "ONLINE :2121" else "OFFLINE")
                StatRow("FTP client", if (connectedTarget.isBlank()) "NOT CONNECTED" else connectedTarget)
                StatRow("Monitor uptime", formatDuration(uptimeSec)); StatRow("Samples", samples.size.toString())
            }'''
    s = s.replace(old_state, new_state, 1)
    MON.write_text(s, encoding="utf-8")

    m = MAIN.read_text(encoding="utf-8")
    if 'session = SessionStats(connected = true, target = connectedTarget)' in m:
        m = m.replace(
            'session = SessionStats(connected = true, target = connectedTarget)',
            'session = SessionStats(rttMs = device.latencyMs ?: 0L, connected = true, target = connectedTarget)',
            1,
        )
    if 'import android.content.ClipData' not in m:
        m = m.replace('import android.content.Intent\n', 'import android.content.Intent\nimport android.content.ClipData\n', 1)
    MAIN.write_text(m, encoding="utf-8")
    print("Live telemetry upgraded with app TrafficStats and Android network capabilities")


if __name__ == "__main__":
    main()
