from pathlib import Path

# Targeted, idempotent corrections only. Preserve the existing NetFTPLab architecture.
main = Path("app/src/main/java/com/netftplab/MainActivity.kt")
text = main.read_text(encoding="utf-8")

# Make the single-file action impossible to miss: keep the selection controls, but
# place a full-width explicit Download button under every remote entry.
old_item = '''                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->
                    val checked = entry.path in selectedRemoteNames
                    Card(Modifier.fillMaxWidth().clickable {
                        if (checked) selectedRemoteNames.remove(entry.path) else selectedRemoteNames.add(entry.path)
                    }) {
                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = checked, onCheckedChange = { if (it) selectedRemoteNames.add(entry.path) else selectedRemoteNames.remove(entry.path) })
                            Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }
                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text("Download") }
                        }
                    }
                }'''
new_item = '''                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->
                    val checked = entry.path in selectedRemoteNames
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(10.dp)) {
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    if (checked) selectedRemoteNames.remove(entry.path) else selectedRemoteNames.add(entry.path)
                                },
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = { if (it) selectedRemoteNames.add(entry.path) else selectedRemoteNames.remove(entry.path) }
                                )
                                Icon(if (entry.directory) Icons.Default.Folder else Icons.Default.InsertDriveFile, null)
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(entry.name)
                                    Text(if (entry.directory) "Folder • recursive download" else "${entry.size} bytes")
                                }
                            }
                            Spacer(Modifier.height(6.dp))
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
                }'''
if new_item not in text:
    if old_item not in text:
        raise SystemExit("Remote transfer item marker not found; refusing to modify MainActivity")
    text = text.replace(old_item, new_item, 1)
    main.write_text(text, encoding="utf-8")
    print("Added explicit full-width single file/folder download action")
else:
    print("Single-item transfer action already corrected")

monitor = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")
text = monitor.read_text(encoding="utf-8")

# Remove accidental duplicate throughput line.
dup = '''                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")
                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")'''
one = '''                Text("App network throughput: ${formatMbps(currentMbps)} Mbps")'''
if dup in text:
    text = text.replace(dup, one, 1)

# Use the transfer's measured rate whenever it is available. For a phone-local
# SERVER -> DOWNLOADS copy, explicitly report that no network throughput exists.
old_measure = '''            val measured = if (transfer.active && transfer.speedBps > 0L) transfer.speedBps else appBps
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
new_measure = '''            val measured = when {
                transfer.active && transfer.speedBps > 0L -> transfer.speedBps
                transfer.direction == "SERVER → DOWNLOADS" -> 0L
                transfer.speedBps > 0L && transfer.message.contains("Complete", true) -> transfer.speedBps
                else -> appBps
            }
            samples.add(LiveNetSample(now, measured, wifi.rssiDbm, wifi.snrDb, appBps))'''
if new_measure not in text:
    if old_measure not in text:
        raise SystemExit("Throughput measurement marker not found; refusing to modify monitor")
    text = text.replace(old_measure, new_measure, 1)

# The previous graph could look flat because it always used a hard 0..peak scale
# with a very small floor. Use a dynamic lower/upper range and include the latest
# non-zero transfer sample when available.
old_graph = '''        val values = samples.map { it.throughputBps / 125_000.0 }
        val peak = values.maxOrNull() ?: 0.0
        val maxValue = max(0.05, peak * 1.25)
        drawSeries(values, 0.0, maxValue)'''
new_graph = '''        val values = samples.map { it.throughputBps / 125_000.0 }
        val peak = values.maxOrNull() ?: 0.0
        val recentPeak = values.takeLast(30).maxOrNull() ?: 0.0
        val scalePeak = max(peak, recentPeak)
        val maxValue = when {
            scalePeak <= 0.0 -> 0.01
            scalePeak < 0.1 -> scalePeak * 1.8
            else -> scalePeak * 1.25
        }
        drawSeries(values, 0.0, maxValue)'''
if new_graph not in text:
    if old_graph not in text:
        raise SystemExit("Throughput graph marker not found; refusing to modify monitor")
    text = text.replace(old_graph, new_graph, 1)

# Replace misleading packet labels with telemetry that Android can actually
# substantiate. Raw Wi-Fi/TCP ACK and collision counts are not exposed to a
# normal application; do not manufacture numbers from application logs.
old_packet = '''            MonitorCard("PACKET / TRANSFER TELEMETRY") {
                StatRow("ACK events", ackCount.toString()); StatRow("Retransmission indicators", retransmissionCount.toString())
                StatRow("Collision events", collisionCount.toString()); StatRow("Errors", errorCount.toString())
                StatRow("RTT (discovery)", if (session.rttMs > 0) "${session.rttMs} ms" else "Not measured")
                StatRow("Goodput", "${formatMbps(currentMbps)} Mbps")
            }'''
new_packet = '''            MonitorCard("PACKET / TRANSFER TELEMETRY") {
                StatRow("TCP ACK packets", "Not exposed")
                StatRow("Retry / resume indicators", retransmissionCount.toString())
                StatRow("Wi-Fi collision packets", "Not exposed")
                StatRow("Application / FTP errors", errorCount.toString())
                StatRow("RTT (discovery)", if (session.rttMs > 0) "${session.rttMs} ms" else "Not measured")
                StatRow("Goodput", "${formatMbps(currentMbps)} Mbps")
                Text("Android app APIs do not expose raw TCP ACK packets, Wi-Fi collision counters, or kernel retransmission packets to this application.", style = MaterialTheme.typography.bodySmall)
            }'''
if new_packet not in text:
    if old_packet not in text:
        raise SystemExit("Packet telemetry marker not found; refusing to modify monitor")
    text = text.replace(old_packet, new_packet, 1)

# Make the congestion card an explicitly measured/modelled view rather than
# presenting a static Reno/CUBIC/BBR label as kernel telemetry.
old_congestion = '''            MonitorCard("TCP CONGESTION MODEL") {
                Text("Educational model — not the Android kernel's actual cwnd", style = MaterialTheme.typography.bodySmall)
                StatRow("State", if (transfer.active) "TRANSFER ACTIVE" else "IDLE")
                StatRow("Model", "Reno / CUBIC / BBR — Network Lab")
                StatRow("Estimated loss", if (retransmissionCount > 0) "Detected" else "No indicator")
                StatRow("Backoff", if (collisionCount > 0) "Modeled from collision events" else "None observed")
            }'''
new_congestion = '''            MonitorCard("TCP CONGESTION MODEL") {
                Text("Educational model — not the Android kernel's actual cwnd", style = MaterialTheme.typography.bodySmall)
                StatRow("State", if (transfer.active) "TRANSFER ACTIVE" else "IDLE")
                StatRow("Model", "Reno / CUBIC / BBR — Network Lab")
                StatRow("Measured goodput", "${formatMbps(currentMbps)} Mbps")
                StatRow("Application loss indicator", if (retransmissionCount > 0) "Detected" else "None observed")
                StatRow("Kernel cwnd", "Not exposed")
                StatRow("Wi-Fi backoff", "Not exposed")
                Text("Use Network Lab for the Reno/CUBIC/BBR mathematical model; this panel supplies measured FTP/application inputs without claiming kernel cwnd or MAC backoff access.", style = MaterialTheme.typography.bodySmall)
            }'''
if new_congestion not in text:
    if old_congestion not in text:
        raise SystemExit("Congestion model marker not found; refusing to modify monitor")
    text = text.replace(old_congestion, new_congestion, 1)

monitor.write_text(text, encoding="utf-8")
print("Corrected throughput graph, packet telemetry semantics, and congestion model telemetry")
