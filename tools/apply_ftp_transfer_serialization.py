from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # The multi-file transfer patch may already have applied this serialization
    # change. Make this patch idempotent so CI never fails merely because the
    # marker was already removed by an earlier patch.
    old_finally = '''            } finally {
                refreshRemote()
            }
    }

    private fun queueDownloads'''
    new_finally = '''            }
    }

    private fun queueDownloads'''
    if old_finally in s:
        s = s.replace(old_finally, new_finally, 1)
    elif "            } finally {\n                refreshRemote()\n            }" in s:
        s = s.replace("            } finally {\n                refreshRemote()\n            }", "            }", 1)
    elif "refreshRemote()" not in s:
        raise SystemExit("Unable to locate upload refresh-finally marker")

    # Ensure the queue performs one LIST refresh only after every upload has
    # completed. If this is already present, leave it untouched.
    old_queue_end = '''            withContext(Dispatchers.Main) { uploadQueueRunning = false }
        }
    }

    private suspend fun uploadUriNow'''
    new_queue_end = '''            withContext(Dispatchers.Main) { uploadQueueRunning = false }
            // Refresh only after the complete upload queue has finished, so
            // LIST cannot overlap the next upload's SIZE/EPSV/STOR sequence.
            refreshRemote()
        }
    }

    private suspend fun uploadUriNow'''
    if old_queue_end in s:
        s = s.replace(old_queue_end, new_queue_end, 1)
    elif new_queue_end not in s:
        raise SystemExit("Upload queue completion marker not found")

    # Prevent a manual LIST from being launched while queued transfers are
    # using the same persistent FTP control/data connection.
    s = s.replace(
        'enabled = connectedTarget.isNotBlank(),\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }',
        'enabled = connectedTarget.isNotBlank() && !uploadQueueRunning && !downloadQueueRunning,\n                                modifier = Modifier.weight(1f)\n                            ) { Text("Refresh") }',
        1,
    )

    MAIN.write_text(s, encoding="utf-8")
    print("FTP transfer serialization patch applied (or already present)")


if __name__ == "__main__":
    main()
