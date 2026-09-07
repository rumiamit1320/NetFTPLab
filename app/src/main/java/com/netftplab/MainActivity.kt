package com.netftplab

import android.Manifest
import android.content.ClipData
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import android.net.ConnectivityManager
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.google.zxing.BarcodeFormat
import com.google.zxing.MultiFormatWriter
import kotlinx.coroutines.*
import java.io.*
import java.net.*
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.min

data class Device(val ip: String, val services: List<Int>, val latencyMs: Long?)
data class LogLine(val time: String, val layer: String, val text: String)
data class SessionStats(val rttMs: Long = 0, val connected: Boolean = false, val target: String = "", val bytes: Long = 0, val throughputBps: Long = 0)
data class RemoteEntry(val name: String, val size: Long, val directory: Boolean)
data class TransferState(val active:Boolean=false,val direction:String="",val name:String="",val done:Long=0,val total:Long=-1,val speedBps:Long=0,val message:String="Idle",val sha256Local:String="",val sha256Remote:String="",val verified:Boolean?=null)

class MainActivity : ComponentActivity() {
    private val devices = mutableStateListOf<Device>()
    private val logs = mutableStateListOf<LogLine>()
    private val remote = mutableStateListOf<RemoteEntry>()
    private var scanning by mutableStateOf(false)
    private var target by mutableStateOf("")
    private var session by mutableStateOf(SessionStats())
    private var transfer by mutableStateOf(TransferState())
    private var serverRunning by mutableStateOf(false)
    private var showQr by mutableStateOf(false)
    private var ftp: FtpClient? = null
    private lateinit var server: FtpServer
    private lateinit var transferRoot: File

    private val picker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let(::upload) }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        transferRoot = File(getExternalFilesDir(null), "NetFTPLabTransfers").apply { mkdirs() }
        server = FtpServer(File(getExternalFilesDir(null), "NetFTPShare").apply { mkdirs() }, logger = ::log)
        if (android.os.Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
        setContent { App() }
    }

    override fun onDestroy() { try { ftp?.close() } catch (_:Exception) {}; server.stop(); super.onDestroy() }

    private fun log(layer:String,text:String) {
        val t=SimpleDateFormat("HH:mm:ss.SSS",Locale.US).format(Date())
        runOnUiThread { logs.add(LogLine(t,layer,text)); if(logs.size>800) logs.removeAt(0) }
    }
    private fun ipv4():String? {
        val cm=getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val lp=cm.getLinkProperties(cm.activeNetwork) ?: return null
        return lp.linkAddresses.firstOrNull { it.address is Inet4Address }?.address?.hostAddress
    }
    private fun scan() {
        if(scanning)return
        val base=ipv4()?.substringBeforeLast('.') ?: run { log("ERROR","No IPv4 LAN interface"); return }
        scanning=true; devices.clear(); log("DISCOVERY","Scanning $base.0/24 for FTP and NetFTP Lab services")
        lifecycleScope.launch(Dispatchers.IO) {
            val found=Collections.synchronizedList(mutableListOf<Device>())
            coroutineScope { (1..254).map { n -> async {
                val ip="$base.$n"; val open=mutableListOf<Int>(); var rtt:Long?=null
                for(p in listOf(21,2121)) { val t=System.currentTimeMillis(); try { Socket().use { s->s.connect(InetSocketAddress(ip,p),220); if(rtt==null)rtt=System.currentTimeMillis()-t; open+=p } } catch(_:Exception){} }
                if(open.isNotEmpty())found+=Device(ip,open,rtt)
            } }.awaitAll() }
            withContext(Dispatchers.Main){ devices.addAll(found.sortedBy{it.ip.substringAfterLast('.').toIntOrNull()?:999}); scanning=false; log("DISCOVERY","Found ${found.size} FTP-capable devices") }
        }
    }
    private fun connect(d:Device) = lifecycleScope.launch(Dispatchers.IO) {
        try {
            ftp?.close(); val p=if(2121 in d.services)2121 else 21
            log("TCP","Connecting ${d.ip}:$p"); val c=FtpClient(d.ip,p,::log); c.connect(); c.login("anonymous","anonymous@netftp.local"); ftp=c
            target="${d.ip}:$p"; session=SessionStats(connected=true,target=target); refresh()
        } catch(e:Exception){log("ERROR","Connection failed: ${e.message}")}
    }
    private fun refresh()=lifecycleScope.launch(Dispatchers.IO){try{val x=ftp?.list()?:return@launch;val a=x.lineSequence().mapNotNull{l->val s=l.trim();if(s.isBlank())return@mapNotNull null;val p=s.split(Regex("\\s+"),limit=9);if(p.size>=9)RemoteEntry(p[8],p[4].toLongOrNull()?:0,p[0].startsWith("d"))else RemoteEntry(s,0,false)}.filter{it.name!="."&&it.name!=".."};withContext(Dispatchers.Main){remote.clear();remote.addAll(a)} }catch(e:Exception){log("ERROR","LIST failed: ${e.message}")}}
    private fun upload(uri:android.net.Uri){if(target.isBlank()){log("ERROR","Connect to an FTP device first");return};val name=queryName(uri)?:"upload-${System.currentTimeMillis()}";lifecycleScope.launch(Dispatchers.IO){try{val size=querySize(uri);val input=contentResolver.openInputStream(uri)?:throw IOException("Cannot open file");val start=System.currentTimeMillis();transfer=TransferState(true,"UPLOAD",name,0,size,message="Starting");ftp?.upload(name,input,size){d,t->transfer=transfer.copy(done=d,total=t,speedBps=d*1000/maxOf(1,System.currentTimeMillis()-start),message="Transferring")};input.close();val lh=contentHash(uri);val rh=ftp?.remoteSha256(name).orEmpty();transfer=transfer.copy(active=false,message="Complete",sha256Local=lh,sha256Remote=rh,verified=if(rh.isBlank())null else lh.equals(rh,true));session=session.copy(bytes=session.bytes+size)}catch(e:Exception){transfer=transfer.copy(active=false,message="Upload failed: ${e.message}");log("ERROR",e.message?:"upload error")}finally{refresh()}}}
    private fun download(e:RemoteEntry){if(e.directory)return;lifecycleScope.launch(Dispatchers.IO){try{val f=File(transferRoot,e.name).canonicalFile;if(!f.path.startsWith(transferRoot.canonicalPath+File.separator))throw IOException("Unsafe filename");val size=ftp?.remoteSize(e.name)?:e.size;val resume=if(f.exists())min(f.length(),size)else 0;RandomAccessFile(f,"rw").use{raf->raf.setLength(resume);raf.seek(resume);val start=System.currentTimeMillis();transfer=TransferState(true,"DOWNLOAD",e.name,resume,size,message=if(resume>0)"Resuming" else "Starting");val out=object:OutputStream(){override fun write(b:Int)=raf.write(b);override fun write(b:ByteArray,o:Int,l:Int)=raf.write(b,o,l)};ftp?.download(e.name,out,resume){d,t->transfer=transfer.copy(done=d,total=t,speedBps=d*1000/maxOf(1,System.currentTimeMillis()-start),message="Transferring")};out.flush()};val lh=hash(f);val rh=ftp?.remoteSha256(e.name).orEmpty();transfer=transfer.copy(active=false,message="Complete",sha256Local=lh,sha256Remote=rh,verified=if(rh.isBlank())null else lh.equals(rh,true));session=session.copy(bytes=session.bytes+f.length());log("DATA","Saved ${f.absolutePath}")}catch(x:Exception){transfer=transfer.copy(active=false,message="Download failed: ${x.message}");log("ERROR",x.message?:"download error")}}}
    private fun queryName(u:android.net.Uri)=contentResolver.query(u,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use{if(it.moveToFirst())it.getString(0)else null}
    private fun querySize(u:android.net.Uri)=contentResolver.query(u,arrayOf(OpenableColumns.SIZE),null,null,null)?.use{if(it.moveToFirst()&&!it.isNull(0))it.getLong(0)else -1}?:-1
    private fun contentHash(u:android.net.Uri)=contentResolver.openInputStream(u)?.use(::hashInput).orEmpty()
    private fun hash(f:File)=FileInputStream(f).use(::hashInput)
    private fun hashInput(i:InputStream):String{val m=MessageDigest.getInstance("SHA-256");val b=ByteArray(65536);while(true){val n=i.read(b);if(n<0)break;m.update(b,0,n)};return m.digest().joinToString(""){"%02x".format(it)}}
    private fun toggleServer(){try{if(serverRunning){server.stop();serverRunning=false}else{server.start();serverRunning=true;log("SERVER","FTP server started on ${ipv4()?:"0.0.0.0"}:2121")}}catch(e:Exception){log("ERROR","Server: ${e.message}")}}

    @Composable private fun App(){var tab by remember{mutableIntStateOf(0)};MaterialTheme(colorScheme=darkColorScheme(primary=Color(0xFF60A5FA),secondary=Color(0xFF34D399))){Scaffold(topBar={TopAppBar(title={Text("NetFTP Lab")},actions={IconButton(::scan){Icon(Icons.Default.Refresh,"Scan")}})},bottomBar={NavigationBar{val x=listOf("Devices" to Icons.Default.Devices,"Transfers" to Icons.Default.SwapVert,"Console" to Icons.Default.Terminal,"Network Lab" to Icons.Default.Timeline,"Server" to Icons.Default.Settings);x.forEachIndexed{i,(n,ic)->NavigationBarItem(tab==i,{tab=i},{Icon(ic,null)},{Text(n)})}}}){p->Box(Modifier.padding(p).fillMaxSize()){when(tab){0->Devices();1->Transfers();2->Console();3->Lab();else->Server()}}}}}
    @Composable private fun Devices(){Column(Modifier.fillMaxSize().padding(16.dp)){Text("ACTIVE DEVICES",style=MaterialTheme.typography.headlineSmall);Text("IPv4: ${ipv4()?:"not connected"}");Button(::scan,enabled=!scanning,Modifier.fillMaxWidth()){Text(if(scanning)"Scanning…" else "Scan LAN")};Spacer(Modifier.height(8.dp));LazyColumn(verticalArrangement=Arrangement.spacedBy(8.dp)){items(devices){d->Card(Modifier.fillMaxWidth().clickable{connect(d)}){Column(Modifier.padding(14.dp)){Text(d.ip,style=MaterialTheme.typography.titleMedium);Text("TCP ${d.services.joinToString()} • RTT ${d.latencyMs?:"-"} ms");Text(if(2121 in d.services)"NetFTP Lab server" else "FTP server")}}}}}}
    @Composable private fun Transfers(){Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())){Text("FILE TRANSFER",style=MaterialTheme.typography.headlineSmall);Text(if(target.isBlank())"Connect from Devices" else "Connected: $target");Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)){Button({picker.launch(arrayOf("*/*"))},enabled=target.isNotBlank()&&!transfer.active,Modifier.weight(1f)){Icon(Icons.Default.Upload,null);Text(" Upload")};OutlinedButton(::refresh,enabled=target.isNotBlank(),Modifier.weight(1f)){Text("Refresh")}};Spacer(Modifier.height(12.dp));if(transfer.message!="Idle")Card(Modifier.fillMaxWidth()){Column(Modifier.padding(12.dp)){Text("${transfer.direction} ${transfer.name}");Text(transfer.message);if(transfer.total>0){LinearProgressIndicator({(transfer.done.toFloat()/transfer.total).coerceIn(0f,1f)},Modifier.fillMaxWidth());Text("${transfer.done}/${transfer.total} B • ${rate(transfer.speedBps)}")};if(transfer.sha256Local.isNotBlank())Text("Local SHA-256: ${transfer.sha256Local}",fontFamily=FontFamily.Monospace);if(transfer.sha256Remote.isNotBlank())Text("Remote SHA-256: ${transfer.sha256Remote}",fontFamily=FontFamily.Monospace)}};Text("REMOTE FILES",style=MaterialTheme.typography.labelLarge);remote.forEach{e->Card(Modifier.fillMaxWidth().padding(vertical=3.dp).clickable{download(e)}){Row(Modifier.padding(12.dp),verticalAlignment=Alignment.CenterVertically){Icon(if(e.directory)Icons.Default.Folder else Icons.Default.InsertDriveFile,null);Spacer(Modifier.width(8.dp));Column(Modifier.weight(1f)){Text(e.name);Text(if(e.directory)"Directory" else "${e.size} B • tap to download")}}}}}}
    @Composable private fun Console(){Column(Modifier.fillMaxSize().padding(10.dp)){Row{Text("PROTOCOL CONSOLE",style=MaterialTheme.typography.titleMedium);Spacer(Modifier.weight(1f));TextButton({logs.clear()}){Text("Clear")}};LazyColumn(Modifier.fillMaxSize().background(Color(0xFF05070A)).padding(8.dp)){items(logs){l->Text("${l.time} ${l.layer.padEnd(10)} ${l.text}",fontFamily=FontFamily.Monospace,style=MaterialTheme.typography.bodySmall)}}}}
    @Composable private fun Lab(){var mode by remember{mutableStateOf("ALOHA")};var g by remember{mutableFloatStateOf(1f)};var cc by remember{mutableStateOf("RENO")};val s=when(mode){"SLOTTED"->NetworkLab.slottedThroughput(g.toDouble());"CSMA/CA"->NetworkLab.csmaCaThroughput(g.toDouble());else->NetworkLab.alohaThroughput(g.toDouble())};Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())){Text("NETWORK LAB",style=MaterialTheme.typography.headlineSmall);Text("MAC models are educational; ordinary Android apps cannot read every Wi-Fi collision.");Spacer(Modifier.height(10.dp));Row(horizontalArrangement=Arrangement.spacedBy(6.dp)){listOf("ALOHA","SLOTTED","CSMA/CA").forEach{OutlinedButton({mode=it}){Text(if(mode==it)"[$it]" else it)}}};Text("Offered load G: %.2f".format(g));Slider(g,{g=it},.05f..4f);Card(Modifier.fillMaxWidth()){Column(Modifier.padding(14.dp)){Text("Throughput S = %.4f".format(s));Text("Contention/collision index = %.1f%%".format((1-s).coerceIn(0.0,1.0)*100))}};Spacer(Modifier.height(10.dp));Text("TCP CONGESTION CONTROL",style=MaterialTheme.typography.titleMedium);Row(horizontalArrangement=Arrangement.spacedBy(6.dp)){listOf("RENO","CUBIC","BBR").forEach{OutlinedButton({cc=it}){Text(if(cc==it)"[$it]" else it)}}};val tr=NetworkLab.cwndTrace(cc);val maxY=tr.maxOf{it.y}.coerceAtLeast(1f);tr.takeLast(20).forEach{Row(verticalAlignment=Alignment.CenterVertically){Text("${it.x.toInt()}",Modifier.width(30.dp));LinearProgressIndicator({it.y/maxY},Modifier.weight(1f));Text(" %.1f".format(it.y),Modifier.width(45.dp))}};Text("cwnd trace is modeled, not kernel TCP telemetry.")}}
    @Composable private fun Server(){val ip=ipv4();Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())){Text("EMBEDDED FTP SERVER",style=MaterialTheme.typography.headlineSmall);Text(if(serverRunning)"● RUNNING" else "○ STOPPED");Text("Endpoint: ${ip?:"-"}:2121");Text("Passive ports: 21210–21250");Text("Anonymous LAN laboratory server");Spacer(Modifier.height(10.dp));Button(::toggleServer){Text(if(serverRunning)"Stop Server" else "Start Server")};Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)){OutlinedButton({showQr=true},enabled=ip!=null,Modifier.weight(1f)){Text("Connection QR")};OutlinedButton({val t="ftp://${ip?:"<phone-ip>"}:2121";(getSystemService(Context.CLIPBOARD_SERVICE)as android.content.ClipboardManager).setPrimaryClip(ClipData.newPlainText("NetFTP endpoint",t));log("SERVER","Endpoint copied")},Modifier.weight(1f)){Text("Copy endpoint")}};if(showQr&&ip!=null)AlertDialog(onDismissRequest={showQr=false},title={Text("FTP connection QR")},text={Column(horizontalAlignment=Alignment.CenterHorizontally,modifier=Modifier.fillMaxWidth()){Qr("ftp://$ip:2121");Text("ftp://$ip:2121",fontFamily=FontFamily.Monospace)}},confirmButton={TextButton({showQr=false}){Text("Close")}});Spacer(Modifier.height(12.dp));Text("Server capabilities",style=MaterialTheme.typography.titleMedium);listOf("Multiple simultaneous sessions","PASV + EPSV","LIST / NLST","RETR / STOR","REST resume","SIZE / XSHA256","CWD / CDUP / PWD / DELE").forEach{Text("✓ $it")}}}
    @Composable private fun Qr(value:String){val b=remember(value){val m=MultiFormatWriter().encode(value,BarcodeFormat.QR_CODE,640,640);Bitmap.createBitmap(640,640,Bitmap.Config.RGB_565).also{for(x in 0 until 640)for(y in 0 until 640)it.setPixel(x,y,if(m.get(x,y))AndroidColor.BLACK else AndroidColor.WHITE)}};Image(b.asImageBitmap(),null,Modifier.size(250.dp))}
    private fun rate(v:Long)=when{v>=1_000_000->"%.2f MB/s".format(v/1_000_000.0);v>=1_000->"%.1f KB/s".format(v/1_000.0);else->"$v B/s"}
}
