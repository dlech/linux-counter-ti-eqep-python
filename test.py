import contextlib
import time

from counter import (
    Counter,
    CounterWatch,
    CounterEventType,
)

_LOOP_DELAY_SEC = 0.5
_COUNTER_ID = 2

with contextlib.ExitStack() as stack:
    # we have a motor where one count is exactly one degree
    c = Counter(_COUNTER_ID, ceiling=359, count=0)

    print("count0/ceiling:", c.count[0].ceiling)
    print("count0/enable:", c.count[0].enable)
    print("count0/function:", c.count[0].function)
    print("count0/function_available:", c.count[0].function_available)
    print("count0/name:", c.count[0].name)

    print("signal0/name:", c.signal[0].name)
    print("signal1/name:", c.signal[1].name)

    overflow = CounterWatch(event=CounterEventType.OVERFLOW)
    underflow = CounterWatch(event=CounterEventType.UNDERFLOW)

    unsubscribe, read_event = c.subscribe_events([overflow, underflow])
    stack.callback(unsubscribe)

    rotations = 0

    c.count[0].enable = True
    stack.callback(setattr, c.count[0], "enable", False)

    while True:
        print("rotations count:", rotations, c.count[0].count)

        while True:
            event = read_event()
            
            if event is None:
                break

            if event.event_type == CounterEventType.OVERFLOW:
                rotations += 1
            elif event.event_type == CounterEventType.UNDERFLOW:
                rotations -= 1

        time.sleep(_LOOP_DELAY_SEC)
