package ai.edith.assistant

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothClass
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import androidx.core.content.ContextCompat

/**
 * "Only work with my headphones": EDITH listens only while one of the user's registered
 * Bluetooth headphones is connected. Registration happens in the EDITH app.
 *
 * This is a convenience lock (it stops EDITH answering through other people's or random
 * headphones), not strong security: Bluetooth names/addresses can be imitated.
 */
object Headphones {
    data class Device(val address: String, val name: String) {
        fun encode() = "$address|$name"

        companion object {
            fun decode(s: String) = s.split('|', limit = 2).let { Device(it[0], it.getOrElse(1) { "" }) }
        }
    }

    private val BT_TYPES = buildSet {
        add(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)
        add(AudioDeviceInfo.TYPE_BLUETOOTH_SCO)
        add(AudioDeviceInfo.TYPE_HEARING_AID)
        if (Build.VERSION.SDK_INT >= 31) {
            add(AudioDeviceInfo.TYPE_BLE_HEADSET)
            add(AudioDeviceInfo.TYPE_BLE_SPEAKER)
        }
    }

    /** Bluetooth audio devices connected right now. */
    fun connected(ctx: Context): List<Device> {
        val am = ctx.getSystemService(AudioManager::class.java)
        return am.getDevices(AudioManager.GET_DEVICES_OUTPUTS or AudioManager.GET_DEVICES_INPUTS)
            .filter { it.type in BT_TYPES }
            .map {
                // Address is available from Android 9; on Android 8 matching falls back to the name.
                val address = if (Build.VERSION.SDK_INT >= 28) it.address.orEmpty() else ""
                Device(address, it.productName?.toString().orEmpty())
            }
            .distinctBy { it.address.ifBlank { it.name } }
    }

    /** Paired (bonded) Bluetooth audio devices, connected or not. Needs BLUETOOTH_CONNECT on Android 12+. */
    @SuppressLint("MissingPermission")
    fun paired(ctx: Context): List<Device> {
        if (Build.VERSION.SDK_INT >= 31 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
        ) return emptyList()
        val adapter = ctx.getSystemService(BluetoothManager::class.java)?.adapter ?: return emptyList()
        return runCatching {
            adapter.bondedDevices.orEmpty()
                .filter {
                    val major = it.bluetoothClass?.majorDeviceClass
                    major == null || major == BluetoothClass.Device.Major.AUDIO_VIDEO ||
                        major == BluetoothClass.Device.Major.WEARABLE ||
                        major == BluetoothClass.Device.Major.UNCATEGORIZED
                }
                .map { Device(it.address.orEmpty(), it.name.orEmpty()) }
        }.getOrDefault(emptyList())
    }

    /** The registered headphones that are connected now, or null. */
    fun trustedConnected(ctx: Context, trusted: List<Device>): Device? {
        if (trusted.isEmpty()) return null
        val now = connected(ctx)
        return trusted.firstOrNull { t -> now.any { same(t, it) } }
    }

    fun same(a: Device, b: Device): Boolean {
        val aa = a.address.uppercase()
        val bb = b.address.uppercase()
        if (aa.isNotBlank() && aa == bb && !aa.startsWith("XX")) return true
        // Some Android versions hide part of the address ("XX:XX:XX:XX:AB:CD"): then also require the name.
        val namesMatch = a.name.isNotBlank() && a.name.equals(b.name, ignoreCase = true)
        val tailMatch = aa.length >= 5 && bb.length >= 5 && aa.takeLast(5) == bb.takeLast(5)
        return namesMatch && (aa.isBlank() || bb.isBlank() || tailMatch)
    }
}
