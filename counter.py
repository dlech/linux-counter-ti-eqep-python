#!/usr/bin/env python3


import contextlib
from ctypes import c_uint8, c_uint64, Structure, sizeof
from enum import IntEnum
from fcntl import F_SETFL, fcntl, ioctl
from os import O_NONBLOCK
from typing import Callable, Dict, List, Optional, Tuple


class CounterComponentType(IntEnum):
    NONE = 0
    SIGNAL = 1
    COUNT = 2
    FUNCTION = 3
    SYNAPSE_ACTION = 4
    EXTENSION = 5


class CounterScope(IntEnum):
    DEVICE = 0
    SIGNAL = 1
    COUNT = 2


class CounterComponent(Structure):
    _fields_ = [
        ("type", c_uint8),
        ("scope", c_uint8),
        ("parent", c_uint8),
        ("id", c_uint8),
    ]

    def __repr__(self):
        return f"CounterComponent(type={CounterComponentType(self.type).name}, scope={CounterScope(self.scope).name}, parent={self.parent}, id={self.id})"


class CounterEventType(IntEnum):
    OVERFLOW = 0
    UNDERFLOW = 1
    OVERFLOW_UNDERFLOW = 2
    THRESHOLD = 3
    INDEX = 4
    DIRECTION_CHANGE = 5
    TIMEOUT = 6


class CounterWatch(Structure):
    _fields_ = [
        ("component", CounterComponent),
        ("event", c_uint8),
        ("channel", c_uint8),
    ]

    def __repr__(self):
        return f"CounterWatch(component={self.component}, event={CounterEventType(self.event).name}, channel={self.channel})"


_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2
_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(direction, request_type, request_nr, size):
    _IOC_NRSHIFT = 0
    _IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
    _IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
    _IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
    return (
        (direction << _IOC_DIRSHIFT)
        | (request_type << _IOC_TYPESHIFT)
        | (request_nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


COUNTER_ADD_WATCH_IOCTL = _IOC(_IOC_WRITE, 0x3E, 0x00, sizeof(CounterWatch))
COUNTER_ENABLE_EVENTS_IOCTL = _IOC(_IOC_NONE, 0x3E, 0x01, 0)
COUNTER_DISABLE_EVENTS_IOCTL = _IOC(_IOC_NONE, 0x3E, 0x02, 0)


class CounterEvent(Structure):
    _fields_ = [
        ("timestamp", c_uint64),
        ("value", c_uint64),
        ("watch", CounterWatch),
        ("status", c_uint8),
    ]

    @property
    def event_type(self) -> CounterEventType:
        return CounterEventType(self.watch.event)

    def __repr__(self):
        return f"CounterEvent(watch={self.watch}, timestamp={self.timestamp}, value={self.value}, status={self.status})"


class CounterCountDirection(IntEnum):
    FORWARD = 0
    BACKWARD = 1


class CounterCountMode(IntEnum):
    NORMAL = 0
    RANGE_LIMIT = 1
    NON_RECYCLE = 2
    MODULO_N = 3


class CounterFunction(IntEnum):
    INCREASE = 0
    DECREASE = 1
    PULSE_DIRECTION = 2
    QUADRATURE_X1_A = 3
    QUADRATURE_X1_B = 4
    QUADRATURE_X2_A = 5
    QUADRATURE_X2_B = 6
    QUADRATURE_X4 = 7


class CounterSignalLevel(IntEnum):
    LOW = 0
    HIGH = 1


class CounterSynapseAction(IntEnum):
    NONE = 0
    RISING_EDGE = 1
    FALLING_EDGE = 2
    BOTH_EDGES = 3

_DEFAULT_FUNCTION = "quadrature x4"
_DEFAULT_CEILING = (1 << 32) - 1

class Count:
    def __init__(self, counter, id, function=_DEFAULT_FUNCTION, ceiling=_DEFAULT_CEILING, count=None):
        self._sysfs = f"{counter._sysfs}/count{str(id)}"

        # sysfs could be in any state, so set everything to a known state
        self.enable = False
        self.ceiling = ceiling
        self.function = function

        if count is not None:
            self.count = count

    @property
    def count(self) -> int:
        with open(self._sysfs + "/count") as f:
            return int(f.read())
        
    @count.setter
    def count(self, value: int):
        with open(self._sysfs + "/count", "w") as f:
            f.write(str(value))

    @property
    def ceiling(self) -> int:
        with open(self._sysfs + "/ceiling") as f:
            return int(f.read())

    @ceiling.setter
    def ceiling(self, value: int):
        with open(self._sysfs + "/ceiling", "w") as f:
            f.write(str(value))

    @property
    def ceiling_component_id(self) -> int:
        with open(self._sysfs + "/ceiling_component_id") as f:
            return int(f.read())

    @property
    def enable(self) -> bool:
        with open(self._sysfs + "/enable") as f:
            return bool(int(f.read()))

    @enable.setter
    def enable(self, value: bool):
        with open(self._sysfs + "/enable", "w") as f:
            f.write(str(int(bool(value))))

    @property
    def function(self) -> str:
        with open(self._sysfs + "/function") as f:
            return f.read().strip()

    @function.setter
    def function(self, value: str):
        with open(self._sysfs + "/function", "w") as f:
            f.write(str(value))

    @property
    def function_available(self) -> List[str]:
        with open(self._sysfs + "/function_available") as f:
            return [line.strip() for line in f.readlines()]

    @property
    def name(self) -> str:
        with open(self._sysfs + "/name") as f:
            return f.read().strip()


class Signal:
    def __init__(self, counter, id):
        self._sysfs = f"{counter._sysfs}/signal{str(id)}"

    @property
    def name(self) -> str:
        with open(self._sysfs + "/name") as f:
            return f.read().strip()


class Counter:
    def __init__(self, id=0, function=_DEFAULT_FUNCTION, ceiling=_DEFAULT_CEILING, count=None):
        self._sysfs = "/sys/bus/counter/devices/counter" + str(id)
        self._dev = "/dev/counter" + str(id)

        with open(self._sysfs + "/num_counts") as f:
            self._num_counts = int(f.read())

        self._counts = {}

        for count_id in range(self._num_counts):
            self._counts[count_id] = Count(self, count_id, function, ceiling, count)

        with open(self._sysfs + "/num_signals") as f:
            self._num_signals = int(f.read())

        self._signals = {}

        for signal_id in range(self._num_signals):
            self._signals[signal_id] = Signal(self, signal_id)

    @property
    def count(self) -> Dict[int, Count]:
        return self._counts

    @property
    def signal(self) -> Dict[int, Signal]:
        return self._signals

    def subscribe_events(
        self, watches: List[CounterWatch]
    ) -> Tuple[Callable[[], None], Callable[[], Optional[CounterEvent]]]:
        """
        Subscribes to counter events.

        Parameters:
            watches: a list of CounterWatch objects to watch for

        Returns:
            A tuple of two functions. The first function unsubscribes from the
            events. The second function reads an event.
        """
        with contextlib.ExitStack() as stack:
            f = stack.enter_context(open(self._dev, "rb"))

            fcntl(f, F_SETFL, O_NONBLOCK)

            for watch in watches:
                ioctl(f, COUNTER_ADD_WATCH_IOCTL, watch)

            ioctl(f, COUNTER_ENABLE_EVENTS_IOCTL)
            stack.callback(ioctl, f, COUNTER_DISABLE_EVENTS_IOCTL)

            def read_event():
                data = f.read(sizeof(CounterEvent))

                if data is None:
                    return None

                return CounterEvent.from_buffer_copy(data)

            return stack.pop_all().close, read_event
