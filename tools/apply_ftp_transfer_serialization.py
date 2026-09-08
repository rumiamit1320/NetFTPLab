from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Each upload must finish all control/data-channel operations before the
    # next queued upload starts. refreshRemote() launches another coroutine,
    # so calling it from uploadUriNow() creates concurrent FTP commands on the
    # same persistent FtpClient and can race for the passive data socket.
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
    else:
        raise SystemExit("Upload refresh-finally marker not found")

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
    print("Serialized queued FTP uploads and deferred remote LIST refresh")


if __name__ == "__main__":
    main()
