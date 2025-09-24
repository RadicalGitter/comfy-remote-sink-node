# remote_sink.py — adds /remote/save endpoint that writes PNG bytes to ./remote_results
import os, base64, io, re
from PIL import Image
from aiohttp import web

OUT_DIR = os.path.abspath("./remote_results")
os.makedirs(OUT_DIR, exist_ok=True)

def setup_remote_sink(app):
    async def save_handler(request):
        try:
            data = await request.json()
            imgs = data.get("images", [])
            saved = []
            for i, item in enumerate(imgs):
                b64 = item.get("b64")
                if not b64:
                    continue
                raw = base64.b64decode(b64)
                name = item.get("name") or f"remote_{i}.png"
                name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
                path = os.path.join(OUT_DIR, name)
                img = Image.open(io.BytesIO(raw))
                img.save(path, format="PNG")
                saved.append({"path": path})
            return web.json_response({"saved": saved})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
    app.router.add_post("/remote/save", save_handler)

NODE_CLASS_MAPPINGS = {}
WEB_DIRECTORY = None
def init():
    try:
        from server import PromptServer
        PromptServer.instance.app.on_startup.append(lambda app: setup_remote_sink(PromptServer.instance.app))
    except Exception:
        pass
