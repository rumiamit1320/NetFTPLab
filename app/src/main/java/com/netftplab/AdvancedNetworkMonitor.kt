package com.netftplab

import android.content.Context
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlin.math.max
import kotlin.math.min

private data class LiveNetSample(val timeMs: Long, val throughputBps: Long, val rssiDbm: Int, val snrDb: Int?)
private data class WifiSnapshot(
    val rssiDbm: Int = -127, val frequencyMHz: Int = 0, val rxMbps: Int = 0, val txMbps: Int = 0,
    val linkStandard: String = "Unknown", val channelWidth: String = "Unknown", val snrDb: Int? = null,
    val noiseFloorDbm: Int? = null, val noiseType: String = "Unavailable", val confidence: Int = 0
)

@Composable
fun AdvancedNetworkDrawer(
    drawerState: DrawerState, transfer: TransferState, session: SessionStats, logs: List<LogLine>,
    serverRunning: Boolean, connectedTarget: String, onClose: () -> Unit
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var wifi by remember { mutableStateOf(WifiSnapshot()) }
    val samples = remember { mutableStateListOf<LiveNetSample>() }
    val startMs = remember { System.currentTimeMillis() }

    LaunchedEffect(Unit) {
        while (true) {
            wifi = readWifiSnapshot(context)
            samples.add(LiveNetSample(System.currentTimeMillis(), transfer.speedBps, wifi.rssiDbm, wifi.snrDb))
            while (samples.size > 90) samples.removeAt(0)
            delay(1000)
        }
    }

    val collisionCount = logs.count { it.layer.equals("COLLISION", true) || it.text.contains("collision", true) }
    val retransmissionCount = logs.count { it.layer.equals("RETX", true) || it.text.contains("retransmit", true) || it.text.contains("retransmission", true) }
    val ackCount = logs.count { it.layer.equals("ACK", true) || it.text.contains(" ACK", true) }
    val errorCount = logs.count { it.layer.equals("ERROR", true) }
    val currentMbps = transfer.speedBps / 125_000.0
    val peakMbps = samples.maxOfOrNull { it.throughputBps }?.div(125_000.0) ?: 0.0
    val avgMbps = if (samples.isEmpty()) 0.0 else samples.map { it.throughputBps }.average() / 125_000.0
    val uptimeSec = max(0L, (System.currentTimeMillis() - startMs) / 1000L)

    ModalDrawerSheet(modifier = Modifier.fillMaxWidth(0.94f), drawerContainerColor = Color(0xFF0B1017)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.weight(1f)) {
                    Text("Advanced Network Monitor", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text("Live measurements, estimates and protocol models", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = onClose) { Text("Close") }
            }
            MonitorCard("REAL-TIME THROUGHPUT") {
                Text("${formatMbps(currentMbps)} Mbps", style = MaterialTheme.typography.headlineMedium)
                Text("Current ${transfer.direction.ifBlank { "idle" }} • ${transfer.name.ifBlank { "no active transfer" }}")
                Text("Average ${formatMbps(avgMbps)} Mbps  •  Peak ${formatMbps(peakMbps)} Mbps")
                Text("Session bytes ${formatBytes(session.bytes)}")
                Spacer(Modifier.height(8.dp)); ThroughputGraph(samples)
            }
            MonitorCard("PACKET / TRANSFER TELEMETRY") {
                StatRow("ACK events", ackCount.toString()); StatRow("Retransmission indicators", retransmissionCount.toString())
                StatRow("Collision events", collisionCount.toString()); StatRow("Errors", errorCount.toString())
                StatRow("RTT", if (session.rttMs > 0) "${session.rttMs} ms" else "Not measured")
                StatRow("Goodput", "${formatMbps(currentMbps)} Mbps")
            }
            MonitorCard("TCP CONGESTION MODEL") {
                Text("Educational model — not the Android kernel's actual cwnd", style = MaterialTheme.typography.bodySmall)
                StatRow("State", if (transfer.active) "TRANSFER ACTIVE" else "IDLE")
                StatRow("Model", "Reno / CUBIC / BBR — Network Lab")
                StatRow("Estimated loss", if (retransmissionCount > 0) "Detected" else "No indicator")
                StatRow("Backoff", if (collisionCount > 0) "Modeled from collision events" else "None observed")
            }
            MonitorCard("LIVE RF / WI-FI DIAGNOSTICS") {
                StatRow("RSSI", if (wifi.rssiDbm > -127) "${wifi.rssiDbm} dBm" else "Unavailable")
                StatRow("SNR", wifi.snrDb?.let { "~$it dB (estimated)" } ?: "Unavailable")
                StatRow("Noise floor", wifi.noiseFloorDbm?.let { "~$it dBm (estimated)" } ?: "Unavailable")
                StatRow("Noise type", wifi.noiseType); StatRow("Confidence", if (wifi.confidence > 0) "${wifi.confidence}%" else "N/A")
                StatRow("Frequency", if (wifi.frequencyMHz > 0) "${wifi.frequencyMHz} MHz" else "Unavailable")
                StatRow("Channel", frequencyToChannel(wifi.frequencyMHz).ifBlank { "Unavailable" }); StatRow("Channel width", wifi.channelWidth)
                StatRow("PHY", wifi.linkStandard); StatRow("RX link rate", "${wifi.rxMbps} Mbps"); StatRow("TX link rate", "${wifi.txMbps} Mbps")
                Text("SNR/noise are estimates because standard Android Wi-Fi APIs do not expose a calibrated RF noise-floor measurement.", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp)); RfGraph(samples)
            }
            MonitorCard("NETWORK STATE") {
                StatRow("FTP server", if (serverRunning) "ONLINE :2121" else "OFFLINE")
                StatRow("FTP client", if (connectedTarget.isBlank()) "NOT CONNECTED" else connectedTarget)
                StatRow("Monitor uptime", formatDuration(uptimeSec)); StatRow("Samples", samples.size.toString())
            }
            MonitorCard("EVENT STREAM") {
                if (logs.isEmpty()) Text("No events yet.") else logs.takeLast(12).asReversed().forEach { line ->
                    Text("${line.time}  ${line.layer.padEnd(10)} ${line.text}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable private fun MonitorCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) { Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold); content() } }
}
@Composable private fun StatRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label); Text(value, fontWeight = FontWeight.SemiBold) }
}
@Composable private fun ThroughputGraph(samples: List<LiveNetSample>) {
    GraphFrame("Mbps") { val maxValue = max(1.0, samples.maxOfOrNull { it.throughputBps / 125_000.0 } ?: 1.0); drawSeries(samples.map { it.throughputBps / 125_000.0 }, maxValue) }
}
@Composable private fun RfGraph(samples: List<LiveNetSample>) {
    GraphFrame("dBm / dB") {
        val snrValues = samples.mapNotNull { it.snrDb?.toDouble() }; val all = samples.map { it.rssiDbm.toDouble() } + snrValues
        val minValue = min(-20.0, (all.minOrNull() ?: -100.0) - 5.0); val maxValue = max(-10.0, (all.maxOrNull() ?: -40.0) + 5.0)
        drawSeries(samples.map { it.rssiDbm.toDouble() }, minValue, maxValue)
        if (snrValues.isNotEmpty()) drawSeries(snrValues, minValue, maxValue, samples.size - snrValues.size)
    }
}
@Composable private fun GraphFrame(label: String, drawContent: androidx.compose.ui.graphics.drawscope.DrawScope.() -> Unit) {
    Box(Modifier.fillMaxWidth().height(170.dp).background(Color(0xFF070B10))) {
        Canvas(Modifier.fillMaxSize().padding(8.dp)) { val w = size.width; val h = size.height; for (i in 1..3) drawLine(Color(0x334B5563), Offset(0f, h * i / 4f), Offset(w, h * i / 4f), 1f); drawContent() }
        Text(label, Modifier.align(Alignment.TopStart).padding(10.dp), style = MaterialTheme.typography.labelSmall)
    }
}
private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawSeries(values: List<Double>, minValue: Double = 0.0, maxValue: Double = 1.0, offset: Int = 0) {
    if (values.size < 2 || maxValue <= minValue) return
    val points = values.mapIndexed { i, value -> Offset((size.width * (i + offset) / 89f), (size.height - ((value - minValue) / (maxValue - minValue)).coerceIn(0.0, 1.0) * size.height).toFloat()) }
    points.zipWithNext().forEach { (a, b) -> drawLine(Color(0xFF60A5FA), a, b, 3f) }
}

private fun readWifiSnapshot(context: Context): WifiSnapshot = try {
    val manager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    val info = manager.connectionInfo ?: return WifiSnapshot()
    val rssi = info.rssi; val freq = info.frequency
    val band = when { freq in 2400..2500 -> "2.4 GHz"; freq in 4900..5900 -> "5 GHz"; freq in 5925..7125 -> "6 GHz"; else -> "Unknown" }
    val assumedNoise = when (band) { "2.4 GHz" -> -92; "5 GHz" -> -95; "6 GHz" -> -96; else -> -95 }
    val snr = if (rssi > -127) rssi - assumedNoise else null
    val standard = if (android.os.Build.VERSION.SDK_INT >= 30) standardName(info.wifiStandard) else "Unknown"
    val width = readChannelWidth(info)
    val confidence = when { rssi <= -127 -> 0; freq <= 0 -> 25; else -> 60 }
    WifiSnapshot(rssi, freq, if (android.os.Build.VERSION.SDK_INT >= 31) info.rxLinkSpeedMbps else 0, if (android.os.Build.VERSION.SDK_INT >= 31) info.txLinkSpeedMbps else 0, "$standard • $band", width, snr, if (rssi > -127) assumedNoise else null, classifyNoise(rssi, snr, band), confidence)
} catch (_: Exception) { WifiSnapshot() }

@Suppress("DEPRECATION") private fun readChannelWidth(info: WifiInfo): String = try {
    when (info.channelWidth) { 0 -> "20 MHz"; 1 -> "40 MHz"; 2 -> "80 MHz"; 3 -> "160 MHz"; 4 -> "80+80 MHz"; else -> "Unknown" }
} catch (_: Throwable) { "Unknown" }
private fun classifyNoise(rssi: Int, snr: Int?, band: String): String = if (rssi <= -127 || snr == null) "Unavailable" else when {
    snr >= 35 -> "Low / background noise"; snr >= 22 -> "Moderate interference likely"; band == "2.4 GHz" && snr < 15 -> "High interference; co/adjacent-channel possible"; snr < 15 -> "High interference / weak signal"; else -> "Moderate noise"
}
private fun standardName(standard: Int): String = when (standard) {
    1 -> "Legacy"; 2 -> "802.11n"; 3 -> "802.11ac"; 4 -> "802.11ax"; 5 -> "802.11ad"; 6 -> "802.11be"; else -> "Unknown"
}
private fun frequencyToChannel(freq: Int): String = when {
    freq in 2412..2472 -> ((freq - 2407) / 5).toString(); freq == 2484 -> "14"; freq in 5000..5900 -> ((freq - 5000) / 5).toString(); freq in 5925..7125 -> ((freq - 5950) / 5).toString(); else -> ""
}
private fun formatMbps(value: Double): String = "%.2f".format(java.util.Locale.US, value)
private fun formatBytes(value: Long): String = when { value < 1024 -> "$value B"; value < 1024 * 1024 -> "%.1f KB".format(java.util.Locale.US, value / 1024.0); value < 1024L * 1024L * 1024L -> "%.1f MB".format(java.util.Locale.US, value / (1024.0 * 1024.0)); else -> "%.2f GB".format(java.util.Locale.US, value / (1024.0 * 1024.0 * 1024.0)) }
private fun formatDuration(seconds: Long): String = "%02d:%02d:%02d".format(seconds / 3600, (seconds % 3600) / 60, seconds % 60)
