from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")

# Add an explicit Download All action to the existing multi-file transfer UI.
s = MAIN.read_text(encoding="utf-8")
all_button = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
'''
if 'Text("Download All (' not in s:
    # Current TransfersTab uses a remoteSelection list rather than the older
    # selectedCount anchor. Insert immediately after the Select all / Clear
    # controls, before the selected-item actions.
    selection_controls = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedButton(onClick = { selectedRemoteNames.clear(); selectedRemoteNames.addAll(remoteFiles.map { it.path }) }, enabled = remoteFiles.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Select all") }
                        OutlinedButton(onClick = { selectedRemoteNames.clear() }, enabled = selectedRemoteNames.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Clear") }
                    }
'''
    if selection_controls in s:
        s = s.replace(selection_controls, selection_controls + '                    Spacer(Modifier.height(6.dp))\n' + all_button, 1)
    else:
        # Fallback for a compatible older Transfer-tab layout.
        anchor = '''                    Button(
                        onClick = {
                            val chosen = remoteFiles.filter { !it.directory && it.name in selectedRemoteNames }
                            queueDownloads(chosen)
                        },
                        enabled = connectedTarget.isNotBlank() && selectedCount > 0 && !downloadQueueRunning,
                        modifier = Modifier.weight(1f)
                    ) { Text("Download ($selectedCount)") }
'''
        if anchor in s:
            s = s.replace(anchor, anchor + all_button, 1)
        else:
            raise SystemExit("Unable to locate a safe Transfer-tab insertion point")
MAIN.write_text(s, encoding="utf-8")

# Make the long-running sampler observe current Compose state rather than the
# initial idle TransferState captured when the drawer first opened.
m = MON.read_text(encoding="utf-8")
if 'val latestTransfer = rememberUpdatedState(transfer)' not in m:
    state_anchor = '''    var liveDeviceRxBps by remember { mutableLongStateOf(0L) }
    var liveDeviceTxBps by remember { mutableLongStateOf(0L) }
    val startMs = remember { System.currentTimeMillis() }
'''
    state_new = '''    var liveDeviceRxBps by remember { mutableLongStateOf(0L) }
    var liveDeviceTxBps by remember { mutableLongStateOf(0L) }
    val latestTransfer = rememberUpdatedState(transfer)
    val latestSession = rememberUpdatedState(session)
    val startMs = remember { System.currentTimeMillis() }
'''
    if state_anchor not in m:
        raise SystemExit("Monitor state anchor not found")
    m = m.replace(state_anchor, state_new, 1)

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
        raise SystemExit("Monitor transfer sampling marker not found")
    m = m.replace(old_loop, new_loop, 1)

old_call = 'StatRow("Network", networkStateText(context, liveDeviceRxBps, liveDeviceTxBps))'
new_call = 'StatRow("Network", networkStateText(context, liveDeviceRxBps, liveDeviceTxBps, transfer.direction, transfer.active, transfer.speedBps))'
if new_call not in m and old_call in m:
    m = m.replace(old_call, new_call, 1)

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
    if old_fn in m:
        m = m.replace(old_fn, new_fn, 1)
    else:
        raise SystemExit("Network state function marker not found")
MON.write_text(m, encoding="utf-8")
print("Added Download All and corrected live FTP throughput telemetry")
