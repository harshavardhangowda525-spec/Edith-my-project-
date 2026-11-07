package ai.edith.assistant

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WakeOnLanTest {
    @Test fun parsesBothMacFormats() {
        val want = byteArrayOf(0xAA.toByte(), 0xBB.toByte(), 0x0C, 0x1D, 0x2E, 0x3F)
        assertArrayEquals(want, WakeOnLan.parseMac("AA:BB:0C:1D:2E:3F"))
        assertArrayEquals(want, WakeOnLan.parseMac("aa-bb-0c-1d-2e-3f"))
        assertNull(WakeOnLan.parseMac("not a mac"))
    }

    @Test fun magicPacketIsSixFFsThenSixteenCopies() {
        val mac = WakeOnLan.parseMac("01:02:03:04:05:06")!!
        val p = WakeOnLan.magicPacket(mac)
        assertEquals(102, p.size)
        for (i in 0 until 6) assertEquals(0xFF.toByte(), p[i])
        for (k in 0 until 16) assertArrayEquals(mac, p.copyOfRange(6 + k * 6, 12 + k * 6))
    }

    @Test fun directedBroadcastForHomeWifi() {
        val b = WakeOnLan.directedBroadcast(byteArrayOf(192.toByte(), 168.toByte(), 1, 37), 24)
        assertArrayEquals(byteArrayOf(192.toByte(), 168.toByte(), 1, 255.toByte()), b)
        val c = WakeOnLan.directedBroadcast(byteArrayOf(10, 0, 5, 9), 16)
        assertArrayEquals(byteArrayOf(10, 0, 255.toByte(), 255.toByte()), c)
    }
}
