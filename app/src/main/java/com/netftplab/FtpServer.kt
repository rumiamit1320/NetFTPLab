package com.netftplab

import java.io.*
import java.net.*
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

/** LAN-only FTP server. It deliberately uses a fixed passive range so a firewall can be configured. */
class FtpServer(
    private val root: File,
    private val controlPort: Int = 2121,
    private val passiveStart: Int = 21210,
    private val passiveEnd: Int = 21250,
    private val logger: (String, String) -> Unit
) {
    private val running = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null
    private var workers: ExecutorService = Executors.newCachedThreadPool()
    private val passiveLock = Any()
    private val passiveInUse = mutableSetOf<Int>()

    fun isRunning(): Boolean = running.get()

    fun start() {
        if (!running.compareAndSet(false, true)) return
        root.mkdirs()
        if (workers.isShutdown) workers = Executors.newCachedThreadPool()
        workers.execute {
            try {
                serverSocket = ServerSocket(controlPort, 64, InetAddress.getByName("0.0.0.0"))
                logger("SERVER", "FTP server listening on :$controlPort; PASV $passiveStart-$passiveEnd")
                while (running.get()) {
                    try {
                        val s = serverSocket!!.accept()
                        workers.execute { handleClient(s) }
                    } catch (e: SocketException) {
                        if (running.get()) logger("ERROR", "FTP accept: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                logger("ERROR", "FTP server start failed: ${e.message}")
                running.set(false)
            }
        }
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        try { serverSocket?.close() } catch (_: Exception) {}
        synchronized(passiveLock) { passiveInUse.clear() }
        workers.shutdownNow()
        logger("SERVER", "FTP server stopped")
    }

    private fun handleClient(socket: Socket) {
        var user = ""
        var cwd = root.canonicalFile
        var loggedIn = false
        var restOffset = 0L
        var pasv: PassiveEndpoint? = null
        var renameFrom: File? = null
        try {
            socket.soTimeout = 30000
            val reader = socket.getInputStream().bufferedReader(StandardCharsets.US_ASCII)
            val writer = socket.getOutputStream().bufferedWriter(StandardCharsets.US_ASCII)
            fun reply(code: Int, text: String) {
                writer.write("$code $text\r\n"); writer.flush()
                logger("FTP", "RX->$code $text")
            }
            fun command(): String? = reader.readLine()?.also { logger("FTP", "CTRL ${socket.inetAddress.hostAddress}: $it") }
            reply(220, "NetFTP Lab FTP Server ready")
            while (running.get()) {
                val line = command() ?: break
                val sp = line.indexOf(' ')
                val cmd = (if (sp < 0) line else line.substring(0, sp)).uppercase()
                val arg = if (sp < 0) "" else line.substring(sp + 1)
                when (cmd) {
                    "USER" -> { user = arg; reply(331, "Password required for $user") }
                    "PASS" -> { loggedIn = user.isNotBlank(); if (loggedIn) reply(230, "User logged in") else reply(530, "Login incorrect") }
                    "SYST" -> reply(215, "UNIX Type: L8")
                    "FEAT" -> {
                        writer.write("211-Features\r\n")
                        writer.write(" SIZE\r\n")
                        writer.write(" REST STREAM\r\n")
                        writer.write(" EPSV\r\n")
                        writer.write(" PASV\r\n")
                        writer.write(" UTF8\r\n")
                        writer.write(" MDTM\r\n")
                        writer.write(" APPE\r\n")
                        writer.write(" MLST\r\n")
                        writer.write(" MLSD\r\n")
                        writer.write("211 End\r\n")
                        writer.flush()
                    }
                    "PWD", "XPWD" -> reply(257, "\"${ftpPath(cwd)}\"")
                    "TYPE" -> reply(200, "Type set to ${arg.ifBlank { "I" }}")
                    "MODE" -> if (arg.equals("S", true)) reply(200, "Mode set to Stream") else reply(504, "Mode not supported")
                    "STRU" -> if (arg.equals("F", true)) reply(200, "Structure set to File") else reply(504, "Structure not supported")
                    "ALLO" -> reply(202, "ALLO command ignored; storage is allocated automatically")
                    "OPTS" -> reply(200, "OK")
                    "NOOP" -> reply(200, "NOOP ok")
                    "HELP" -> {
                        reply(214, "Supported commands: USER PASS PWD CWD CDUP TYPE MODE STRU ALLO FEAT SYST OPTS NOOP HELP STAT LIST NLST SIZE MDTM RETR STOR APPE REST ABOR RNFR RNTO MKD RMD DELE PASV EPSV QUIT")
                    }
                    "STAT" -> {
                        reply(211, "NetFTP Lab status: ${if (loggedIn) "logged in" else "not logged in"}; CWD ${ftpPath(cwd)}; PASV ${pasv?.port ?: "none"}")
                    }
                    "CWD" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val target = safeResolve(cwd, arg)
                        if (target?.isDirectory == true) { cwd = target; reply(250, "Directory changed") } else reply(550, "Directory unavailable")
                    }
                    "CDUP" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val parent = cwd.parentFile?.canonicalFile
                        if (parent != null && (parent.path == root.canonicalPath || parent.path.startsWith(root.canonicalPath + File.separator))) { cwd = parent; reply(200, "Directory changed") } else reply(550, "Access denied")
                    }
                    "PASV" -> if (!loggedIn) reply(530, "Not logged in") else {
                        pasv?.close(); pasv = allocatePassive()
                        if (pasv == null) reply(421, "No passive ports available") else {
                            val a = socket.localAddress.hostAddress?.split('.') ?: listOf("127","0","0","1")
                            val p1 = pasv!!.port / 256; val p2 = pasv!!.port % 256
                            reply(227, "Entering Passive Mode (${a.joinToString(",")},$p1,$p2)")
                            logger("DATA", "PASV allocated :${pasv!!.port} for ${socket.inetAddress.hostAddress}")
                        }
                    }
                    "EPSV" -> if (!loggedIn) reply(530, "Not logged in") else {
                        pasv?.close(); pasv = allocatePassive()
                        if (pasv == null) reply(421, "No passive ports available") else reply(229, "Entering Extended Passive Mode (|||${pasv!!.port}|)")
                    }
                    "LIST", "NLST" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val ep = pasv ?: allocatePassive()
                        if (ep == null) reply(425, "Use PASV first") else {
                            reply(150, "Opening data connection")
                            ep.acceptAndUse { ch ->
                                val out = ch.output()
                                val target = safeResolve(cwd, arg.ifBlank { "." }) ?: cwd
                                val files = if (target.isDirectory) target.listFiles()?.toList().orEmpty() else listOf(target)
                                val dateFmt = SimpleDateFormat("MMM dd HH:mm", Locale.US)
                                val text = if (cmd == "NLST") {
                                    files.joinToString("\r\n") { it.name } + if (files.isNotEmpty()) "\r\n" else ""
                                } else {
                                    files.joinToString("\r\n") { f ->
                                        val type = if (f.isDirectory) 'd' else '-'
                                        String.format("%crw-r--r-- 1 owner group %10d %s %s", type, f.length(), dateFmt.format(Date(f.lastModified())), f.name)
                                    } + if (files.isNotEmpty()) "\r\n" else ""
                                }
                                out.write(text.toByteArray(StandardCharsets.UTF_8)); out.flush()
                            }
                            reply(226, "Transfer complete"); pasv = null
                        }
                    }
                    "SIZE" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg)
                        if (f?.isFile == true) reply(213, f.length().toString()) else reply(550, "File unavailable")
                    }
                    "MDTM" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg)
                        if (f?.exists() == true) {
                            val fmt = SimpleDateFormat("yyyyMMddHHmmss", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }
                            reply(213, fmt.format(Date(f.lastModified())))
                        } else reply(550, "File unavailable")
                    }
                    "XSHA256" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg)
                        if (f?.isFile == true) {
                            val md = java.security.MessageDigest.getInstance("SHA-256")
                            FileInputStream(f).use { input ->
                                val buf = ByteArray(64 * 1024)
                                while (true) { val n = input.read(buf); if (n < 0) break; md.update(buf, 0, n) }
                            }
                            reply(213, md.digest().joinToString("") { "%02x".format(it) })
                        } else reply(550, "File unavailable")
                    }
                    "REST" -> { restOffset = arg.toLongOrNull()?.coerceAtLeast(0) ?: 0; reply(350, "Restart position accepted") }
                    "RETR" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg); val ep = pasv
                        if (f?.isFile != true || ep == null) reply(550, "File or passive connection unavailable") else {
                            reply(150, "Opening binary data connection")
                            ep.acceptAndUse { ch ->
                                val out = ch.output()
                                RandomAccessFile(f, "r").use { raf ->
                                    raf.seek(min(restOffset, raf.length()))
                                    val buf = ByteArray(64 * 1024); var total = 0L
                                    while (true) { val n = raf.read(buf); if (n < 0) break; out.write(buf, 0, n); total += n }
                                    out.flush(); logger("DATA", "RETR ${f.name}: $total bytes")
                                }
                            }
                            restOffset = 0; reply(226, "Transfer complete"); pasv = null
                        }
                    }
                    "STOR", "APPE" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg); val ep = pasv
                        if (f == null || ep == null) reply(550, "File or passive connection unavailable") else {
                            f.parentFile?.mkdirs(); reply(150, "Opening binary data connection")
                            ep.acceptAndUse { ch ->
                                val input = ch.input()
                                RandomAccessFile(f, "rw").use { raf ->
                                    val start = if (cmd == "APPE") raf.length() else min(restOffset, raf.length())
                                    raf.seek(start)
                                    val buf = ByteArray(64 * 1024); var total = start
                                    while (true) { val n = input.read(buf); if (n < 0) break; raf.write(buf, 0, n); total += n }
                                    logger("DATA", "${cmd} ${f.name}: $total bytes total")
                                }
                            }
                            restOffset = 0; reply(226, "Transfer complete"); pasv = null
                        }
                    }
                    "MKD", "XMKD" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val target = safeResolve(cwd, arg)
                        if (target == null) reply(550, "Invalid path")
                        else if (target.exists()) reply(550, "Directory already exists")
                        else if (target.mkdirs()) reply(257, "\"${ftpPath(target)}\" directory created")
                        else reply(550, "Create directory failed")
                    }
                    "RMD", "XRMD" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val target = safeResolve(cwd, arg)
                        if (target == null || target == root.canonicalFile || !target.isDirectory) reply(550, "Directory unavailable")
                        else if (target.listFiles()?.isNotEmpty() == true) reply(550, "Directory not empty")
                        else if (target.delete()) reply(250, "Directory removed") else reply(550, "Remove directory failed")
                    }
                    "DELE" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg); if (f != null && f.isFile && f.delete()) reply(250, "File deleted") else reply(550, "Delete failed")
                    }
                    "RNFR" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val f = safeResolve(cwd, arg)
                        if (f != null && f.exists() && f != root.canonicalFile) { renameFrom = f; reply(350, "Ready for RNTO") } else reply(550, "File or directory unavailable")
                    }
                    "RNTO" -> if (!loggedIn) reply(530, "Not logged in") else {
                        val source = renameFrom
                        renameFrom = null
                        val target = safeResolve(cwd, arg)
                        if (source == null) reply(503, "RNFR required first")
                        else if (target == null || target == root.canonicalFile || target.exists()) reply(550, "Invalid or existing destination")
                        else if (source.renameTo(target)) reply(250, "Rename successful") else reply(550, "Rename failed")
                    }
                    "ABOR" -> {
                        restOffset = 0
                        pasv?.close(); pasv = null
                        reply(226, "Abort command acknowledged; no active transfer")
                    }
                    "QUIT" -> { reply(221, "Goodbye"); break }
                    else -> reply(502, "Command not implemented")
                }
            }
        } catch (e: Exception) {
            if (running.get()) logger("ERROR", "Client ${socket.inetAddress.hostAddress}: ${e.message}")
        } finally {
            try { pasv?.close() } catch (_: Exception) {}
            try { socket.close() } catch (_: Exception) {}
        }
    }

    private fun safeResolve(cwd: File, raw: String): File? {
        val arg = raw.trim().removePrefix("/")
        val base = if (raw.trim().startsWith("/")) root else cwd
        val f = try { File(base, arg).canonicalFile } catch (_: Exception) { return null }
        return if (f.path == root.canonicalPath || f.path.startsWith(root.canonicalPath + File.separator)) f else null
    }

    private fun ftpPath(f: File): String = "/" + f.canonicalPath.removePrefix(root.canonicalPath).trimStart(File.separatorChar).replace(File.separatorChar, '/')

    private fun allocatePassive(): PassiveEndpoint? {
        synchronized(passiveLock) {
            for (p in passiveStart..passiveEnd) if (!passiveInUse.contains(p)) {
                try { passiveInUse += p; return PassiveEndpoint(p) { releasePort(p) } } catch (_: IOException) { passiveInUse.remove(p) }
            }
        }
        return null
    }

    private fun releasePort(port: Int) { synchronized(passiveLock) { passiveInUse.remove(port) } }

    private class PassiveEndpoint(val port: Int, private val release: () -> Unit) : Closeable {
        private val server = ServerSocket(port, 4, InetAddress.getByName("0.0.0.0"))
        fun <T> acceptAndUse(block: (InputStreamOrOutput) -> T): T {
            server.soTimeout = 30000
            return try {
                val s = server.accept()
                s.use {
                    val adapter = object : InputStreamOrOutput {
                        override fun input(): InputStream = it.getInputStream()
                        override fun output(): OutputStream = it.getOutputStream()
                    }
                    block(adapter)
                }
            } finally { close() }
        }
        override fun close() { try { server.close() } finally { release() } }
    }

    private interface InputStreamOrOutput {
        fun input(): InputStream = throw UnsupportedOperationException()
        fun output(): OutputStream = throw UnsupportedOperationException()
    }
}
