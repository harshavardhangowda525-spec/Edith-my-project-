package ai.edith.assistant

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.util.Log

/**
 * Routes the microphone to a connected Bluetooth headset (HFP/SCO) when possible.
 *
 * Bluetooth headphones only send microphone audio in "call mode" (SCO). While it is on,
 * music on the headphones sounds like a phone call and the headphones' battery drains faster.
 * That is a Bluetooth limitation. Choose "Phone microphone" in the app to avoid it.
 */
class AudioRouting(context: Context) {
    private val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var usingSco = false
    private var previousMode = AudioManager.MODE_NORMAL

    /** Tries to switch input to the headset mic. Returns the input device to prefer, or null (phone mic). */
    fun useHeadsetMic(): AudioDeviceInfo? {
        val input = am.getDevices(AudioManager.GET_DEVICES_INPUTS)
            .firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO } ?: return null
        try {
            previousMode = am.mode
            am.mode = AudioManager.MODE_IN_COMMUNICATION
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val out = am.availableCommunicationDevices
                    .firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO } ?: return null
                if (!am.setCommunicationDevice(out)) return null
            } else {
                @Suppress("DEPRECATION")
                am.startBluetoothSco()
                @Suppress("DEPRECATION")
                am.isBluetoothScoOn = true
            }
            usingSco = true
            return input
        } catch (e: SecurityException) {
            Log.w(TAG, "No permission to use the Bluetooth microphone", e)
        } catch (e: Exception) {
            Log.w(TAG, "Could not switch to the Bluetooth microphone", e)
        }
        release()
        return null
    }

    val headsetActive: Boolean get() = usingSco

    fun release() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                am.clearCommunicationDevice()
            } else {
                @Suppress("DEPRECATION")
                am.isBluetoothScoOn = false
                @Suppress("DEPRECATION")
                am.stopBluetoothSco()
            }
            am.mode = previousMode
        } catch (e: Exception) {
            Log.w(TAG, "Audio routing release failed", e)
        }
        usingSco = false
    }

    companion object { private const val TAG = "EdithAudio" }
}
