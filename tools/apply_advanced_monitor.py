from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")
ADV = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")
    start = s.find("    @OptIn(ExperimentalMaterial3Api::class)\n    @Composable\n    fun NetFtpApp() {")
    end = s.find("\n    @Composable\n    private fun DevicesTab()", start)
    if start < 0 or end < 0:
        raise SystemExit("NetFtpApp markers not found")

    replacement = '''    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun NetFtpApp() {
        var tab by remember { mutableIntStateOf(0) }
        val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
        val scope = rememberCoroutineScope()
        val closeDrawer: () -> Unit = { scope.launch { drawerState.close() }; Unit }
        MaterialTheme(
            colorScheme = darkColorScheme(
                primary = Color(0xFF60A5FA),
                secondary = Color(0xFF34D399),
                background = Color(0xFF080B10),
                surface = Color(0xFF11161E)
            )
        ) {
            ModalNavigationDrawer(
                drawerState = drawerState,
                drawerContent = {
                    AdvancedNetworkDrawer(
                        drawerState = drawerState,
                        transfer = transfer,
                        session = session,
                        logs = logs,
                        serverRunning = serverRunning,
                        connectedTarget = connectedTarget,
                        onClose = closeDrawer
                    )
                }
            ) {
                Scaffold(
                    topBar = {
                        TopAppBar(
                            navigationIcon = {
                                IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                    Icon(Icons.Default.Menu, "Advanced network monitor")
                                }
                            },
                            title = { Text("NetFTP Lab") },
                            actions = {
                                IconButton(onClick = { scanNetwork() }) {
                                    Icon(Icons.Default.Refresh, "Scan")
                                }
                            }
                        )
                    },
                    bottomBar = {
                        NavigationBar {
                            val tabs = listOf(
                                "Devices" to Icons.Default.Devices,
                                "Transfers" to Icons.Default.SwapVert,
                                "Console" to Icons.Default.Terminal,
                                "Network Lab" to Icons.Default.Timeline,
                                "Server" to Icons.Default.Settings
                            )
                            tabs.forEachIndexed { index, item ->
                                NavigationBarItem(
                                    selected = tab == index,
                                    onClick = { tab = index },
                                    icon = { Icon(item.second, null) },
                                    label = { Text(item.first) }
                                )
                            }
                        }
                    }
                ) { padding ->
                    Box(Modifier.padding(padding).fillMaxSize()) {
                        when (tab) {
                            0 -> DevicesTab()
                            1 -> TransfersTab()
                            2 -> ConsoleTab()
                            3 -> NetworkLabTab()
                            else -> ServerTab()
                        }
                        if (showQr) QrDialog()
                    }
                }
            }
        }
    }
'''
    s = s[:start] + replacement + s[end:]
    MAIN.write_text(s, encoding="utf-8")

    # WifiInfo.channelWidth is not available in all compile SDK/API combinations.
    # Read it reflectively so the monitor remains build-compatible without changing
    # the FTP/server architecture or the rest of the telemetry logic.
    if ADV.exists():
        a = ADV.read_text(encoding="utf-8")
        old = '''@Suppress("DEPRECATION") private fun readChannelWidth(info: WifiInfo): String = try {
    when (info.channelWidth) { 0 -> "20 MHz"; 1 -> "40 MHz"; 2 -> "80 MHz"; 3 -> "160 MHz"; 4 -> "80+80 MHz"; else -> "Unknown" }
} catch (_: Throwable) { "Unknown" }'''
        new = '''private fun readChannelWidth(info: WifiInfo): String = try {
    val field = WifiInfo::class.java.getDeclaredField("channelWidth")
    field.isAccessible = true
    val width = field.getInt(info)
    when (width) { 0 -> "20 MHz"; 1 -> "40 MHz"; 2 -> "80 MHz"; 3 -> "160 MHz"; 4 -> "80+80 MHz"; else -> "Unknown" }
} catch (_: Throwable) { "Unknown" }'''
        if old in a:
            a = a.replace(old, new)
        elif 'info.channelWidth' in a:
            raise SystemExit("Unexpected channelWidth source; refusing unsafe replacement")
        ADV.write_text(a, encoding="utf-8")

    print("Added left-side Advanced Network Monitor drawer; fixed channel-width API compatibility; FTP architecture untouched")


if __name__ == "__main__":
    main()
