package ai.edith.assistant

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Presses WhatsApp's Send button for a message the user just confirmed by voice.
 *
 * Safety:
 * - Android only gives this service WhatsApp's screen (packageNames in res/xml/whatsapp_sender.xml).
 * - It does nothing unless EDITH armed it with the exact confirmed text, and the arm expires after 20 s.
 * - It only presses Send when the message box contains exactly that text.
 */
class WhatsAppSender : AccessibilityService() {

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val text = pendingText ?: return
        if (System.currentTimeMillis() > pendingUntil) {
            disarm()
            EdithState.log("WhatsApp auto-send timed out – the message is typed, tap Send")
            return
        }
        val pkg = event?.packageName?.toString() ?: return
        if (!pkg.startsWith("com.whatsapp")) return
        val root = rootInActiveWindow ?: return
        val entry = root.findAccessibilityNodeInfosByViewId("$pkg:id/entry").firstOrNull() ?: return
        if (!sameText(entry.text?.toString().orEmpty(), text)) return
        val send = root.findAccessibilityNodeInfosByViewId("$pkg:id/send").firstOrNull { it.isEnabled }
            ?: findByDescription(root, "send")
            ?: return
        if (send.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            disarm()
            EdithState.log("WhatsApp: message sent ✓")
        }
    }

    override fun onInterrupt() = Unit

    private fun findByDescription(node: AccessibilityNodeInfo, word: String): AccessibilityNodeInfo? {
        if (node.isClickable && node.isEnabled &&
            node.contentDescription?.toString()?.trim()?.equals(word, ignoreCase = true) == true) return node
        for (i in 0 until node.childCount) {
            node.getChild(i)?.let { findByDescription(it, word)?.let { hit -> return hit } }
        }
        return null
    }

    companion object {
        @Volatile private var pendingText: String? = null
        @Volatile private var pendingUntil = 0L

        fun arm(text: String) {
            pendingText = text
            pendingUntil = System.currentTimeMillis() + 20_000
        }

        fun disarm() {
            pendingText = null
        }

        private fun norm(s: String) = s.replace(Regex("\\s+"), " ").trim().lowercase()
        fun sameText(typed: String, expected: String) = norm(typed) == norm(expected)

        fun isEnabled(ctx: Context): Boolean {
            val enabled = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
                ?: return false
            val cn = ComponentName(ctx, WhatsAppSender::class.java)
            return enabled.split(':').any {
                it.equals(cn.flattenToString(), true) || it.equals(cn.flattenToShortString(), true)
            }
        }
    }
}
