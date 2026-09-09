from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
MON = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")

# Keep the existing Transfer-tab architecture and queue implementation. This
# patch only guarantees that the user-visible download actions exist, without
# depending on a particular earlier button layout.
s = MAIN.read_text(encoding="utf-8")

all_button = '''                    Button(
                        onClick = { queueDownloads(remoteFiles.filterNot { it.directory }) },
                        enabled = remoteFiles.any { !it.directory } && connectedTarget.isNotBlank() && !downloadQueueRunning && !uploadQueueRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Download All (${remoteFiles.count { !it.directory }})") }
'''

if 'Text("Download All (' not in s:
    # Stable insertion point: the remote-file LazyColumn item block. This is
    # deliberately independent of Select all/Clear button formatting.
    remote_items_marker = '''                items(remoteFiles, key = { "remote-${it.path}" }) { entry ->'''
    if remote_items_marker in s:
        s = s.replace(remote_items_marker, all_button + '''                    Spacer(Modifier.height(6.dp))\n''' + remote_items_marker, 1)
    else:
        # Compatible fallback: place it immediately after the remote selection
        # controls if the item-key form differs.
        selection_row = '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {'''
        remote_heading = s.find('Text("REMOTE FILES"')
        pos = s.find(selection_row, remote_heading)
        if remote_heading >= 0 and pos >= 0:
            end = s.find('\n                    }', pos)
            if end >= 0:
                end += len('\n                    }')
                s = s[:end] + '\n                    Spacer(Modifier.height(6.dp))\n' + all_button + s[end:]
            else:
                raise SystemExit("Unable to locate Transfer selection controls")
        else:
            raise SystemExit("Unable to locate stable Transfer-tab insertion point")

# Guarantee an explicit per-entry action. If an earlier patch already supplied
# it, only normalize the label so files and folders are unambiguous.
if 'onClick = { queueDownloads(listOf(entry)) }' in s:
    s = s.replace(
        ') { Text("Download") }',
        ') { Text(if (entry.directory) "Download Folder" else "Download File") }',
        1
    )
else:
    entry_text = '''                            Column(Modifier.weight(1f)) { Text(entry.name); Text(if (entry.directory) "Folder" else "${entry.size} bytes") }'''
    individual_button = '''                            OutlinedButton(
                                onClick = { queueDownloads(listOf(entry)) },
                                enabled = !downloadQueueRunning && !uploadQueueRunning
                            ) { Text(if (entry.directory) "Download Folder" else "Download File") }
'''
    if entry_text in s:
        s = s.replace(entry_text, entry_text + '\n' + individual_button, 1)
    else:
        raise SystemExit("Unable to locate remote entry rendering block")

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
print("Transfer download actions normalized; live FTP throughput telemetry preserved")
