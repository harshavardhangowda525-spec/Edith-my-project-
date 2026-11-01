package ai.edith.assistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContactMatchTest {
    private val book = listOf(
        Triple("Mummy", "+91 90000 00001", false),
        Triple("Papa", "+91 90000 00002", false),
        Triple("Rahul Sharma", "+91 90000 00003", false),
        Triple("Rahul Office", "+91 90000 00004", false),
        Triple("Priya ❤️", "+91 90000 00005", false),
        Triple("Ma Ling", "+91 90000 00006", false),
        Triple("Arjun K", "+91 90000 00007", false),
        Triple("Arjun K", "+91 90000 00008", true), // second number, primary
        Triple("Dr. Mehta Clinic", "+91 90000 00009", false),
    )

    private fun names(spoken: String, rows: List<Triple<String, String, Boolean>> = book) =
        PhoneActions.matchContacts(spoken, rows).map { it.name }

    @Test fun nicknameForMom() = assertEquals(listOf("Mummy"), names("mom"))
    @Test fun myMom() = assertEquals(listOf("Mummy"), names("my mom"))
    @Test fun dad() = assertEquals(listOf("Papa"), names("dad"))
    @Test fun exactFullName() = assertEquals(listOf("Rahul Sharma"), names("rahul sharma"))
    @Test fun ambiguousFirstNameAsksInstead() =
        assertEquals(setOf("Rahul Sharma", "Rahul Office"), names("rahul").toSet())
    @Test fun emojiAndSpelling() = assertEquals(listOf("Priya ❤️"), names("pria"))
    @Test fun partialWords() = assertEquals(listOf("Dr. Mehta Clinic"), names("mehta clinic"))
    @Test fun primaryNumberPreferred() =
        assertEquals("+91 90000 00008", PhoneActions.matchContacts("arjun", book).single().number)
    @Test fun unknownName() = assertTrue(names("zebulon").isEmpty())

    @Test fun momNeverMatchesStrangerStartingWithMa() {
        val noMom = book.filterNot { it.first == "Mummy" }
        assertTrue(names("mom", noMom).isEmpty())
    }

    @Test fun similarity() {
        assertEquals(1.0, PhoneActions.similarity("edith", "edith"), 0.0)
        assertTrue(PhoneActions.similarity("priya", "pria") >= 0.8)
        assertTrue(PhoneActions.similarity("rahul", "mehta") < 0.5)
    }
}
