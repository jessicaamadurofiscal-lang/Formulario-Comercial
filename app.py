"""
app.py — Servidor do Formulário Comercial S&C
Funciona local (python app.py) e no Render (PORT env var)
Compatível com Python 3.8–3.13+ (sem módulo cgi)
"""

import os, sys, json, threading, urllib.parse
import tempfile, subprocess, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE   = Path(__file__).parent
PORT   = int(os.environ.get("PORT", 5050))
RENDER = os.environ.get("RENDER", "false").lower() == "true"


def parse_multipart(rfile, content_type: str, content_length: int) -> dict:
    body = rfile.read(content_length)
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"').encode()
            break
    if not boundary:
        return {}
    fields = {}
    delimiter = b"--" + boundary
    for part in body.split(delimiter)[1:]:
        if part in (b"--\r\n", b"--", b"--\r\n--"):
            break
        sep = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
        if sep not in part:
            continue
        raw_headers, content = part.split(sep, 1)
        content = content.rstrip(b"\r\n")
        headers_str = raw_headers.decode("utf-8", errors="replace")
        m = re.search(r'name="([^"]+)"', headers_str)
        if m:
            fields[m.group(1)] = content
    return fields


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            print(f"  -> {args[0]} {args[1] if len(args) > 1 else ''}", flush=True)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            return self._json({"ok": True, "python": sys.version.split()[0]})
        if path in ("/", "/index.html"):
            return self._file(BASE / "public" / "index.html", "text/html; charset=utf-8")
        static = BASE / "public" / path.lstrip("/")
        if static.exists() and static.is_file():
            ext = static.suffix.lower()
            types = {".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",
                     ".gif":"image/gif",".svg":"image/svg+xml",".ico":"image/x-icon",
                     ".css":"text/css",".js":"application/javascript",
                     ".woff2":"font/woff2",".woff":"font/woff"}
            return self._file(static, types.get(ext, "application/octet-stream"))
        self._raw(404, b"Not found")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/extrair":
            self._extrair()
        else:
            self._raw(404, b"Not found")

    def _extrair(self):
        ct = self.headers.get("Content-Type", "")
        cl = int(self.headers.get("Content-Length", 0))
        if "multipart/form-data" not in ct:
            return self._json({"erro": "Envie um PDF via multipart/form-data."}, 400)
        fields = parse_multipart(self.rfile, ct, cl)
        arquivo = fields.get("contrato")
        if not arquivo:
            return self._json({"erro": "Nenhum arquivo recebido."}, 400)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(arquivo)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [sys.executable, str(BASE / "extrator.py"), tmp_path],
                capture_output=True, text=True, timeout=120
            )
            raw = result.stdout.strip()
            if not raw:
                return self._json({"erro": result.stderr[:500] or "Extrator sem saida."}, 500)
            dados = json.loads(raw)
            if "erro" not in dados:
                dados = _limpar(dados)
            self._json({"ok": True, "data": dados})
        except json.JSONDecodeError as e:
            self._json({"erro": f"Falha ao interpretar resultado: {e}"}, 500)
        except Exception as e:
            self._json({"erro": str(e)}, 500)
        finally:
            try: os.unlink(tmp_path)
            except: pass

    def _file(self, path: Path, ct: str):
        if not path.exists():
            return self._raw(404, b"Not found")
        self._raw(200, path.read_bytes(), ct)

    def _json(self, obj: dict, status=200):
        self._raw(status, json.dumps(obj, ensure_ascii=False).encode(),
                  "application/json; charset=utf-8")

    def _raw(self, status: int, body: bytes, ct="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def _limpar(d: dict) -> dict:
    prefixos = [
        r'^(?:dele?|dela|do|da|de|que)\s*[:\-]?\s*',
        r'^\s*\(Ate \d+ (?:Meses?|Ano)\)\s*[:\-]?\s*',
        r'^\s*para o Cliente\s*[:\-]?\s*',
        r'^\s*\(Camisa 10\)\s*[:\-]?\s*',
        r'^\s*Responsavel?\s*[:\-]?\s*',
        r'^\s*\?\s*',
    ]
    out = {}
    for k, v in d.items():
        if isinstance(v, str) and v:
            for p in prefixos:
                v = re.sub(p, '', v, flags=re.IGNORECASE).strip()
            v = v.strip(' ,;:-')
        out[k] = v
    return out


def _instalar_deps_local():
    packs = []
    try: import pdfplumber
    except ImportError: packs.append("pdfplumber")
    try: from pypdf import PdfReader
    except ImportError: packs.append("pypdf")
    try: from PIL import Image
    except ImportError: packs.append("Pillow")
    try: import pytesseract
    except ImportError: packs.append("pytesseract")
    if packs:
        print(f"  Instalando: {', '.join(packs)}...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install"] + packs,
                       check=True, capture_output=True)
        print("  OK!\n", flush=True)


def main():
    print("\n" + "="*50, flush=True)
    print("  FORMULARIO COMERCIAL - SOUSA & COUTO", flush=True)
    print("="*50, flush=True)
    print(f"  Python : {sys.version.split()[0]}", flush=True)
    print(f"  Porta  : {PORT}", flush=True)
    print(f"  Modo   : {'Render (nuvem)' if RENDER else 'Local'}", flush=True)

    if not RENDER:
        print("  Verificando dependencias...", flush=True)
        _instalar_deps_local()
        print(f"  Acesse  : http://localhost:{PORT}", flush=True)
        def _abrir():
            import time, webbrowser
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{PORT}")
        threading.Thread(target=_abrir, daemon=True).start()
    else:
        print("  Servidor publico no ar!", flush=True)

    print("="*50 + "\n", flush=True)
    host = "0.0.0.0" if RENDER else "localhost"
    try:
        HTTPServer((host, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor encerrado.", flush=True)


if __name__ == "__main__":
    main()
