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

    # Remove duplicate App network throughput rows without assuming how many
    # accidental copies a previous UI patch inserted. Keep the first one only.
    lines = s.splitlines(keepends=True)
    seen_app_rate = False
    cleaned = []
    for line in lines:
        if 'Text("App network throughput: ${formatMbps(currentMbps)} Mbps")' in line:
            if seen_app_rate:
                continue
            seen_app_rate = True
        cleaned.append(line)
    s = ''.join(cleaned)

    # The live rate must represent the current transfer, not a completed
    # transfer's retained speed. After completion, fall back to the current
    # TrafficStats delta; when idle that naturally becomes zero.
    old_measure = '''            val appBps = delta * 1000L / elapsed
            val transferBps = max(liveTransfer.speedBps, liveSession.throughputBps)
            val measured = when {
                liveTransfer.direction == "SERVER → DOWNLOADS" -> 0L
                liveTransfer.active && transferBps > 0L -> transferBps
                liveTransfer.message.contains("Complete", true) && transferBps > 0L -> transferBps
                else -> appBps
            }'''
    new_measure = '''            val appBps = delta * 1000L / elapsed
            val transferBps = max(liveTransfer.speedBps, liveSession.throughputBps)
            val measured = when {
                liveTransfer.direction == "SERVER → DOWNLOADS" -> 0L
                liveTransfer.active && transferBps > 0L -> transferBps
                else -> appBps
            }'''
    s = s.replace(old_measure, new_measure, 1)

    # Display zero immediately when the transfer is no longer active instead
    # of holding the last transfer rate in the headline metric.
    old_current = '''    val currentMbps = (samples.lastOrNull()?.throughputBps ?: transfer.speedBps) / 125_000.0
    val peakMbps = samples.maxOfOrNull { it.throughputBps }?.div(125_000.0) ?: 0.0
    val avgMbps = if (samples.isEmpty()) 0.0 else samples.map { it.throughputBps }.average() / 125_000.0'''
    new_current = '''    val currentBps = if (transfer.active) {
        max(transfer.speedBps, samples.lastOrNull()?.throughputBps ?: 0L)
    } else {
        samples.lastOrNull()?.appBytesBps ?: 0L
    }
    val currentMbps = currentBps / 125_000.0
    val appNetworkMbps = (samples.lastOrNull()?.appBytesBps ?: 0L) / 125_000.0
    val peakMbps = samples.maxOfOrNull { it.throughputBps }?.div(125_000.0) ?: 0.0
    val avgMbps = if (samples.isEmpty()) 0.0 else samples.map { it.throughputBps }.average() / 125_000.0'''
    s = s.replace(old_current, new_current, 1)

    # Show the actual current transfer state in the headline instead of leaving
    # a completed DOWNLOAD labelled as current.
    s = s.replace(
        'Text("Current ${transfer.direction.ifBlank { "idle" }} • ${transfer.name.ifBlank { "no active transfer" }}")',
        'Text("Current ${if (transfer.active) transfer.direction else "IDLE"} • ${if (transfer.active) transfer.name else "no active transfer"}")',
        1,
    )

    # The app-network value is the most recent TrafficStats delta, not the
    # transfer headline value. This prevents the two metrics from being
    # incorrectly identical after a transfer has completed.
    s = s.replace(
        'Text("App network throughput: ${formatMbps(currentMbps)} Mbps")',
        'Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")',
        1,
    )

    # Keep the graph historical, but use an autoscale based on observed values.
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

    # Use actual sample count for graph X coordinates rather than a fixed 90-sample width.
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

    # Preserve the existing server presentation while making only the monitor
    # metric semantics above more accurate.
    MON.write_text(s, encoding="utf-8")


def main() -> None:
    patch_server_tab()
    patch_monitor()
    print("Preserved Server tab and fixed live throughput metric presentation")


if __name__ == "__main__":
    main()
