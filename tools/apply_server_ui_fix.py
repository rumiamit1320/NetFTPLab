from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    start = s.find("    @Composable\n    private fun ServerTab() {")
    end = s.find("\n    @Composable\n    private fun QrDialog()", start)
    if start < 0 or end < 0:
        raise SystemExit("ServerTab markers not found")

    tab = s[start:end]

    # The whole Server tab owns the vertical scroll. This keeps the QR/end-point
    # section reachable on small screens and avoids a nested scrolling container.
    old_root = '''        Column(Modifier.fillMaxSize().padding(16.dp)) {'''
    new_root = '''        Column(
            Modifier.fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(0.dp)
        ) {'''
    if old_root in tab:
        tab = tab.replace(old_root, new_root, 1)

    old_files = '''            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.weight(1f, fill = false)
            ) {
                items(serverFiles) { file ->'''
    new_files = '''            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                serverFiles.forEach { file ->'''
    if old_files in tab:
        tab = tab.replace(old_files, new_files, 1)

    if "verticalScroll(rememberScrollState())" not in tab:
        raise SystemExit("Server tab scroll modifier was not applied")
    if "LazyColumn(\n                verticalArrangement = Arrangement.spacedBy(6.dp)" in tab:
        raise SystemExit("Nested server file LazyColumn remains")

    s = s[:start] + tab + s[end:]
    MAIN.write_text(s, encoding="utf-8")
    print("Server tab made fully vertically scrollable; FTP architecture untouched")


if __name__ == "__main__":
    main()
