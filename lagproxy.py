#!/usr/bin/env python
"""
Simple network utility that forwards connections to a local port to a remote
host/port, optionally adding in simulated network latency.

Author: bencvt (Ben Cartwright)

Portions of this code are based on Simon Foster's pinhole utility.
http://code.activestate.com/recipes/114642/
Licensed under the PSF License: http://docs.python.org/license.html
"""

import sys
import os.path
import socket
import threading
import time
import random
try:
    import queue
except ImportError:
    import Queue as queue # 2.x compat

LOGGING = True
def log(s):
    if LOGGING:
        print('%s:%s' % (time.ctime(), s))
        sys.stdout.flush()

def usage():
    cmd = os.path.basename(sys.argv[0])
    print('Usage: %s localport remotehost remoteport [delaymin [delaymax]]' % cmd)
    print('Example: %s 8080 www.yahoo.com 80 0.6 1.4' % cmd)
    print('         Browsing http://localhost:8080 will then simulate a very laggy')
    print('         connection (600-1400ms latency) to www.yahoo.com.')

def main():
    try:
        args = sys.argv[1:]
        while '-q' in args:
            LOGGING = False
            args.remove('-q')
        localport = int(args[0])
        remotehost = args[1]
        remoteport = int(args[2])
        delay = None
        if len(args) > 3:
            delaymin, delaymax = float(args[3]), None
            if len(args) > 4:
                delaymax = float(args[4])
            delay = Delay(delaymin, delaymax)
    except:
        usage()
        return
    proxy = LagProxy(localport, remotehost, remoteport, delay)
    proxy.run()

class Delay(object):
    def __init__(self, minseconds, maxseconds=None):
        self.minseconds = minseconds
        if not maxseconds or maxseconds < minseconds:
            maxseconds = minseconds
        self.maxseconds = maxseconds

    def getrandom(self):
        # A different distribution may model real-world latency more accurately.
        # See http://docs.python.org/library/random.html#random.uniform
        # for some other builtin distributions to play around with.
        return random.uniform(self.minseconds, self.maxseconds)

    def __str__(self):
        return '[%f-%f] seconds added latency' % \
            (self.minseconds, self.maxseconds)

class BackloggedData(object):
    def __init__(self, payload, delay):
        if delay:
            self.waituntil = time.time() + delay.getrandom()
        else:
            self.waituntil = time.time()
        self.payload = payload

class PipeCleanerThread(threading.Thread):
    daemon = True
    def __init__(self, pipe):
        threading.Thread.__init__(self)
        self.pipe = pipe

    def run(self):
        while True:
            data = self.pipe.backlog.get(block=True)
            time.sleep(max(0, data.waituntil - time.time()))
            self.pipe.sink.send(data.payload)
            self.pipe.backlog.task_done()

class PipeThread(threading.Thread):
    daemon = True
    pipes = []
    def __init__(self, source, sink, delay):
        threading.Thread.__init__(self)
        self.source = source
        self.sink = sink
        self.delay = delay
        self.backlog = queue.Queue()
        self.cleanerthread = PipeCleanerThread(self)
        log('Creating new pipe thread  %s (%s -> %s)' % \
            (self, source.getpeername(), sink.getpeername()))
        PipeThread.pipes.append(self)
        log('%s pipes active' % len(PipeThread.pipes))

    def run(self):
        self.cleanerthread.start()
        while True:
            try:
                bytes = self.source.recv(1024)
                if not bytes:
                    break
                self.backlog.put(BackloggedData(bytes, self.delay), block=True)
            except:
                break
        log('%s terminating' % self)
        self.backlog.join()
        PipeThread.pipes.remove(self)
        log('%s pipes active' % len(PipeThread.pipes))

class LagProxy(object):
    def __init__(self, localport, remotehost, remoteport, delay=None):
        log('Redirecting: localhost:%s -> %s:%s with %s' % \
            (localport, remotehost, remoteport, delay if delay else 'no delay'))
        self.remotehost = remotehost
        self.remoteport = remoteport
        self.delay = delay
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # In case the proxy just got restarted and the socket address is
        # stuck in TIME_WAIT
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', localport))
        self.sock.listen(5)

    def run(self):
        while True:
            localsock, address = self.sock.accept()
            log('Creating new session for %s %s' % address)
            remotesock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remotesock.connect((self.remotehost, self.remoteport))
            PipeThread(localsock, remotesock, self.delay).start()
            PipeThread(remotesock, localsock, self.delay).start()

if __name__ == '__main__':
    main()
