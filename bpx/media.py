"""Tensor <-> media conversion. torch/PIL/numpy are imported lazily so headless
tooling (codegen, schema tests) can import the package without ComfyUI's stack."""

import base64
import io

from .client import MAX_INLINE_BYTES


def _pil():
    from PIL import Image  # noqa: PLC0415

    return Image


def tensor_to_png_bytes(image_tensor):
    """One ComfyUI IMAGE frame ([H,W,C] float 0..1) → PNG bytes."""
    import numpy as np  # noqa: PLC0415

    arr = (image_tensor.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    img = _pil().fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def image_batch_to_api_values(image_tensor, client):
    """ComfyUI IMAGE ([B,H,W,C]) → list of API media values, one per frame.

    Small frames go inline as data URIs; frames past the inline cap are pushed
    through POST /v1/uploads and passed as URLs.
    """
    values = []
    for i in range(image_tensor.shape[0]):
        png = tensor_to_png_bytes(image_tensor[i])
        if len(png) <= MAX_INLINE_BYTES:
            values.append("data:image/png;base64," + base64.b64encode(png).decode())
        else:
            values.append(client.upload(png, "input-%d.png" % i, "image/png"))
    return values


def image_bytes_to_tensor(data):
    """Encoded image bytes → [1,H,W,C] float tensor."""
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    img = _pil().open(io.BytesIO(data))
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr)[None,]


def combine_image_tensors(tensors):
    """Batch [1,H,W,C] tensors; mixed sizes are center-padded to the max frame."""
    import torch  # noqa: PLC0415

    if len(tensors) == 1:
        return tensors[0]
    max_h = max(t.shape[1] for t in tensors)
    max_w = max(t.shape[2] for t in tensors)
    padded = []
    for t in tensors:
        h, w = t.shape[1], t.shape[2]
        if h == max_h and w == max_w:
            padded.append(t)
            continue
        canvas = torch.zeros((1, max_h, max_w, t.shape[3]), dtype=t.dtype)
        top = (max_h - h) // 2
        left = (max_w - w) // 2
        canvas[:, top : top + h, left : left + w, :] = t
        padded.append(canvas)
    return torch.cat(padded, dim=0)


def urls_to_image_batch(urls, client):
    tensors = [image_bytes_to_tensor(client.download(u)) for u in urls]
    if not tensors:
        raise RuntimeError("Job succeeded but returned no images.")
    return combine_image_tensors(tensors)


# --- video / audio ---------------------------------------------------------


def _temp_dir():
    try:
        import folder_paths  # noqa: PLC0415

        return folder_paths.get_temp_directory()
    except Exception:
        import tempfile  # noqa: PLC0415

        return tempfile.gettempdir()


def save_temp_media(data, suffix):
    """Persist downloaded bytes under ComfyUI's temp dir (or the OS temp dir
    headless) and return the path. Named uniquely so parallel jobs don't clash."""
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    directory = _temp_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "budgetpixel-%s%s" % (uuid.uuid4().hex[:12], suffix))
    with open(path, "wb") as f:
        f.write(data)
    return path


def make_video_output(url, client):
    """Download a result video and wrap it as a ComfyUI VIDEO. Headless (no
    comfy_api available) it returns the saved file path instead."""
    path = save_temp_media(client.download(url), ".mp4")
    try:
        from comfy_api.input_impl import VideoFromFile  # noqa: PLC0415

        return VideoFromFile(path)
    except ImportError:
        return path


def video_input_to_url(value, client, name):
    """A VIDEO socket value (or a path/URL string) → an http(s) URL the API
    accepts. The /v1 media resolver requires URLs for video — never inline."""
    import os  # noqa: PLC0415

    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        if os.path.isfile(value):
            with open(value, "rb") as f:
                return client.upload(f.read(), os.path.basename(value), "video/mp4")
        raise ValueError("%s: string input must be a URL or an existing file path" % name)

    path = None
    if hasattr(value, "save_to"):  # comfy_api VideoInput
        path = save_temp_media(b"", ".mp4")
        value.save_to(path)
    elif hasattr(value, "get_stream_source"):
        source = value.get_stream_source()
        if isinstance(source, str) and os.path.isfile(source):
            path = source
    if path is None:
        raise ValueError("%s: unsupported VIDEO input type %r" % (name, type(value)))
    with open(path, "rb") as f:
        return client.upload(f.read(), os.path.basename(path), "video/mp4")


def comfy_audio_to_wav_bytes(audio):
    """ComfyUI AUDIO ({waveform [B,C,T], sample_rate}) → 16-bit PCM WAV bytes.
    Uses only the stdlib `wave` module so no audio backend is required."""
    import io  # noqa: PLC0415
    import wave  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    if hasattr(waveform, "dim") and waveform.dim() == 3:
        waveform = waveform[0]
    arr = waveform.cpu().numpy()  # [C, T]
    pcm = (arr.T.clip(-1.0, 1.0) * 32767.0).astype(np.int16)  # [T, C]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(pcm.shape[1] if pcm.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def audio_input_to_url(value, client, name):
    """An AUDIO socket value (or URL string) → an http(s) URL for the API."""
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        raise ValueError("%s: string input must be a URL" % name)
    if isinstance(value, dict) and "waveform" in value:
        return client.upload(comfy_audio_to_wav_bytes(value), "input.wav", "audio/wav")
    raise ValueError("%s: unsupported AUDIO input type %r" % (name, type(value)))


def audio_url_to_comfy(url, client):
    """Download a result track and decode to ComfyUI AUDIO. Tries torchaudio,
    then PyAV (both ship with ComfyUI); stdlib `wave` covers plain WAV."""
    suffix = ".wav" if ".wav" in url.split("?")[0].lower() else ".mp3"
    path = save_temp_media(client.download(url), suffix)

    try:
        import torchaudio  # noqa: PLC0415

        waveform, sample_rate = torchaudio.load(path)  # [C, T]
        return {"waveform": waveform.unsqueeze(0), "sample_rate": int(sample_rate)}
    except Exception:
        pass

    try:
        import av  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import torch  # noqa: PLC0415

        frames = []
        with av.open(path) as container:
            stream = container.streams.audio[0]
            sample_rate = stream.rate
            for frame in container.decode(stream):
                arr = frame.to_ndarray()  # [C, N] or [N] (packed formats vary)
                if arr.ndim == 1:
                    arr = arr[None, :]
                if arr.dtype.kind == "i":
                    arr = arr.astype(np.float32) / float(np.iinfo(arr.dtype).max)
                frames.append(arr.astype(np.float32))
        waveform = torch.from_numpy(np.concatenate(frames, axis=1))
        return {"waveform": waveform.unsqueeze(0), "sample_rate": int(sample_rate)}
    except Exception as e:
        raise RuntimeError(
            "Could not decode audio result (need torchaudio or av installed): %s" % e
        )
