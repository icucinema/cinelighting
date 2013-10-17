import dmx
import dummyparallel

def setup_parallel():
    return dummyparallel.DummyParallel()

def test_basic():
    mn = dmx.ManolatorDmxController(setup_parallel())
    mn.set_channel(72, 245)
    mn.set_channels({
        73: 233,
        76: 210
    })
    assert mn.get_channel(72) == 245
    assert mn.get_channel(73) == 233
    assert mn.get_channel(76) == 210
    assert mn.get_channels([72, 73, 76]) == {
        72: 245,
        73: 233,
        76: 210
    }

def test_set_starting_values():
    mn = dmx.ManolatorDmxController(setup_parallel(), starting_values={23: 16, 66: 11})
    assert mn.get_channel(23) == 16
    assert mn.get_channel(66) == 11

def test_start():
    mn = dmx.ManolatorDmxController(setup_parallel(), starting_values={23: 16, 66: 11})
    mn.start()
    assert mn.has_started
    assert mn.parallel_keep_going
    assert mn.parallel_update_thread.is_alive()
    mn.stop()
    assert not mn.has_started
    assert not mn.parallel_keep_going
    assert not mn.parallel_update_thread.is_alive()

def test_fading():
    dmdmx = dmx.DummyDmxController()
    mod = dmdmx.new_change()
    mod.set_value(time=0, channel=73, value=0)
    mod.set_value(time=2, channel=74, value=255)
    mod.set_value(time=2.1, channel=74, value=0, easing="sudden")
    mod.set_value(time=4, channel=74, value=60)
    mod.set_value(time=5, channel=73, value=255, easing="ease_in_out")
    mod.execute()
    mod.runner.join()
    assert False