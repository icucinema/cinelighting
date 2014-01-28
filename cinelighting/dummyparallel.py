import sys

class DummyParallel(object):
    def setData(self, data):
        sys.stdout.write(str(data))
    def setAutoFeed(self, autoFeed):
        if autoFeed == 1:
            sys.stdout.write("\n")
        sys.stdout.write("[")
        sys.stdout.write(str(autoFeed))
        sys.stdout.write("]")
    def setDataStrobe(self, dataStrobe):
        if dataStrobe == 1:
            sys.stdout.write("<")
        else:
            sys.stdout.write(">")
