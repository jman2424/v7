"""Bounded audio decoding through the deployment's trusted FFmpeg binary."""
from __future__ import annotations

import io
import os
import subprocess
import threading
import wave

MAX_INPUT_BYTES = 10 * 1024 * 1024
SAMPLE_RATE = 16000
MAX_PCM_BYTES = SAMPLE_RATE * 2 * 61
MAX_STDERR_BYTES = 16 * 1024
DECODE_TIMEOUT = 10
_DEMUXERS = {"audio/ogg": "ogg", "audio/webm": "matroska", "audio/mpeg": "mp3",
             "audio/mp3": "mp3", "audio/mp4": "mov", "audio/m4a": "mov", "audio/x-m4a": "mov"}


class AudioDecodeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def decoder_binary():
    # No environment override or PATH search: production installs this binary
    # as root, while the application and uploaded media run as appuser.
    path = "/usr/bin/ffmpeg"
    return path if os.name == "posix" and os.path.isfile(path) and os.access(path, os.X_OK) else None


def compressed_formats():
    return list(_DEMUXERS) if decoder_binary() else []


def decode_wav(data, media_type):
    if not isinstance(data, bytes) or not data or len(data)>MAX_INPUT_BYTES or media_type not in _DEMUXERS:
        raise AudioDecodeError("invalid_audio")
    binary = decoder_binary()
    if not binary:
        raise AudioDecodeError("audio_decoder_unavailable")
    args = [binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-max_alloc", "16777216",
            "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-protocol_whitelist", "pipe", "-f", _DEMUXERS[media_type], "-i", "pipe:0",
            "-map", "0:a:0", "-vn", "-sn", "-dn", "-threads", "1", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-c:a", "pcm_s16le", "-f", "s16le", "-fs", str(MAX_PCM_BYTES), "pipe:1"]
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, cwd="/", env={"LANG":"C", "LC_ALL":"C", "AV_LOG_FORCE_NOCOLOR":"1"})
    except OSError:
        raise AudioDecodeError("audio_decoder_unavailable") from None
    output = []
    overflow, io_failure = threading.Event(), threading.Event()

    def stop():
        try:
            process.kill()
        except OSError:
            pass  # An already-exited child needs no termination.

    def read(stream, cap, destination=None):
        size = 0
        try:
            while chunk := stream.read(32768):
                size += len(chunk)
                if size>cap:
                    overflow.set()
                    stop()
                    break
                if destination is not None:
                    destination.append(chunk)
        except OSError:
            io_failure.set()
            stop()
        finally:
            stream.close()

    def write():
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except BrokenPipeError:
            pass  # The bounded decoder can finish before reading trailing bytes.
        except OSError:
            io_failure.set()
            stop()
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass  # Closing a pipe after the child exits can flush no more data.

    workers = [threading.Thread(target=read,args=(process.stdout,MAX_PCM_BYTES,output),daemon=True),
               threading.Thread(target=read,args=(process.stderr,MAX_STDERR_BYTES),daemon=True),
               threading.Thread(target=write,daemon=True)]
    for worker in workers:
        worker.start()
    timed_out = False
    try:
        result = process.wait(timeout=DECODE_TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop()
        try:
            result = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            result = -1
    finally:
        for worker in workers:
            worker.join(timeout=1)
    if timed_out:
        raise AudioDecodeError("audio_decode_timeout")
    if overflow.is_set():
        raise AudioDecodeError("audio_duration_unverified")
    if result or io_failure.is_set() or any(worker.is_alive() for worker in workers):
        raise AudioDecodeError("audio_decode_failed")
    pcm = b"".join(output)
    if not pcm or len(pcm)%2 or len(pcm)>SAMPLE_RATE*2*60:
        raise AudioDecodeError("audio_duration_unverified")
    decoded = io.BytesIO()
    with wave.open(decoded,"wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(SAMPLE_RATE)
        recording.writeframes(pcm)
    return decoded.getvalue()
