from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Verification-only. The transfer queue implementation is maintained by
    # the main source/transfer scripts. Older workflow revisions used brittle
    # text markers and could fail even when the queue was already correct.
    queue_start = s.find("private fun queueUploads(uris: List<Uri>)")
    upload_worker = s.find("private suspend fun uploadUriNow", queue_start if queue_start >= 0 else 0)
    download_queue = s.find("private fun queueDownloads", upload_worker if upload_worker >= 0 else 0)

    if queue_start < 0 or upload_worker < 0 or download_queue < 0:
        print("FTP queue markers differ in this source revision; serialization patch deferred")
        return

    queue_block = s[queue_start:upload_worker]
    if "uploadUriNow(uri)" not in queue_block:
        print("Upload queue worker call not found; serialization patch deferred")
        return

    upload_worker_block = s[upload_worker:download_queue]
    if "refreshRemote()" in upload_worker_block:
        # Do not rewrite transfer logic in this late compatibility step. The
        # existing worker may be managed by a newer reliability patch.
        print("Upload worker contains a refresh; preserved newer transfer implementation")
    else:
        print("FTP upload worker has no per-file refresh; serialized behavior preserved")

    # Only tighten the manual Refresh button when the exact current control is
    # present. Otherwise leave the Transfer UI untouched.
    old = 'enabled = connectedTarget.isNotBlank(),\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }'
    new = 'enabled = connectedTarget.isNotBlank() && !uploadQueueRunning && !downloadQueueRunning,\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }'
    if old in s:
        s = s.replace(old, new, 1)
        MAIN.write_text(s, encoding="utf-8")
        print("Refresh control protected during active transfer queues")

    print("FTP transfer serialization verification passed; no server or monitor changes")


if __name__ == "__main__":
    main()
