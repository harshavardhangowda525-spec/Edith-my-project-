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

class ContactChoiceTest {
    private val book = listOf(
        Triple("Mom", "+91 90000 00010", false),
        Triple("Mummy", "+91 90000 00011", false),
        Triple("Mom Jio", "+91 90000 00012", false),
    )

    @Test fun exactSavedNameBeatsNickname() =
        assertEquals(listOf("Mom"), PhoneActions.matchContacts("mom", book).map { it.name })

    @Test fun nicknameStillWorksWhenNoExact() =
        assertEquals(listOf("Mummy"), PhoneActions.matchContacts("mom", book.filter { it.first != "Mom" }).map { it.name })

    private val options = listOf("Mom Jio", "Mom Airtel", "Mummy")
    @Test fun ordinals() {
        assertEquals(0, PhoneActions.parseChoice("the first one", options))
        assertEquals(1, PhoneActions.parseChoice("second", options))
        assertEquals(1, PhoneActions.parseChoice("no, the second one", options))
        assertEquals(2, PhoneActions.parseChoice("last one", options))
        assertEquals(2, PhoneActions.parseChoice("3", options))
    }
    @Test fun byName() {
        assertEquals(0, PhoneActions.parseChoice("Jio", options))
        assertEquals(1, PhoneActions.parseChoice("call mom airtel", options))
        assertEquals(2, PhoneActions.parseChoice("mummy", options))
        assertEquals(1, PhoneActions.parseChoice("airtell", options)) // small mishearing
    }
    @Test fun unclear() {
        assertEquals(null, PhoneActions.parseChoice("mom", options))   // matches two
        assertEquals(null, PhoneActions.parseChoice("hmm", options))
        assertEquals(null, PhoneActions.parseChoice("tenth", options))
    }
}
