"""
Quick TTS Test Script
Run this to test text-to-speech with agents
"""

from tts_module import get_tts, speak_agent

# Test each agent
agents = ["James", "Jasmine", "Elena", "Luca", "Alex", "Sarah", "Diana", "Eve", "Ryan"]

print("=" * 50)
print("TTS Voice Test")
print("=" * 50)
print("Each agent will introduce themselves...")
print()

# Initialize TTS
tts = get_tts()
print(f"Backend: {tts.backend}")
print()

# Test each agent
for name in agents:
    response = f"Hello, I am {name}. I'm ready to discuss the research topic."
    print(f"Testing {name}...")
    speak_agent(name, response)
    input("Press Enter for next agent (Ctrl+C to stop)...")
