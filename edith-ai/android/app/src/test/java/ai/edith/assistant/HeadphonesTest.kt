package ai.edith.assistant

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HeadphonesTest {
    private val mine = Headphones.Device("AA:BB:CC:DD:EE:FF", "boAt Airdopes 141")

    @Test fun sameAddress() = assertTrue(Headphones.same(mine, Headphones.Device("aa:bb:cc:dd:ee:ff", "Airdopes")))
    @Test fun otherHeadphones() = assertFalse(Headphones.same(mine, Headphones.Device("11:22:33:44:55:66", "boAt Airdopes 141")))
    @Test fun anonymisedAddressNeedsNameAndTail() {
        assertTrue(Headphones.same(mine, Headphones.Device("XX:XX:XX:XX:EE:FF", "boAt Airdopes 141")))
        assertFalse(Headphones.same(mine, Headphones.Device("XX:XX:XX:XX:EE:FF", "Galaxy Buds")))
        assertFalse(Headphones.same(mine, Headphones.Device("XX:XX:XX:XX:12:34", "boAt Airdopes 141")))
    }
    @Test fun encodeDecode() = assertTrue(Headphones.Device.decode(mine.encode()) == mine)
}
