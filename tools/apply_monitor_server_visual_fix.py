from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit(f"markers not found: {start_marker!r}")
    return text[:start] + replacement + text[end:]


def patch_server_tab() -> None:
    s = MAIN.read_text(encoding="utf-8")
    start_marker = "    @Composable\n    private fun ServerTab() {"
    end_marker = "\n    @Composable\n    private fun QrDialog()"
    server_tab = r'''    @Composable
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
'''
    s = replace_between(s, start_marker, end_marker, server_tab)
    MAIN.write_text(s, encoding="utf-8")


def patch_monitor() -> None:
    s = MON.read_text(encoding="utf-8")

    # Remove the accidental repeated throughput rows introduced by the prior patch.
    duplicate_block = '''                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")
                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")
                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")
                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")
                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")'''
    single_row = '''                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")'''
    s = s.replace(duplicate_block, single_row, 1)

    # Prefer the transfer's measured rate while a transfer is active; otherwise use UID TrafficStats.
    old_measure = '''            val appBps = delta * 1000L / elapsed
            val measured = if (appBps > 0L) appBps else transfer.speedBps
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
    new_measure = '''            val appBps = delta * 1000L / elapsed
            val measured = if (transfer.active && transfer.speedBps > 0L) transfer.speedBps else appBps
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
    s = s.replace(old_measure, new_measure, 1)

    # Make the throughput graph autoscale to the observed data and use the actual sample count.
    old_throughput = '''@Composable private fun ThroughputGraph(samples: List<LiveNetSample>) {
    GraphFrame("Mbps") { val maxValue = max(1.0, samples.maxOfOrNull { it.throughputBps / 125_000.0 } ?: 1.0); drawSeries(samples.map { it.throughputBps / 125_000.0 }, maxValue) }
}'''
    new_throughput = '''@Composable private fun ThroughputGraph(samples: List<LiveNetSample>) {
    GraphFrame("Mbps") {
        val values = samples.map { it.throughputBps / 125_000.0 }
        val peak = values.maxOrNull() ?: 0.0
        val maxValue = max(0.05, peak * 1.25)
        drawSeries(values, 0.0, maxValue)
    }
}'''
    s = s.replace(old_throughput, new_throughput, 1)

    old_series = '''private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawSeries(values: List<Double>, minValue: Double = 0.0, maxValue: Double = 1.0, offset: Int = 0) {
    if (values.size < 2 || maxValue <= minValue) return
    val points = values.mapIndexed { i, value -> Offset((size.width * (i + offset) / 89f), (size.height - ((value - minValue) / (maxValue - minValue)).coerceIn(0.0, 1.0) * size.height).toFloat()) }
    points.zipWithNext().forEach { (a, b) -> drawLine(Color(0xFF60A5FA), a, b, 3f) }
}'''
    new_series = '''private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawSeries(values: List<Double>, minValue: Double = 0.0, maxValue: Double = 1.0, offset: Int = 0) {
    if (values.size < 2 || maxValue <= minValue) return
    val denominator = (values.size - 1).coerceAtLeast(1).toFloat()
    val points = values.mapIndexed { i, value ->
        val x = size.width * (i + offset).toFloat() / (denominator + offset.coerceAtLeast(0))
        val normalized = ((value - minValue) / (maxValue - minValue)).coerceIn(0.0, 1.0)
        Offset(x, (size.height - normalized * size.height).toFloat())
    }
    points.zipWithNext().forEach { (a, b) -> drawLine(Color(0xFF60A5FA), a, b, 3f) }
}'''
    s = s.replace(old_series, new_series, 1)

    # Make the telemetry semantics explicit: these are app/protocol indicators, not RF packet captures.
    s = s.replace('StatRow("RTT", if (session.rttMs > 0) "${session.rttMs} ms" else "Not measured")',
                  'StatRow("RTT (discovery)", if (session.rttMs > 0) "${session.rttMs} ms" else "Not measured")', 1)
    s = s.replace('Text("Educational model — not the Android kernel\'s actual cwnd", style = MaterialTheme.typography.bodySmall)',
                  'Text("Educational model — not the Android kernel\'s actual cwnd", style = MaterialTheme.typography.bodySmall)', 1)
    s = s.replace('Text("SNR/noise are estimates because standard Android Wi-Fi APIs do not expose a calibrated RF noise-floor measurement.", style = MaterialTheme.typography.bodySmall)',
                  'Text("SNR/noise are estimates; ACK/retransmission/collision counters are application/protocol indicators, not raw Wi-Fi packet captures.", style = MaterialTheme.typography.bodySmall)', 1)

    MON.write_text(s, encoding="utf-8")


def main() -> None:
    patch_server_tab()
    patch_monitor()
    print("Restored preferred Server tab design and corrected live monitor presentation")


if __name__ == "__main__":
    main()
