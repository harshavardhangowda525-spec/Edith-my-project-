package ai.edith.assistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MessagingTest {
    @Test fun withPlus() = assertEquals("919845012345", PhoneActions.intlNumber("+91 98450 12345", "91"))
    @Test fun withLeadingZero() = assertEquals("919845012345", PhoneActions.intlNumber("098450-12345", "91"))
    @Test fun tenDigits() = assertEquals("919845012345", PhoneActions.intlNumber("98450 12345", "91"))
    @Test fun alreadyHasCc() = assertEquals("919845012345", PhoneActions.intlNumber("919845012345", "91"))
    @Test fun doubleZero() = assertEquals("447700900123", PhoneActions.intlNumber("00 44 7700 900123", "91"))
    @Test fun noCountryCodeKnown() = assertNull(PhoneActions.intlNumber("98450 12345", ""))
    @Test fun usNumber() = assertEquals("14155550123", PhoneActions.intlNumber("(415) 555-0123", "1"))

    @Test fun sendOnlyExactText() {
        assertTrue(WhatsAppSender.sameText("I'll be late  by 10 minutes.", "i'll be late by 10 minutes."))
        assertFalse(WhatsAppSender.sameText("I'll be late", "I'll be late by 10 minutes."))
        assertFalse(WhatsAppSender.sameText("", "hi"))
    }
}
