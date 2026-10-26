"""Windows AppContainer process launcher for project execution tools."""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Iterable


OUTPUT_LIMIT = 64_000
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_TOKEN_QUERY = 0x0008
_TOKEN_IS_APP_CONTAINER = 29


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _flatbuffer_string(data: bytearray, value: str) -> int:
    target = len(data)
    encoded = value.encode("utf-8")
    data.extend(struct.pack("<I", len(encoded)) + encoded + b"\0")
    data.extend(b"\0" * (-len(data) % 4))
    return target


def _flatbuffer_vector(data: bytearray, values: Iterable[str]) -> int:
    values = tuple(values)
    target = len(data)
    data.extend(struct.pack("<I", len(values)) + b"\0" * (4 * len(values)))
    for index, value in enumerate(values):
        string = _flatbuffer_string(data, value)
        slot = target + 4 + 4 * index
        struct.pack_into("<I", data, slot, string - slot)
    return target


def sandbox_spec(
    read_write: Iterable[str], read_only: Iterable[str], deny: Iterable[str] = (),
    capabilities: str = "", disallow_win32k: bool = True,
) -> bytes:
    """Build the tiny SBOX FlatBuffer used by Windows' documented schema."""
    data = bytearray(92)
    struct.pack_into("<I", data, 0, 40)
    data[4:8] = b"SBOX"
    # The schema fields are version, AppContainer, Win32k mitigation, and two path vectors.
    struct.pack_into("<HH12H", data, 8, 28, 52, 4, 8, 0, 16, 0, 0, 36, 40, 44, 0, 0, 48)
    struct.pack_into("<i", data, 40, 32)
    data[48] = 1
    data[56] = int(disallow_win32k)
    pointers = [
        (44, _flatbuffer_string(data, "0.1.0")),
        (76, _flatbuffer_string(data, capabilities)),
        (80, _flatbuffer_vector(data, read_write)),
        (84, _flatbuffer_vector(data, read_only)),
        (88, _flatbuffer_vector(data, deny)),
    ]
    for slot, target in pointers:
        struct.pack_into("<I", data, slot, target - slot)
    return bytes(data)


def _is_appcontainer() -> bool:
    if os.name != "nt":
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "cannot inspect the current process token")
    try:
        value, returned = wintypes.DWORD(), wintypes.DWORD()
        if not advapi.GetTokenInformation(
            token, _TOKEN_IS_APP_CONTAINER, ctypes.byref(value), ctypes.sizeof(value),
            ctypes.byref(returned),
        ):
            raise OSError(ctypes.get_last_error(), "cannot inspect AppContainer status")
        return bool(value.value)
    finally:
        kernel.CloseHandle(token)


def _environment(temp_dir: Path, appcontainer_temp: Path, path_extra: Iterable[str]) -> ctypes.Array:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    entries = {
        "PATH": os.pathsep.join((
            str(Path(sys.executable).parent), str(Path(sys.base_prefix) / "DLLs"),
            str(Path(system_root) / "System32"), *path_extra,
        )),
        "ALLUSERSPROFILE": os.environ.get("ALLUSERSPROFILE", str(Path(system_root) / "ServiceProfiles" / "LocalService")),
        "APPDATA": str(appcontainer_temp),
        "LOCALAPPDATA": str(appcontainer_temp.parent),
        "USERPROFILE": str(appcontainer_temp.parent),
        "USERNAME": os.environ.get("USERNAME", "JinniSandbox"),
        "USERDOMAIN": os.environ.get("USERDOMAIN", "Jinni"),
        "HOMEDRIVE": os.environ.get("HOMEDRIVE", Path(temp_dir).drive),
        "HOMEPATH": os.environ.get("HOMEPATH", str(temp_dir)[len(Path(temp_dir).drive):]),
        "ComSpec": str(Path(system_root) / "System32" / "cmd.exe"),
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "TEMP": str(appcontainer_temp),
        "TMP": str(appcontainer_temp),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    block = "\0".join(
        f"{key}={value}" for key, value in sorted(entries.items(), key=lambda item: item[0].casefold())
    ) + "\0\0"
    return ctypes.create_unicode_buffer(block, len(block))


def _profile_paths(profile: str) -> tuple[Path, Path]:
    if not profile.startswith("Jinni-") or not all(char in "0123456789abcdef" for char in profile[6:].lower()):
        raise ValueError("invalid AppContainer identity")
    packages = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Packages"
    root = packages / profile
    return root, root / "AC" / "Temp"


def create_sandbox_profile() -> tuple[str, Path]:
    profile = f"Jinni-{uuid.uuid4().hex}"
    _, temp_dir = _profile_paths(profile)
    temp_dir.mkdir(parents=True, exist_ok=False)
    return profile, temp_dir


def delete_sandbox_profile(profile: str) -> None:
    root, _ = _profile_paths(profile)
    packages = root.parent.resolve()
    resolved = root.resolve()
    if resolved.parent != packages or not resolved.is_relative_to(packages):
        raise ValueError("refusing to remove an unexpected AppContainer profile path")
    try:
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        delete_profile = userenv.DeleteAppContainerProfile
        delete_profile.argtypes = [wintypes.LPCWSTR]
        delete_profile.restype = ctypes.c_long
        result = delete_profile(profile)
        if result == 0 and resolved.exists():
            shutil.rmtree(resolved)
    except (AttributeError, OSError):
        pass


def run_isolated(
    executable: str,
    arguments: list[str],
    cwd: Path,
    temp_dir: Path,
    timeout: int,
    output_file: Path,
    read_only: Iterable[str] = (),
    profile: str | None = None,
    deny: Iterable[str] = (),
    path_extra: Iterable[str] = (),
    capabilities: str = "",
    disallow_win32k: bool = True,
    read_write: Iterable[str] = (),
) -> tuple[int, str, bool]:
    """Run one fixed executable in a no-network AppContainer and bound its lifetime/output."""
    if os.name != "nt":
        raise RuntimeError("isolated execution is available only on Windows")
    if _is_appcontainer():
        raise RuntimeError("the current Jinni process is already in an AppContainer; nested sandbox launch is blocked")
    dll_path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "processmodel.dll"
    try:
        process_model = ctypes.WinDLL(str(dll_path), use_last_error=True)
        create_sandbox = process_model.Experimental_CreateProcessInSandbox
    except (OSError, AttributeError):
        raise RuntimeError("this Windows installation does not provide AppContainer process isolation") from None

    owns_profile = profile is None
    if profile is None:
        profile, appcontainer_temp = create_sandbox_profile()
    else:
        _, appcontainer_temp = _profile_paths(profile)
        appcontainer_temp.mkdir(parents=True, exist_ok=True)
    control_paths = tuple(
        str((cwd.resolve() / name)) for name in (".git", ".jinni")
        if (cwd / name).exists()
    )
    spec = sandbox_spec(
        (str(cwd.resolve()), str(temp_dir.resolve()), str(appcontainer_temp.resolve()), *read_write),
        read_only, (*control_paths, *deny), capabilities, disallow_win32k,
    )
    spec_buffer = ctypes.create_string_buffer(spec)
    startup, info = _StartupInfo(), _ProcessInformation()
    startup.cb = ctypes.sizeof(startup)
    command = ctypes.create_unicode_buffer(__import__("subprocess").list2cmdline([executable, *arguments]))
    environment = _environment(temp_dir, appcontainer_temp, path_extra)
    create_sandbox.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo), wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_ProcessInformation),
    ]
    create_sandbox.restype = wintypes.BOOL

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "could not create a process cleanup job")
    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError(ctypes.get_last_error(), "could not configure process cleanup")
        flags = _CREATE_SUSPENDED | _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT
        if not create_sandbox(
            executable, command, None, None, False, flags, ctypes.cast(environment, ctypes.c_void_p),
            str(cwd), ctypes.byref(startup), profile, ctypes.cast(spec_buffer, ctypes.c_void_p),
            len(spec), ctypes.byref(info),
        ):
            code = ctypes.get_last_error()
            raise OSError(code, f"AppContainer process creation failed (Windows error {code})")
        if not kernel.AssignProcessToJobObject(job, info.hProcess):
            raise OSError(ctypes.get_last_error(), "could not contain sandbox child processes")
        resume = kernel.ResumeThread
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = wintypes.DWORD
        if resume(info.hThread) == 0xFFFFFFFF:
            raise OSError(ctypes.get_last_error(), "could not start the sandboxed process")

        deadline = time.monotonic() + timeout
        overflow = False
        while True:
            wait = kernel.WaitForSingleObject(info.hProcess, 50)
            if wait == 0:
                break
            if wait == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), "could not wait for the sandboxed process")
            try:
                if output_file.stat().st_size > OUTPUT_LIMIT:
                    overflow = True
                    break
            except FileNotFoundError:
                pass
            if time.monotonic() >= deadline:
                kernel.TerminateJobObject(job, 1)
                raise TimeoutError(f"execution exceeded the {timeout}-second limit")
        if overflow:
            kernel.TerminateJobObject(job, 1)
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise OSError(ctypes.get_last_error(), "could not read sandbox exit status")
        try:
            raw = output_file.read_bytes()[:OUTPUT_LIMIT]
        except FileNotFoundError:
            raw = b""
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            output = raw.decode("utf-16", errors="replace")
        elif b"\0" in raw[:128]:
            output = raw.decode("utf-16-le", errors="replace")
        else:
            output = raw.decode("utf-8", errors="replace")
        return int(exit_code.value), output, overflow
    finally:
        if info.hProcess:
            kernel.TerminateJobObject(job, 0)
            kernel.TerminateProcess(info.hProcess, 1)
            kernel.CloseHandle(info.hThread)
            kernel.CloseHandle(info.hProcess)
        kernel.CloseHandle(job)
        if owns_profile:
            delete_sandbox_profile(profile)
