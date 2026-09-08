from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    old_discovery = '''                        if (open.isNotEmpty()) {
                            found += Device(ip, services = open, latencyMs = latency)
                        }'''
    new_discovery = '''                        if (open.isNotEmpty()) {
                            val resolvedName = try {
                                val hostName = InetAddress.getByName(ip).canonicalHostName
                                if (hostName.isNullOrBlank() || hostName == ip) "Unknown" else hostName
                            } catch (_: Exception) { "Unknown" }
                            found += Device(ip, host = resolvedName, services = open, latencyMs = latency)
                        }'''
    if old_discovery in s:
        s = s.replace(old_discovery, new_discovery, 1)
    elif new_discovery not in s:
        raise SystemExit("Device discovery marker not found")

    old_ui = '''                            Text(device.ip, style = MaterialTheme.typography.titleMedium)
                            Text(
                                "Services: ${device.services.joinToString()}" +'''
    new_ui = '''                            Text(
                                if (device.host.isBlank() || device.host == "Unknown") device.ip
                                else device.host,
                                style = MaterialTheme.typography.titleMedium
                            )
                            Text(
                                "IP: ${device.ip}" +
                                    " • Services: ${device.services.joinToString()}" +'''
    if old_ui in s:
        s = s.replace(old_ui, new_ui, 1)
    elif new_ui not in s:
        raise SystemExit("DevicesTab UI marker not found")

    MAIN.write_text(s, encoding="utf-8")
    print("Device discovery now resolves host names and Devices tab displays name + IP")


if __name__ == "__main__":
    main()
