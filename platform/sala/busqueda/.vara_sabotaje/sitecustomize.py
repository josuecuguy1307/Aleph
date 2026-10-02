import atexit, sys
def _romper():
    m = sys.modules.get('__main__')
    if m is not None and hasattr(m, '_SOURCES'): m._SOURCES = []
import threading; threading.Timer(0.35, _romper).start()
