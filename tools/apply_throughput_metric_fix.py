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
    else:
        print("Throughput metric already normalized; no source change needed")
        return

    # Remove only accidental duplicate display rows. Keep one app-throughput row.
    duplicate = '''                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")
                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")
                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")'''
    single = '''                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")'''
    if duplicate in text:
        text = text.replace(duplicate, single, 1)

    text = text.replace(
        '                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")\n                Text("Session bytes ${formatBytes(session.bytes)}")',
        '                Text("App network throughput: ${formatMbps(appNetworkMbps)} Mbps")\n                Text("Session bytes ${formatBytes(session.bytes)}")',
        1,
    )

    ADV.write_text(text, encoding="utf-8")
    print("Fixed real-time throughput sampling: active FTP speed is shown during transfer and not held after completion; duplicate display rows removed")


if __name__ == "__main__":
    main()
