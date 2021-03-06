# The MIT License (MIT)
#
# Copyright (c) 2020 Scott Shawcroft for Adafruit Industries LLC
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_ble_midi`
================================================================================

BLE MIDI service for CircuitPython

"""

import time

import _bleio

from adafruit_ble.attributes import Attribute
from adafruit_ble.characteristics import Characteristic, ComplexCharacteristic
from adafruit_ble.uuid import VendorUUID
from adafruit_ble.services import Service

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_BLE_MIDI.git"

class _MidiCharacteristic(ComplexCharacteristic):
    """Endpoint for sending commands to a media player. The value read will list all available

       commands."""
    uuid = VendorUUID("7772E5DB-3868-4112-A1A9-F2669D106BF3")

    def __init__(self):
        super().__init__(properties=Characteristic.WRITE_NO_RESPONSE | Characteristic.READ | Characteristic.NOTIFY,
                         read_perm=Attribute.OPEN, write_perm=Attribute.OPEN,
                         max_length=512,
                         fixed_length=False)

    def bind(self, service):
        """Binds the characteristic to the given Service."""
        bound_characteristic = super().bind(service)
        return _bleio.PacketBuffer(bound_characteristic,
                                   buffer_size=4)

class MIDIService(Service):
    uuid = VendorUUID("03B80E5A-EDE8-4B33-A751-6CE34EC4C700")
    _raw = _MidiCharacteristic()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._in_buffer = bytearray(self._raw.packet_length)
        self._out_buffer = None
        shared_buffer = memoryview(bytearray(4))
        self._buffers = [None, shared_buffer[:1], shared_buffer[:2], shared_buffer[:3], shared_buffer[:4]]
        self._header = bytearray(1)
        self._in_sysex = False
        self._message_target_length = None
        self._message_length = 0
        self._pending_realtime = None

    def read(self, length):
        self._raw.read(self._in_buffer)
        return None

    def write(self, buf, length):
        timestamp_ms = time.monotonic_ns() // 1000000
        self._header[0] = (timestamp_ms >> 7 & 0x3f) | 0x80
        i = 0
        while i < length:
            data = buf[i]
            command = data & 0x80 != 0
            if self._in_sysex:
                if command: # End of sysex or real time
                    b = self._buffers[2]
                    b[0] = 0x80 | (timestamp_ms & 0x7f)
                    b[1] = 0xf7
                    self._raw.write(b, self._header)
                    self._in_sysex = data == 0xf7
                else:
                    b = self._buffers[1]
                    b[0] = data
                    self._raw.write(b, self._header)
            elif command:
                self._in_sysex = data == 0xf0
                b = self._buffers[2]
                b[0] = 0x80 | (timestamp_ms & 0x7f)
                b[1] = data
                if 0xf6 <= data <= 0xff or self._in_sysex: # Real time, command only or start sysex
                    if self._message_target_length:
                        self._pending_realtime = b
                    else:
                        self._raw.write(b, self._header)
                else:
                    if 0x80 <= data <= 0xbf or 0xe0 <= data <= 0xef or data == 0xf2: # Two following bytes
                        self._message_target_length = 4
                    else:
                        self._message_target_length = 3
                    b = self._buffers[self._message_target_length]
                    # All of the buffers share memory so the timestamp and data have already been set.
                    self._message_length = 2
                    self._out_buffer = b
            else:
                self._out_buffer[self._message_length] = data
                self._message_length += 1
                if self._message_target_length == self._message_length:
                    self._raw.write(self._out_buffer, self._header)
                    if _pending_realtime:
                        self._raw.write(self._pending_realtime, self._header)
                        self._pending_realtime = None
                    self._message_target_length = None
