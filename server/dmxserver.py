import SocketServer as socketserver
import re
import traceback

class DmxProtocolException(Exception):
    short_error = "Protocol exception"
    def get_short_error(self):
        return self.short_error

class DmxCommandInvalid(DmxProtocolException):
    short_error = "Invalid command"
class DmxCommandExit(DmxProtocolException):
    short_error = "Quitting"
class DmxCommandAsync(DmxProtocolException):
    def __init__(self, command_id):
        self.command_id = command_id
    short_error = "Async command starting"

VERSION = "0.1"

def safe_int(val):
    try:
        return int(val)
    except:
        raise DmxCommandInvalid()

class DmxCommandParser(object):
    commands = [
        (r'^\?$', 'command_help'),
        (r'^help$', 'command_help'),

        (r'^(c|get) (?P<channel>[0-9]+)$', 'command_get_channel'),
        (r'^(c|set) (?P<channel>[0-9]+):(?P<value>[0-9]+)$', 'command_set_channel'),

        (r'^f (?P<channel>[0-9]+)(:(?P<from_value>[0-9]+))?:(?P<to_value>[0-9]+):(?P<seconds>[0-9]+)(:(?P<block>[YN]))?$', 'command_fade_channel'),

        (r'^getm( (?P<channels>([0-9]+,)*[0-9]+))?$', 'command_get_channels'),
        (r'^setm (?P<channels>([0-9]+:[0-9]+,)*[0-9]+:[0-9]+)?$', 'command_set_channels'),

        (r'^(v|version)$', 'command_version'),

        (r'^bye$', 'command_exit'),
        (r'^exit$', 'command_exit'),
        (r'^quit$', 'command_exit'),
        (r'^q$', 'command_exit'),
    ]

    def __init__(self, dmx, handler):
        self.dmx = dmx
        self.handler = handler
        self.preprocess_commands(self.commands)

    def preprocess_commands(self, commands):
        cmds = []
        for command, func in commands:
            cmds.append((re.compile(command), getattr(self, func)))
        self.commands = cmds
        return cmds

    def process_command(self, sock_input):
        for command, func in self.commands:
            res = command.match(sock_input)
            if res:
                return func(**res.groupdict())
        raise DmxCommandInvalid()

    def command_fade_channel(self, channel, to_value, seconds, from_value=None, block='N'):
        ch, to_val = safe_int(channel), safe_int(to_value)
        seconds = safe_int(seconds)
        if from_value is None:
            from_val = self.dmx.get_channel(ch)
        else:
            from_val = safe_int(from_value)
        change = self.dmx.new_change()
        change.set(0, ch, from_val)
        change.set(seconds, ch, to_val)
        change.execute()
        if block == 'Y':
            change.runner.join()
        else:
            command_id = self.handler.get_async_command_id()
            change.runner.when_done(lambda _: self.handler.async_done(command_id))
            raise DmxCommandAsync(command_id)


    def command_set_channel(self, channel, value):
        ch, val = safe_int(channel), safe_int(value)
        self.dmx.set_channel(ch, val)

    def command_version(self):
        import dmx
        return "Server v{}, DMX v{}".format(VERSION, dmx.VERSION)

    def command_get_channel(self, channel):
        ch = safe_int(channel)
        return "{}:{}".format(ch, self.dmx.get_channel(ch))


    def command_set_channels(self, channels):
        chpairs = [z.split(':') for z in channels.split(',')]
        out = {}
        for ch, val in chpairs:
            ch, val = safe_int(ch), safe_int(val)
            out[ch] = val
        self.dmx.set_channels(out)

    def command_get_channels(self, channels=None):
        if channels is None:
            channels = range(self.dmx.min_channel, self.dmx.max_channel+1)
        else:
            channels = [safe_int(z) for z in channels.split(',')]
        channel_data = self.dmx.get_channels(channels)
        outp = ["{}:{}".format(ch, val) for ch, val in channel_data.iteritems()]
        return ",".join(outp)


    def command_help(self):
        return """Commands:
- ?/help: this help
- q/bye/exit/quit: closes the connection
- c/set <channel>:<value>: sets <channel> to <value>
- c/get <channel>: returns the current value of <channel>
- getm <channels>: returns the current value of <channels> (channels is comma-separated)
- setm <cvps>: sets each channel to the value in <cvps> (cvps is in the format channel:value,channel:value,channel:value,... - Channel Value PairS)
- v/version: returns the currently running software versions
- f <channel>(:<from_value>):<to_value>:<seconds>:<block Y|N>: immediately execute a fade of <channel> from <from_value> to <to_value> over <seconds> seconds, optionally <block>ing until complete

Protocol notes:
Issue me a command, and I will respond with:
OK - command completed successfully
OK <note> - command completed successfully with optional extra information (may be several lines, all OK prefixed)
ASYNCPENDING <number> - async operation <number> is now running
ASYNCDONE <number> - async operation <number> is now done
ASYNCDONE <number> <note> - async operation <number> is now done with optional extra information (again, may be several lines)
ERROR - command failed
ERROR <reason> - command failed because <reason>
BYE <note> - goodbye - closing connection
"""
    def command_exit(self):
        raise DmxCommandExit()
        

class DmxTcpHandler(socketserver.StreamRequestHandler):
    """
    Imperial Cinema DMX protocol RequestHandler class.
    """
    def __init__(self, dmx, *args, **kwargs):
        self.dmx = dmx
        self.async_command_id = 0
        self.pending_async_commands = set()
        self.completed_async_commands = {}
        socketserver.StreamRequestHandler.__init__(self, *args, **kwargs)

    def handle(self):
        # the ICDMX TCP protocol is line-based
        # this means that we just eat the input one line at a time
        self.parser = DmxCommandParser(self.dmx, self)
        self.wfile.write("READY (? for help)\n")
        while True:
            try:
                out = self.parser.process_command(self.rfile.readline().rstrip())
                if not out:
                    self.wfile.write("OK\n")
                else:
                    for ln in out.split('\n'):
                        self.wfile.write("OK {}\n".format(ln))
            except DmxCommandAsync, ex:
                self.wfile.write("ASYNCPENDING {}\n".format(ex.command_id))
                if ex.command_id in self.pending_async_commands:
                    self.pending_async_commands.remove(ex.command_id)
                    self.wfile.write("ASYNCDONE {}\n".format(ex.command_id))
                else:
                    self.pending_async_commands.add(ex.command_id)
            except DmxCommandExit:
                self.wfile.write("BYE cya\n")
                break
            except DmxProtocolException, ex:
                self.wfile.write("ERROR {}\n".format(ex.get_short_error()))
            except Exception, ex:
                traceback.print_exc()
                self.wfile.write("ERROR {}\n".format(str(ex)))

    def get_async_command_id(self):
        self.async_command_id += 1
        return self.async_command_id

    def say_async_done(self, command_id):
        reason = self.completed_async_commands[command_id]
        if not reason:
            self.wfile.write("ASYNCDONE {}\n".format(command_id))
        else:
            for ln in reason.split('\n'):
                self.wfile.write("ASYNCDONE {} {}\n".format(command_id, ln))

    def async_done(self, command_id, reason=None):
        self.completed_async_commands[command_id] = reason
        if command_id in self.pending_async_commands:
            self.pending_async_commands.remove(command_id)
            self.say_async_done(command_id)
        else:
            self.pending_async_commands.add(command_id)


class DmxTcpServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, dmx, *args, **kwargs):
        self.dmx = dmx
        socketserver.TCPServer.__init__(self, *args, **kwargs)

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(self.dmx, request, client_address, self)


if __name__ == '__main__':
    HOST, PORT = "localhost", 9090

    import sys
    sys.path.append("../lib/")

    import dmx, dummyparallel
    dmdmx = dmx.ManolatorDmxController(dummyparallel.DummyParallel())

    server = DmxTcpServer(dmdmx, (HOST, PORT), DmxTcpHandler)
    server.serve_forever()