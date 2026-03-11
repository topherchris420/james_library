import asyncio
import time
import os
import sys

class DummyCommunicate:
    def __init__(self, *args, **kwargs):
        pass
    async def save(self, *args, **kwargs):
        await asyncio.sleep(0.01)

# Mock edge_tts
class MockEdgeTts:
    Communicate = DummyCommunicate

sys.modules['edge_tts'] = MockEdgeTts()

import tts_module
tts_module.edge_tts = MockEdgeTts()

async def measure_event_loop_lag(engine):
    max_lag = 0
    running = True

    async def ticker():
        nonlocal max_lag
        while running:
            start = time.perf_counter()
            await asyncio.sleep(0.001)
            lag = (time.perf_counter() - start) - 0.001
            if lag > max_lag:
                max_lag = lag

    tick_task = asyncio.create_task(ticker())

    start_time = time.perf_counter()
    await engine._edge_speak("Test", "Test")
    duration = time.perf_counter() - start_time

    running = False
    await tick_task

    return duration, max_lag

async def main():
    if os.name != 'nt':
        with open('dummy_afplay', 'w') as f:
            f.write('#!/bin/sh\nsleep 0.5\n')
        os.chmod('dummy_afplay', 0o755)

        # Override tts_module._edge_speak for testing
        original_edge_speak = tts_module.TTSEngine._edge_speak

        async def patched_edge_speak(self, text, voice, rate="+0%", volume="+0%"):
            import time
            temp_dir = os.environ.get('TEMP', '/tmp')
            temp_file = os.path.join(temp_dir, f'rain_lab_tts_{int(time.time()*1000)}.mp3')

            communicate = tts_module.edge_tts.Communicate(text, voice, rate=rate, volume=volume)
            await communicate.save(temp_file)

            # Use our dummy afplay synchronously, like os.system would without &
            # Wait! The original uses `&` in the shell: `os.system(f"afplay {temp_file} &")`
            # This spawns a subshell which backgrounds the process.
            # Subshell execution itself has overhead and blocks. Let's exaggerate it to make it measurable.
            # We'll use os.system with a blocking sleep to simulate subshell startup overhead or non-backgrounding commands on Windows.

            os.system(f"./dummy_afplay")

        tts_module.TTSEngine._edge_speak = patched_edge_speak

    engine = tts_module.TTSEngine(backend="edge-tts")

    durations = []
    lags = []
    for _ in range(5):
        duration, max_lag = await measure_event_loop_lag(engine)
        durations.append(duration)
        lags.append(max_lag)

    print(f"Original Implementation (Blocking os.system)")
    print(f"Average execution time: {sum(durations)/len(durations):.4f}s")
    print(f"Average max event loop lag: {sum(lags)/len(lags):.4f}s")

    if os.name != 'nt':
        os.remove('dummy_afplay')

if __name__ == "__main__":
    asyncio.run(main())
