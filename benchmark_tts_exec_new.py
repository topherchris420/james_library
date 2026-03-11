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
        with open('afplay', 'w') as f:
            f.write('#!/bin/sh\nsleep 0.5\n')
        os.chmod('afplay', 0o755)
        # add to path
        os.environ['PATH'] = os.path.abspath('.') + os.pathsep + os.environ['PATH']

    engine = tts_module.TTSEngine(backend="edge-tts")

    durations = []
    lags = []
    for _ in range(5):
        duration, max_lag = await measure_event_loop_lag(engine)
        durations.append(duration)
        lags.append(max_lag)

    print(f"Current Implementation (Async)")
    print(f"Average execution time: {sum(durations)/len(durations):.4f}s")
    print(f"Average max event loop lag: {sum(lags)/len(lags):.4f}s")

    if os.name != 'nt':
        os.remove('afplay')

if __name__ == "__main__":
    asyncio.run(main())
