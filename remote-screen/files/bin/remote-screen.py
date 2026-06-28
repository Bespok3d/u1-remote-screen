#!/usr/bin/env python3

import argparse
import ctypes
import fcntl
import hashlib
import mmap
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from gui_watchdog import GuiWatchdog
from PIL import Image
from touch_input import EvdevWriter, TouchController

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602

BPP_RGBA = 32
BPP_RGB565 = 16
JPEG_QUALITY = 75
STREAM_FPS = 15

class FbVarScreeninfo(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_uint32),
        ("yres", ctypes.c_uint32),
        ("xres_virtual", ctypes.c_uint32),
        ("yres_virtual", ctypes.c_uint32),
        ("xoffset", ctypes.c_uint32),
        ("yoffset", ctypes.c_uint32),
        ("bits_per_pixel", ctypes.c_uint32),
        ("grayscale", ctypes.c_uint32),
        ("red", ctypes.c_uint32 * 3),
        ("green", ctypes.c_uint32 * 3),
        ("blue", ctypes.c_uint32 * 3),
        ("transp", ctypes.c_uint32 * 3),
        ("nonstd", ctypes.c_uint32),
        ("activate", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("accel_flags", ctypes.c_uint32),
        ("pixclock", ctypes.c_uint32),
        ("left_margin", ctypes.c_uint32),
        ("right_margin", ctypes.c_uint32),
        ("upper_margin", ctypes.c_uint32),
        ("lower_margin", ctypes.c_uint32),
        ("hsync_len", ctypes.c_uint32),
        ("vsync_len", ctypes.c_uint32),
        ("sync", ctypes.c_uint32),
        ("vmode", ctypes.c_uint32),
        ("rotate", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]

class FbFixScreeninfo(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]

def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

class Framebuffer:
    def __init__(self, device='/dev/fb0'):
        self.device = device
        self.fd = None
        self.mm = None
        self.width = 0
        self.height = 0
        self.virtual_width = 0
        self.virtual_height = 0
        self.bpp = 0
        self.line_length = 0
        self._cache_hash = None
        self._cache_jpeg = None
        self._open()

    def _open(self):
        self.fd = os.open(self.device, os.O_RDONLY)
        vinfo = FbVarScreeninfo()
        fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, vinfo)
        finfo = FbFixScreeninfo()
        fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, finfo)

        self.width = vinfo.xres
        self.virtual_width = vinfo.xres_virtual
        self.height = vinfo.yres
        self.virtual_height = vinfo.yres_virtual
        self.bpp = vinfo.bits_per_pixel
        self.line_length = finfo.line_length
        self.can_pan = self.virtual_height > self.height

        size = self.line_length * self.virtual_height
        self.mm = mmap.mmap(self.fd, size, mmap.MAP_SHARED, mmap.PROT_READ)
        log(
            f"Framebuffer: {self.width}x{self.height} "
            f"({self.virtual_width}x{self.virtual_height} virtual) "
            f"@ {self.bpp}bpp, line_length={self.line_length}"
        )

    def _current_offset(self):
        if not self.can_pan:
            return 0
        vinfo = FbVarScreeninfo()
        fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, vinfo)
        return vinfo.yoffset * self.line_length

    def _encode(self, raw):
        size = (self.width, self.height)
        if self.bpp == BPP_RGBA:
            rgba = Image.frombytes('RGBA', size, raw, 'raw', 'BGRA', self.line_length)
            return rgba.convert('RGB')
        if self.bpp == BPP_RGB565:
            return Image.frombytes('RGB', size, raw, 'raw', 'BGR;16', self.line_length)
        return Image.frombytes('RGB', size, raw, 'raw', 'BGR', self.line_length)

    def get_snapshot(self, client_etag=None):
        self.mm.seek(self._current_offset())
        raw = self.mm.read(self.line_length * self.height)
        raw_hash = hashlib.md5(raw).hexdigest()[:16]
        if client_etag and client_etag == raw_hash:
            return raw_hash, None
        if raw_hash == self._cache_hash and self._cache_jpeg:
            return raw_hash, self._cache_jpeg
        buf = BytesIO()
        self._encode(raw).save(buf, 'JPEG', quality=JPEG_QUALITY)
        jpeg_data = buf.getvalue()
        self._cache_hash = raw_hash
        self._cache_jpeg = jpeg_data
        return raw_hash, jpeg_data

    def close(self):
        if self.mm:
            self.mm.close()
        if self.fd:
            os.close(self.fd)

class ScreenHandler(SimpleHTTPRequestHandler):
    framebuffer = None
    touch = None
    html_dir = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.html_dir, **kwargs)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ('/snapshot.jpg', '/snapshot'):
            self.handle_snapshot()
        elif path == '/stream.mjpg':
            self.handle_stream_mjpeg()
        elif path == '/touch':
            self.handle_touch(parsed.query)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/touch':
            self.handle_touch(parsed.query)
        else:
            self.send_error(404, 'Not Found')

    def handle_snapshot(self):
        try:
            client_etag = self.headers.get('If-None-Match', '').strip('"')
            etag, jpeg_data = self.framebuffer.get_snapshot(client_etag)
            if jpeg_data is None:
                self.send_response(304)
                self.send_header('ETag', f'"{etag}"')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', len(jpeg_data))
            self.send_header('ETag', f'"{etag}"')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(jpeg_data)
        except Exception as e:
            log(f"Snapshot error: {e}")
            self.send_error(500, str(e))

    def handle_stream_mjpeg(self):
        try:
            self._begin_mjpeg()
            self._stream_frames()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"Stream error: {e}")

    def _begin_mjpeg(self):
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

    def _stream_frames(self):
        last_etag = None
        last_jpeg = None
        while True:
            etag, jpeg_data = self.framebuffer.get_snapshot(last_etag)
            if jpeg_data is not None:
                last_etag = etag
                last_jpeg = jpeg_data
            if last_jpeg is not None:
                self._write_mjpeg_frame(last_jpeg)
            time.sleep(1 / STREAM_FPS)

    def _write_mjpeg_frame(self, jpeg):
        self.wfile.write(b'--frame\r\n')
        self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
        self.wfile.write(jpeg)
        self.wfile.write(b'\r\n')
        self.wfile.flush()

    def handle_touch(self, query):
        params = parse_qs(query)
        action = params.get('a', ['tap'])[0]
        self.touch.submit(action, self._int_param(params, 'x'), self._int_param(params, 'y'))
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _int_param(params, key):
        try:
            return int(params.get(key, ['0'])[0])
        except ValueError:
            return 0

def parse_args():
    parser = argparse.ArgumentParser(description='Framebuffer HTTP Server')
    parser.add_argument('-p', '--port', type=int, default=8092, help='HTTP port')
    parser.add_argument('--bind', default='127.0.0.1', help='Bind address')
    parser.add_argument('--fb', default='/dev/fb0', help='Framebuffer device')
    parser.add_argument('--touch', default='/dev/input/event0', help='Touch input device')
    parser.add_argument(
        '--html-dir',
        default='/userdata/bespok3d/remote-screen/html',
        help='Path to HTML directory',
    )
    parser.add_argument('--trace', default='', help='Write injected-touch trace to this file')
    return parser.parse_args()


def make_tracer(path):
    if not path:
        return None
    handle = open(path, 'a', buffering=1)
    log(f"Touch trace -> {path}")
    return lambda line: handle.write(line + '\n')


def main():
    args = parse_args()
    fb = Framebuffer(args.fb)
    writer = EvdevWriter(args.touch, fb.width, fb.height, log)
    controller = TouchController(writer.emit, writer.scale, make_tracer(args.trace))
    GuiWatchdog(log)

    ScreenHandler.framebuffer = fb
    ScreenHandler.touch = controller
    ScreenHandler.html_dir = os.fspath(args.html_dir)

    server = ThreadingHTTPServer((args.bind, args.port), ScreenHandler)
    log_routes(args.bind, args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        fb.close()
        writer.close()


def log_routes(bind, port):
    log(f"Server running on http://{bind}:{port}")
    log("  GET  /snapshot.jpg - JPEG snapshot")
    log(f"  GET  /stream.mjpg  - MJPEG stream ({STREAM_FPS} fps)")
    log("  POST /touch?x=&y=  - Send touch event")

if __name__ == '__main__':
    main()
