package ai.edith.assistant

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress

/**
 * Wake-on-LAN: wakes the laptop from sleep by broadcasting a "magic packet" on the home Wi-Fi.
 * Works only on the same network, and only if the laptop's network adapter allows waking (see PC_BRIDGE.md).
 */
object WakeOnLan {
    private val MAC = Regex("^([0-9A-Fa-f]{2})([:-]?[0-9A-Fa-f]{2}){5}$")

    fun parseMac(text: String): ByteArray? {
        val t = text.trim()
        if (!MAC.matches(t)) return null
        val hex = t.replace(":", "").replace("-", "")
        return ByteArray(6) { i -> hex.substring(i * 2, i * 2 + 2).toInt(16).toByte() }
    }

    /** 6 x 0xFF, then the MAC address 16 times (102 bytes). */
    fun magicPacket(mac: ByteArray): ByteArray {
        require(mac.size == 6)
        val out = ByteArray(6 + 16 * 6) { 0xFF.toByte() }
        for (i in 0 until 16) System.arraycopy(mac, 0, out, 6 + i * 6, 6)
        return out
    }

    /** The Wi-Fi's own broadcast address (e.g. 192.168.1.255), which routers forward more reliably. */
    fun directedBroadcast(address: ByteArray, prefixLength: Int): ByteArray {
        val ip = address.fold(0L) { acc, b -> (acc shl 8) or (b.toLong() and 0xFF) }
        val mask = if (prefixLength == 0) 0L else (0xFFFFFFFFL shl (32 - prefixLength)) and 0xFFFFFFFFL
        val bcast = (ip and mask) or (mask.inv() and 0xFFFFFFFFL)
        return ByteArray(4) { i -> ((bcast shr (24 - 8 * i)) and 0xFF).toByte() }
    }

    /** Returns false when the phone isn't on Wi-Fi (the packet can't reach the laptop then). Blocking. */
    fun send(context: Context, macs: List<String>): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val net = cm.activeNetwork
        val caps = net?.let { cm.getNetworkCapabilities(it) }
        if (caps == null || !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return false
        val targets = mutableListOf<InetAddress>(InetAddress.getByName("255.255.255.255"))
        cm.getLinkProperties(net)?.linkAddresses?.firstOrNull { it.address is Inet4Address }?.let {
            targets.add(InetAddress.getByAddress(directedBroadcast(it.address.address, it.prefixLength)))
        }
        val packets = macs.mapNotNull { parseMac(it) }.map { magicPacket(it) }
        if (packets.isEmpty()) return false
        DatagramSocket().use { socket ->
            socket.broadcast = true
            net.bindSocket(socket)
            repeat(3) {
                for (p in packets) for (t in targets) for (port in intArrayOf(9, 7)) {
                    runCatching { socket.send(DatagramPacket(p, p.size, t, port)) }
                }
                Thread.sleep(150)
            }
        }
        return true
    }
}
