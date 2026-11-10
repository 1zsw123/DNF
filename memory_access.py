"""Windows read-only process access for verified game telemetry."""
import ctypes as C,struct,os
from ctypes import wintypes as W

class ReadOnlyProcess:
    def __init__(self,pid):
        self.pid=pid;self.k=C.WinDLL('kernel32',use_last_error=True)
        self.k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.k.OpenProcess.restype=W.HANDLE
        self.k.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];self.k.ReadProcessMemory.restype=W.BOOL
        self.k.CloseHandle.argtypes=[W.HANDLE]
        self.handle=self.k.OpenProcess(0x410,False,pid)
        if not self.handle:raise OSError(C.get_last_error(),'Game read access unavailable')
    def read(self,address,size):
        buf=C.create_string_buffer(size);n=C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle,address,buf,size,C.byref(n)) or n.value!=size:return None
        return buf.raw
    def xyz(self,address):
        data=self.read(address,12)
        return struct.unpack('<3f',data) if data else None
    def alive(self):
        self.k.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
        self.k.GetExitCodeProcess.restype=W.BOOL
        code=W.DWORD()
        return bool(self.handle and self.k.GetExitCodeProcess(self.handle,C.byref(code)) and code.value==259)
    def image_path(self):
        self.k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
        self.k.QueryFullProcessImageNameW.restype=W.BOOL
        buf=C.create_unicode_buffer(32768);size=W.DWORD(len(buf))
        if not self.k.QueryFullProcessImageNameW(self.handle,0,buf,C.byref(size)):
            raise OSError(C.get_last_error(),'Cannot identify game executable')
        return buf.value
    def image_base(self,path):
        psapi=C.WinDLL('psapi',use_last_error=True)
        psapi.EnumProcessModulesEx.argtypes=[W.HANDLE,C.POINTER(W.HMODULE),W.DWORD,C.POINTER(W.DWORD),W.DWORD]
        psapi.EnumProcessModulesEx.restype=W.BOOL
        psapi.GetModuleFileNameExW.argtypes=[W.HANDLE,W.HMODULE,W.LPWSTR,W.DWORD]
        psapi.GetModuleFileNameExW.restype=W.DWORD
        modules=(W.HMODULE*2048)();needed=W.DWORD()
        if not psapi.EnumProcessModulesEx(self.handle,modules,C.sizeof(modules),C.byref(needed),3):
            raise OSError(C.get_last_error(),'Game modules not ready')
        if needed.value>C.sizeof(modules):raise ValueError('Game module list too large')
        normalized=os.path.normcase(os.path.abspath(path))
        for module in modules[:needed.value//C.sizeof(W.HMODULE)]:
            buf=C.create_unicode_buffer(32768)
            if psapi.GetModuleFileNameExW(self.handle,module,buf,len(buf)):
                if os.path.normcase(os.path.abspath(buf.value))==normalized:return int(module)
        raise ValueError('Game executable module not found')
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
