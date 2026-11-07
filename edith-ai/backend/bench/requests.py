"""106 representative requests for the EDITH benchmark."""
SIMPLE = [
    "Hello Edith", "Hi, I'm back", "Good morning", "Thanks Edith", "How are you?", "What's 12 times 8?",
    "What is the capital of Japan?", "Who wrote Hamlet?", "How many days are in a leap year?",
    "Tell me a joke", "What's the boiling point of water?", "Convert 10 km to miles",
    "What does HTML stand for?", "What is an API?", "Spell necessary", "What is Git?",
    "What's the opposite of hot?", "Define latency", "What is a database?", "What's 15 percent of 200?",
    "Who is the CEO of Tesla?", "What is Python?", "What day comes after Friday?", "What is RAM?",
    "Is the sun a star?", "What is JSON?", "Translate hello to Hindi", "What is 2 to the power 10?",
    "What is a pixel?", "Name three primary colours", "What is Flutter?", "What's a URL?",
    "Good night Edith", "What is HTTP?", "How many continents are there?", "What is React?",
    "What's 99 plus 1?", "What is the speed of light?", "What is cloud computing?", "Say something funny",
]
CODING = [
    "Explain Python decorators with an example", "How do I reverse a list in Python?",
    "Why does my Flutter app say setState called after dispose?", "Explain React useEffect cleanup",
    "How do I fix 'TypeError: Cannot read properties of undefined' in JavaScript?",
    "Write a SQL query to get the top 5 customers by revenue", "Explain async and await in Dart",
    "What is the difference between let, const and var?", "How do I set up Supabase auth in Next.js?",
    "Debug: ModuleNotFoundError: No module named 'requests'", "Explain Git rebase vs merge",
    "How do I deploy a Next.js app to Vercel?", "Explain Docker volumes", "How do I write a pytest fixture?",
    "Why is my Node.js server not reading environment variables?", "Explain Firebase Firestore security rules",
    "How do I paginate a REST API?", "What is a race condition and how do I prevent it?",
    "Explain the Flutter widget lifecycle", "How do I optimize a slow React list?",
    "Write a Python function that validates an email address", "Explain CORS errors and how to fix them",
    "How do I use environment variables in Flutter?", "What's the difference between SQL and NoSQL?",
    "Explain JWT authentication", "How do I handle errors in async JavaScript?",
    "Design a scalable architecture for a chat application with millions of users and explain trade-offs",
    "Analyze the time complexity of quicksort and when it degrades, step by step",
    "Refactor a 2000-line React component into a maintainable architecture; give a detailed plan",
    "Debug a memory leak in a Node.js service that grows 50MB per hour; walk through a full investigation",
    "Explain how to design a multi-tenant SaaS database schema with row-level security in depth",
    "Compare microservices and a modular monolith for a 5-person startup in detail",
    "How do I write a GitHub Actions workflow that runs tests?", "Explain Kubernetes pods vs deployments",
    "How do I mock an HTTP call in pytest?", "Explain state management options in Flutter",
    "What is dependency injection?", "Explain AWS Lambda cold starts", "How do I profile a Python script?",
    "Explain the event loop in JavaScript",
]
COMMANDS = [
    "Call mom", "Open Spotify and play my favourite music", "Pause", "Next song", "Set an alarm for 6 AM",
    "Set a timer for 10 minutes", "Navigate to the airport", "Open Instagram", "WhatsApp Rahul saying I'm late",
    "Take a note: buy milk", "Volume up", "Open WhatsApp", "Find me leads for dentists in Indiranagar",
    "Email Priya saying the proposal is ready", "Play Kesariya by Arijit Singh", "Type hello how are you",
    "Previous track", "Open notes and type", "Send a message to Mom", "Call Rahul Sharma",
]
VOICE = ["voice"] * 6

ALL = [("simple", t) for t in SIMPLE] + [("coding", t) for t in CODING] + [("command", t) for t in COMMANDS] + \
      [("voice", t) for t in VOICE]
assert len(ALL) >= 100, len(ALL)
