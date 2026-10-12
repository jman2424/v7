"""Decoder resource limits and paid duration are exercised without provider calls."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import wave

import pytest

from service import audio_decoder, speech_transcription, usage_wallet


class InputPipe(BytesIO):
    def close(self):
        self.captured = self.getvalue()
        super().close()


class DecoderProcess:
    def __init__(self,pcm=b"\0"*32000,stderr=b"",code=0,timeout=False):
        self.stdin,self.stdout,self.stderr = InputPipe(),BytesIO(pcm),BytesIO(stderr)
        self.code,self.timeout,self.killed = code,timeout,False

    def kill(self):
        self.killed = True

    def wait(self,timeout):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg",timeout)
        return self.code


@pytest.fixture
def decoder(monkeypatch):
    captured = {}
    process = DecoderProcess()
    monkeypatch.setattr(audio_decoder,"decoder_binary",lambda:"/usr/bin/ffmpeg")

    def popen(args,**kwargs):
        captured.update(args=args,**kwargs)
        return process

    monkeypatch.setattr(audio_decoder.subprocess,"Popen",popen)
    return process,captured


def test_decode_uses_only_fixed_pipe_arguments_and_no_application_secrets(decoder,monkeypatch):
    process,captured = decoder
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-private-key")
    monkeypatch.setenv("V7_POSTGRES_DSN","synthetic-private-dsn")
    result = audio_decoder.decode_wav(b"OggS compressed data","audio/ogg")
    with wave.open(BytesIO(result),"rb") as recording:
        assert recording.getnchannels()==1 and recording.getframerate()==16000
        assert recording.getnframes()==16000 and recording.getsampwidth()==2
    args = captured["args"]
    assert args[0]=="/usr/bin/ffmpeg" and captured["shell"] is False and captured["close_fds"] is True
    assert args[args.index("-protocol_whitelist")+1]=="pipe"
    assert args[args.index("-i")+1]=="pipe:0" and args[-1]=="pipe:1"
    assert "-fs" in args and "-max_alloc" in args and "-t" not in args
    assert captured["env"]=={"LANG":"C","LC_ALL":"C","AV_LOG_FORCE_NOCOLOR":"1"}
    assert process.stdin.captured==b"OggS compressed data"
    assert "synthetic-private" not in str(captured)


@pytest.mark.parametrize("pcm,stderr,code,timeout,expected",[
    (b"",b"",0,False,"audio_duration_unverified"),
    (b"\0"*3,b"",0,False,"audio_duration_unverified"),
    (b"\0"*32000,b"sensitive decoder text",1,False,"audio_decode_failed"),
    (b"\0"*32000,b"",0,True,"audio_decode_timeout"),
    (b"\0"*1920002,b"",0,False,"audio_duration_unverified"),
    (b"\0"*(audio_decoder.MAX_PCM_BYTES+1),b"",0,False,"audio_duration_unverified"),
    (b"\0"*32000,b"x"*(audio_decoder.MAX_STDERR_BYTES+1),0,False,"audio_duration_unverified"),
],ids=["empty","odd-frame","decoder-error","timeout","over-sixty-seconds","stdout-cap","stderr-cap"])
def test_decoder_failure_timeout_and_output_limits(decoder,pcm,stderr,code,timeout,expected):
    process,_ = decoder
    process.stdout,process.stderr = BytesIO(pcm),BytesIO(stderr)
    process.code,process.timeout = code,timeout
    with pytest.raises(audio_decoder.AudioDecodeError) as error:
        audio_decoder.decode_wav(b"OggS audio","audio/ogg")
    assert error.value.code==expected
    assert "sensitive decoder text" not in str(error.value)
    if timeout or len(pcm)>audio_decoder.MAX_PCM_BYTES or len(stderr)>audio_decoder.MAX_STDERR_BYTES:
        assert process.killed


def test_unavailable_decoder_and_oversized_input_never_spawn(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(audio_decoder.subprocess,"Popen",spawn)
    monkeypatch.setattr(audio_decoder,"decoder_binary",lambda:None)
    with pytest.raises(audio_decoder.AudioDecodeError,match="audio_decoder_unavailable"):
        audio_decoder.decode_wav(b"OggS data","audio/ogg")
    with pytest.raises(audio_decoder.AudioDecodeError,match="invalid_audio"):
        audio_decoder.decode_wav(b"x"*(audio_decoder.MAX_INPUT_BYTES+1),"audio/ogg")
    spawn.assert_not_called()


def test_compressed_capability_is_honest_without_binary(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-only")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL","gpt-transcribe")
    monkeypatch.setattr(audio_decoder,"decoder_binary",lambda:None)
    status = speech_transcription.transcription_status()
    assert status["configured"] and status["bounded_audio_model"]
    assert status["compressed_audio_supported"] is False
    assert status["supported_audio_formats"]==["audio/wav","audio/x-wav"]


@pytest.mark.parametrize("code",["audio_decoder_unavailable","audio_decode_failed","audio_decode_timeout"])
def test_failed_compressed_decode_never_reserves_or_calls_provider(monkeypatch,code):
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-only")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL","gpt-transcribe")
    monkeypatch.setattr("service.subscriptions.internal_business",lambda tenant:False)
    monkeypatch.setattr(audio_decoder,"decode_wav",Mock(side_effect=audio_decoder.AudioDecodeError(code)))
    reserve,provider = Mock(),Mock()
    monkeypatch.setattr(usage_wallet,"reserve_usage",reserve)
    monkeypatch.setattr(speech_transcription,"OpenAI",provider)
    with pytest.raises(speech_transcription.SpeechTranscriptionError) as error:
        speech_transcription.transcribe_audio(b"OggS recording","audio/ogg",tenant="EXAMPLE",channel="whatsapp")
    assert error.value.code==code
    reserve.assert_not_called()
    provider.assert_not_called()


def test_decoded_duration_reserves_credit_before_provider_and_sends_only_canonical_wav(decoder,monkeypatch):
    provider = Mock()
    provider.audio.transcriptions.create.return_value = SimpleNamespace(
        text="Question",usage=SimpleNamespace(type="duration",seconds=1))
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-only")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL","gpt-transcribe")
    monkeypatch.setattr("service.subscriptions.internal_business",lambda tenant:False)
    monkeypatch.setattr(speech_transcription,"OpenAI",lambda **kwargs:provider)
    order = []

    def reserve(tenant,ceiling,metadata):
        assert tenant=="EXAMPLE" and ceiling==150_000
        assert metadata["rate_snapshot"]=={"audio_second":75000}
        assert "compressed data" not in str(metadata)
        order.append("reserve")
        return "synthetic-reservation"

    def complete(**kwargs):
        assert order==["reserve"]
        filename,data,mime = kwargs["file"]
        assert filename=="message.wav" and mime=="audio/wav" and data[:4]==b"RIFF"
        with wave.open(BytesIO(data),"rb") as recording:
            assert recording.getnframes()/recording.getframerate()==1
        order.append("provider")
        return SimpleNamespace(text="Question",usage=SimpleNamespace(type="duration",seconds=1))

    monkeypatch.setattr(usage_wallet,"reserve_usage",reserve)
    settle = Mock()
    monkeypatch.setattr(usage_wallet,"settle_usage",settle)
    monkeypatch.setattr("service.api_usage.record_transcription",Mock())
    provider.audio.transcriptions.create.side_effect = complete
    assert speech_transcription.transcribe_audio(b"OggS compressed data","audio/ogg",tenant="EXAMPLE",channel="whatsapp")=="Question"
    assert order==["reserve","provider"]
    assert settle.call_args.args[1]==75_000


def test_actual_decoder_canonicalizes_streamable_audio_if_available():
    binary = audio_decoder.decoder_binary()
    if not binary:
        pytest.skip("Trusted FFmpeg is installed in the Docker runtime, not this local environment")
    wave_data = BytesIO()
    with wave.open(wave_data,"wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b"\0"*32000)
    encoded = subprocess.run([binary,"-hide_banner","-loglevel","error","-nostdin","-protocol_whitelist","pipe",
        "-f","wav","-i","pipe:0","-c:a","libopus","-f","ogg","pipe:1"],input=wave_data.getvalue(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True,shell=False,
        env={"LANG":"C","LC_ALL":"C"}).stdout
    decoded = audio_decoder.decode_wav(encoded,"audio/ogg")
    with wave.open(BytesIO(decoded),"rb") as recording:
        assert .9<=recording.getnframes()/recording.getframerate()<=1.1
