from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Final transfer serialization step is intentionally conservative. The
    # workflow has several older source-generation steps, so this script must
    # not depend on an exact indentation/formatting marker and must never
    # rebuild the transfer implementation.
    queue_start = s.find("private fun queueUploads(uris: List<Uri>)")
    upload_worker = s.find("private suspend fun uploadUriNow", queue_start)
    if queue_start < 0 or upload_worker < 0:
        raise SystemExit("FTP upload queue functions not found")

    queue_block = s[queue_start:upload_worker]
    if "uploadUriNow(uri)" not in queue_block:
        raise SystemExit("Upload queue worker call not found")
    if "refreshRemote()" not in queue_block:
        raise SystemExit("Upload queue completion refresh is missing")

    # A per-file refresh defeats sequential FTP serialization and generates a
    # continuous LIST storm. Verify that the upload worker itself does not
    # contain that refresh. The queue-level refresh above is retained.
    worker_end = s.find("private fun queueDownloads", upload_worker)
    if worker_end < 0:
        worker_end = s.find("private suspend fun downloadFolderNow", upload_worker)
    if worker_end < 0:
        raise SystemExit("FTP download queue boundary not found")
    upload_worker_block = s[upload_worker:worker_end]
    if "refreshRemote()" in upload_worker_block:
        raise SystemExit("Per-file upload refresh is still present")

    # Refresh controls are UI-specific. Only change the known exact control if
    # it exists; otherwise leave the Transfer UI untouched.
    old = 'enabled = connectedTarget.isNotBlank(),\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }'
    new = 'enabled = connectedTarget.isNotBlank() && !uploadQueueRunning && !downloadQueueRunning,\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }'
    if old in s:
        s = s.replace(old, new, 1)

    MAIN.write_text(s, encoding="utf-8")
    print("FTP transfer serialization verified; no server or monitor changes")


if __name__ == "__main__":
    main()
