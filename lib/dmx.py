import threading
import time

from helpers import monotonic_time

DMX_MIN_VALUE = 0
DMX_MAX_VALUE = 255

DMX_MIN_CHANNEL = 1
DMX_MAX_CHANNEL = 256


class DmxModificationRunner(threading.Thread):
    def __init__(self, controller, modification, interval=0.1):
        self.controller = controller
        self.modification = modification
        self.interval = interval

        self.calculate_values()

        super(DmxModificationRunner, self).__init__()

    def monotonic_clock(self):
        return monotonic_time()

    def step(self):
        # calculate next step
        time_now = self.monotonic_clock()
        time_relative = min(time_now - self.started, self.duration) # cap this to the duration

        step_channels = self.step_at(time_relative)
        print time_relative, step_channels
        self.controller.set_channels(step_channels)

        return time_relative >= self.duration

    def run(self):
        self.started = self.monotonic_clock()
        while True:
            if self.step():
                break
            time.sleep(self.interval)

    def calculate_values(self):
        # calculate values
        tv = dict(self.modification.time_values)
        time_stops = list(sorted(tv.keys()))
        chans = set(self.modification.using_channels)

        self.time_values = tv
        self.channels = chans
        self.time_stops = time_stops
        self.duration = max(time_stops)

        channel_time_stops = {}
        for ch in self.channels:
            channel_time_stops[ch] = [time_stop for time_stop in time_stops if ch in tv[time_stop].keys()]
        self.channel_time_stops = channel_time_stops

    def calculate_easing(self, easing_type, percentage, last_val, next_val):
        if easing_type == "linear":
            return last_val + ((next_val - last_val) * percentage)
        elif easing_type == "sudden":
            # to use this easing type, you should put a stop 0.1 second before this
            # with the LAST value
            # then for the "FLASH" value, apply easing="sudden"
            return next_val if percentage > 0.9 else last_val
        raise ValueError("Unknown easing type %r" % (easing_type,))

    def step_at(self, t):
        output = {}
        for ch in self.channels:
            try:
                chts = self.channel_time_stops[ch]

                # find the last time that the value was specified
                last_time = max([ts for ts in chts if ts < t])
                last_value = self.time_values[last_time][ch]
                # and the next time
                next_time = min([ts for ts in chts if ts >= t])
                next_value = self.time_values[next_time][ch]

                # now what percentage of the way we are through it
                fade_duration = float(next_time - last_time)
                fade_progress = float(t - last_time)
                fade_percentage = fade_progress / fade_duration

                new_value = self.calculate_easing(next_value["easing"], fade_percentage, last_value['value'], next_value['value'])
                output[ch] = int(round(new_value))
            except ValueError:
                pass
                # probably means that there's no "next time" or "last time"
                # so we should STOP FIDDLING WITH IT
        return output




class DmxModification(object):
    def __init__(self, controller=None):
        self.controller = controller  # this should ONLY be used in .execute as convenient shorthand - not required

        self.locked = False
        
        self.using_channels = set()
        self.time_values = {}

    def execute(self):
        """Shorthand for BaseDmxController.execute_change"""
        assert self.controller
        self.controller.execute_change(self)

    def set_value(self, time, channel, value, easing="linear"):
        assert not self.locked

        self.using_channels.add(channel)
        pointdict = self.time_values.setdefault(time, {}).setdefault(channel, {})
        pointdict["value"] = value
        pointdict["easing"] = easing
        # space for future expansion - could stick an easing function in that dict

    def lock(self):
        assert not self.locked
        self.locked = True




class BaseDmxController(object):
    """Base class describing a generic DMX controller API"""

    def __init__(self, starting_values=None):
        self.min_value = DMX_MIN_VALUE
        self.max_value = DMX_MAX_VALUE

        self.min_channel = DMX_MIN_CHANNEL
        self.max_channel = DMX_MAX_CHANNEL

        self.has_started = False

        if starting_values is not None:
            self.set_channels(starting_values)

    def is_valid_channel(self, channel_id):
        return self.min_channel <= channel_id <= self.max_channel

    def is_valid_value(self, set_to):
        return self.min_value <= set_to <= self.max_value

    def validate_channel(self, channel_id):
        if not self.is_valid_channel(channel_id):
            raise ValueError("Channel ID '%r' out of range" % (channel_id,))

    def validate_value(self, set_to):
        if not self.is_valid_value(set_to):
            raise ValueError("DMX value '%r' out of range" % (set_to,))

    def validate_channel_and_value(self, channel_id, set_to):
        self.validate_channel(channel_id)
        self.validate_value(set_to)


    def set_channel(self, channel_id, set_to):
        self.validate_channel_and_value(channel_id, set_to)
        self._set_channels({
            channel_id: set_to
        })

    def set_channels(self, channels):
        channel_set = {}
        for channel, value in channels.iteritems():
            self.validate_channel_and_value(channel, value)
            channel_set[channel] = value
        self._set_channels(channel_set)

    def get_channel(self, channel_id):
        self.validate_channel(channel_id)
        return self._get_channels([channel_id])[channel_id]

    def get_channels(self, channels):
        channel_check = []
        for channel in channels:
            self.validate_channel(channel)
            channel_check.append(channel)

        return self._get_channels(channel_check)

    def new_change(self):
        return DmxModification(self)

    def execute_change(self, modification):
        modification.lock()
        modification.runner = DmxModificationRunner(self, modification)
        modification.runner.start()


    def start(self, *args, **kwargs):
        if self.has_started:
            raise RuntimeError("Cannot 'start' multiple times")

        self._start(*args, **kwargs)
        self.has_started = True

    def stop(self, *args, **kwargs):
        if not self.has_started:
            raise RuntimeError("Not started")

        self._stop(*args, **kwargs)
        self.has_started = False


    def _set_channels(self, channel_set):
        raise NotImplementedError("Subclasses should override this method and implement it")

    def _get_channels(self, channel_set):
        raise NotImplementedError("Subclasses should override this method and implement it")

    def _start(self):
        # implement if necessary
        pass

    def _stop(self):
        # implement if necessary
        pass

class ManolatorDmxController(BaseDmxController):
    def __init__(self, parallel, default_value=0, *args, **kwargs):
        self.live_channels = dict((c, None) for c in range(DMX_MIN_CHANNEL, DMX_MAX_CHANNEL))
        self.live_channels_lock = threading.Lock()

        self.channel_default_value = default_value

        self.parallel = parallel
        self.parallel_keep_going = False

        self.sleep_in_send = False

        super(ManolatorDmxController, self).__init__(*args, **kwargs)

    def _start(self):
        self.parallel_keep_going = True
        self.parallel_update_thread = threading.Thread(
            target=self._perform_parallel_update,
            args=(self.parallel,),
            name="Manolator-Parallel-Thread"
        )
        self.parallel_ending_event = threading.Event()
        self.parallel_update_thread.start()

    def _stop(self):
        assert self.parallel_update_thread.is_alive()

        self.parallel_keep_going = False
        if not self.parallel_ending_event.wait(5):
            raise RuntimeError("Parallel update thread has stalled!")

    def _perform_parallel_update(self, p):
        # pySerial parallel in p
        try:
            while self.parallel_keep_going:
                p.setData(0)
                p.setAutoFeed(1)
                time.sleep(0.1)
                p.setAutoFeed(0)
                for channel in range(self.min_channel, self.max_channel):
                    val = self.live_channels[channel]
                    p.setData(self.channel_default_value if val is None else val)
                    p.setDataStrobe(1)
                    self.sleep_in_send and time.sleep(0.01)  # Not usually necessary
                    p.setDataStrobe(0)
                    self.sleep_in_send and time.sleep(0.01)  # Not usually necessary
                    p.setData(0)

                # now take a nap
                time.sleep(0.1)
        finally:
            self.parallel_keep_going = False
            self.parallel_ending_event.set()


    def _set_channels(self, channel_set):
        if self.has_started and not self.parallel_keep_going:
            raise RuntimeError("Parallel port has died!")

        with self.live_channels_lock:
            for channel, value in channel_set.iteritems():
                self.live_channels[channel] = value

    def _get_channels(self, channel_set):
        if self.has_started and not self.parallel_keep_going:
            raise RuntimeError("Parallel port has died!")

        output = {}
        with self.live_channels_lock:
            for channel in channel_set:
                output[channel] = self.live_channels[channel]
                if output[channel] is None:
                    raise ValueError("Cannot read channel '%r' - has not been previously set" % (channel,))

        return output

class DummyDmxController(BaseDmxController):
    def _set_channels(self, channel_set):
        print time.time(), "Setting channels:", channel_set

    def _get_channels(self, channel_set):
        return dict([(ch, 0) for ch in channel_set])
