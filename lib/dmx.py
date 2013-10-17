import threading
import time

DMX_MIN_VALUE = 0
DMX_MAX_VALUE = 255

DMX_MIN_CHANNEL = 1
DMX_MAX_CHANNEL = 256

class BaseDmxController(object):
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

    def start(self, *args, **kwargs):
        if self.has_started:
            raise RuntimeError("Cannot 'start' multiple times")

        self._start(*args, **kwargs)
        self.has_started = True


    def _set_channels(self, channel_set):
        raise NotImplementedError("Subclasses should override this method and implement it")

    def _get_channels(self, channel_set):
        raise NotImplementedError("Subclasses should override this method and implement it")

    def _start(self):
        # implement if necessary
        pass

class ManolatorDmxController(BaseDmxController):
    def __init__(self, parallel, default_value=0, *args, **kwargs):
        self.live_channels = dict((c, None) for c in range(DMX_MIN_CHANNEL, DMX_MAX_CHANNEL))
        self.live_channels_lock = threading.Lock()

        self.channel_default_value = default_value

        self.parallel = parallel
        self.parallel_keep_going = False

        super(ManolatorDmxController, self).__init__(*args, **kwargs)

    def _start(self):
        self.parallel_keep_going = True
        self.parallel_update_thread = threading.Thread(
            target=self._perform_parallel_update,
            args=(self.parallel,),
            name="Manolator-Parallel-Thread"
        )
        self.parallel_update_thread.start()

    def _perform_parallel_update(self, p):
        # pySerial parallel in p
        try:
            while self.parallel_keep_going:
                p.setData(0)
                p.setAutoFeed(1)
                time.sleep(0.1)
                p.setAutoFeed(0)
                for channel in range(self.min_channel, self.max_channel):
                    p.setData(self.live_channels[channel])
                    p.setDataStrobe(1)
                    #time.sleep(0.01)  # Not usually necessary
                    p.setDataStrobe(0)
                    #time.sleep(0.01)  # Not usually necessary
                    p.setData(0)

                # now take a nap
                time.sleep(0.1)
        finally:
            self.parallel_keep_going = False


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

if __name__ == '__main__':
    from dummyparallel import DummyParallel
    mn = ManolatorDmxController(DummyParallel(), starting_values={76: 24})
    mn.set_channel(72, 255)
    mn.start()