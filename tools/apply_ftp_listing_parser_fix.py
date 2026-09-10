from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def replace_function(source: str, name: str, body: str) -> str:
    needle = f"    private fun {name}("
    start = source.find(needle)
    if start < 0:
        raise SystemExit(f"{name} function not found")
    brace = source.find("{", start)
    if brace < 0:
        raise SystemExit(f"Opening brace not found for {name}")
    depth = 0
    i = brace
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                return source[:start] + body + source[end:]
        i += 1
    raise SystemExit(f"Unterminated {name} function")


def main():
    s = MAIN.read_text(encoding="utf-8")
    body = r'''    private fun parseListing(text: String, basePath: String = ""): List<RemoteEntry> {
        val normalizedBase = basePath.trim('/').trim()
        val windowsDos = Regex("^\\s*(\\d{1,2}[-/]\\d{1,2}[-/]\\d{2,4})\\s+(\\d{1,2}:\\d{2}(?::\\d{2})?\\s*[AP]M)\\s+(<DIR>|\\d+)\\s+(.+)$", RegexOption.IGNORE_CASE)
        return text.lineSequence().mapNotNull { line ->
            val value = line.trim()
            if (value.isBlank()) return@mapNotNull null

            // Windows/DOS FTP LIST format, e.g.:
            // 11-17-2025 12:51PM 123456 report.ods
            // 09-10-2026 12:12AM <DIR> 5g sim
            val dos = windowsDos.matchEntire(value)
            if (dos != null) {
                val kindOrSize = dos.groupValues[3]
                val name = dos.groupValues[4].trim()
                if (name == "." || name == "..") return@mapNotNull null
                val directory = kindOrSize.equals("<DIR>", true)
                val size = if (directory) 0L else kindOrSize.toLongOrNull() ?: 0L
                val path = if (normalizedBase.isBlank()) name else "$normalizedBase/$name"
                return@mapNotNull RemoteEntry(name = name, size = size, directory = directory, path = path)
            }

            // Unix LIST format used by NetFTPLab's embedded server and many FTP servers.
            val parts = value.split(Regex("\\s+"), limit = 9)
            if (parts.size >= 9 && (parts[0].startsWith("d") || parts[0].startsWith("-"))) {
                val name = parts[8]
                if (name == "." || name == "..") return@mapNotNull null
                val directory = parts[0].startsWith("d")
                val size = parts[4].toLongOrNull() ?: 0L
                val path = if (normalizedBase.isBlank()) name else "$normalizedBase/$name"
                return@mapNotNull RemoteEntry(name = name, size = size, directory = directory, path = path)
            }

            null
        }.toList()
    }
'''
    MAIN.write_text(replace_function(s, "parseListing", body), encoding="utf-8")
    print("FTP listing parser now supports Windows/DOS and Unix LIST formats")


if __name__ == "__main__":
    main()
