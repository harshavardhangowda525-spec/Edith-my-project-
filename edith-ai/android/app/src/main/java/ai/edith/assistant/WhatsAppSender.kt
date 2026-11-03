package ai.edith.assistant

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Full edition only: lets EDITH type what you dictated into the open app's text box and press its
 * Send button after you say "yes". (Class name kept for compatibility with existing settings.)
 *
 * Safety:
 * - It never acts on its own: only right after you dictate something to EDITH.
 * - It never types into password fields and never reads, stores or uploads screen content.
 * - WhatsApp auto-send presses Send only when the box holds exactly the text you confirmed (20 s window).
 */
class WhatsAppSender : AccessibilityService() {

    override fun onServiceConnected() {
        instance = this
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

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
            ?: findSend(root)
            ?: return
        if (send.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            disarm()
            EdithState.log("WhatsApp: message sent ✓")
        }
    }

    override fun onInterrupt() = Unit

    // ------------------------------------------------------------------ typing in any app

    /** Package of the app on screen now. */
    fun foregroundPackage(): String? = rootInActiveWindow?.packageName?.toString()

    /** The focused (or first visible) editable text box, never a password field. */
    private fun inputBox(): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        val node = if (focused?.isEditable == true) focused else firstEditable(root)
        return node?.takeIf { !it.isPassword }
    }

    fun hasInputBox(): Boolean = inputBox() != null

    /** Types [text] into the open app's text box (after anything already typed). */
    fun typeIntoFocused(text: String): Boolean {
        val node = inputBox() ?: return false
        val showingHint = Build.VERSION.SDK_INT >= 26 && node.isShowingHintText
        val existing = if (showingHint) "" else node.text?.toString().orEmpty()
        val newText = if (existing.isBlank()) text else existing.trimEnd() + " " + text
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, newText)
        }
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    fun hasSendButton(): Boolean = rootInActiveWindow?.let { findSend(it) } != null

    fun pressSend(): Boolean {
        val root = rootInActiveWindow ?: return false
        val pkg = root.packageName?.toString().orEmpty()
        val byId = root.findAccessibilityNodeInfosByViewId("$pkg:id/send").firstOrNull { it.isEnabled }
        return (byId ?: findSend(root))?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
    }

    private fun firstEditable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isEditable && node.isVisibleToUser) return node
        for (i in 0 until node.childCount) node.getChild(i)?.let { firstEditable(it)?.let { hit -> return hit } }
        return null
    }

    /** A clickable "Send" control: by label/description, or a view id containing "send". */
    private fun findSend(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val label = (node.contentDescription ?: node.text)?.toString()?.trim()?.lowercase().orEmpty()
        val id = node.viewIdResourceName?.lowercase().orEmpty()
        val looksLikeSend = label == "send" || label == "send message" || label.startsWith("send ") ||
            id.endsWith("/send") || id.contains("send_button") || id.contains("composer_send")
        if (looksLikeSend && node.isEnabled && node.isVisibleToUser) {
            if (node.isClickable) return node
            var p = node.parent
            while (p != null) {
                if (p.isClickable) return p
                p = p.parent
            }
        }
        for (i in 0 until node.childCount) node.getChild(i)?.let { findSend(it)?.let { hit -> return hit } }
        return null
    }

    companion object {
        @Volatile var instance: WhatsAppSender? = null
            private set
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

        /** Full edition and the user switched the service on. */
        fun ready(ctx: Context) = BuildConfig.WHATSAPP_AUTO_SEND && isEnabled(ctx) && instance != null

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
