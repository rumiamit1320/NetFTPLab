from pathlib import Path

ADV = Path("app/src/main/java/com/netftplab/AdvancedNetworkMonitor.kt")


def main() -> None:
    text = ADV.read_text(encoding="utf-8")

    old = '''            val measured = when {
                liveTransfer.direction == "SERVER → DOWNLOADS" -> 0L
                liveTransfer.active && transferBps > 0L -> transferBps
                liveTransfer.message.contains("Complete", true) && transferBps > 0L -> transferBps
                else -> appBps
            }'''
    new = '''            val measured = when {
                liveTransfer.active && transferBps > 0L -> transferBps
                else -> appBps
            }'''

    if old in text:
        text = text.replace(old, new, 1)
    elif 'liveTransfer.direction == "SERVER → DOWNLOADS" -> 0L' in text or 'liveTransfer.message.contains("Complete", true)' in text:
        raise SystemExit("Throughput logic has an unexpected variant; refusing unsafe rewrite")

    # CI runs several older telemetry patches before this final step. Some of
    # those patches can insert the same UI label again. Normalize the source
    # here so the final committed APK source always contains exactly one row.
    label = '                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")'
    lines = text.splitlines(keepends=True)
    cleaned = []
    seen = False
    for line in lines:
        if line.strip() == label.strip():
            if seen:
                continue
            seen = True
        cleaned.append(line)
    text = ''.join(cleaned)

    if not seen:
        raise SystemExit("App network throughput display row is missing; refusing unsafe insertion")

    ADV.write_text(text, encoding="utf-8")
    print("Fixed real-time throughput sampling and normalized app-throughput display to exactly one row")


if __name__ == "__main__":
    main()
