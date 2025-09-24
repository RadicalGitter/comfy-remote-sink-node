# worker.py — repo-list ensure+prune + run (HTTP/Civitai origins)
import base64, os, time, uuid, requests, runpod, subprocess, re, hashlib

COMFY = f"http://127.0.0.1:{os.getenv('COMFY_PORT','8188')}"
POLL = 0.5
WORKDIR = os.getenv("WORKDIR", "/workspace")
MODELS_DIR = os.getenv("MODELS_DIR", f"{WORKDIR}/models")
OUTPUT_DIR = os.path.abspath(os.getenv("COMFY_OUTPUT_DIR", f"{WORKDIR}/ComfyUI/output"))

KIND_TO_SUBDIR = {
    "ckpt":"checkpoints","checkpoint":"checkpoints","lora":"loras","vae":"vae",
    "controlnet":"controlnet","upscale":"upscale_models","clip_vision":"clip_vision",
    "text_encoder":"text_encoders","other":""
}

CIV_PAT = re.compile(r"civitai\.com/.*/models/(\d+)|civitai\.com/api/download/models/(\d+)", re.I)

def _subdir(kind): return KIND_TO_SUBDIR.get(kind.lower(), "")
def _run(cmd): return subprocess.run(cmd, shell=True, check=False)
def _sha1(s: str) -> str: 
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def _fetch_url(url, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    cmd = f'aria2c -x 8 -s 8 -k 1M -o "{os.path.basename(dst)}" -d "{os.path.dirname(dst)}" "{url}"'
    r = _run(cmd)
    if r.returncode != 0:
        _run(f'curl -L "{url}" -o "{dst}"')

def _dest_from_link(kind, link: str) -> str:
    sd = _subdir(kind)
    os.makedirs(os.path.join(MODELS_DIR, sd), exist_ok=True)
    m = CIV_PAT.search(link)
    if m:
        vid = m.group(1) or m.group(2)
        return os.path.join(MODELS_DIR, sd, f"civ-{vid}.safetensors")
    return os.path.join(MODELS_DIR, sd, f"url-{_sha1(link)}.safetensors")

def _ensure_from_link(kind, link):
    dst = _dest_from_link(kind, link)
    if os.path.exists(dst): return dst, False
    if CIV_PAT.search(link) and "civitai.com/api/download/models/" not in link:
        vid = CIV_PAT.search(link).group(1) or CIV_PAT.search(link).group(2)
        link = f"https://civitai.com/api/download/models/{vid}"
    _fetch_url(link, dst)
    return dst, True

def _parse_repo_list(repo_list_text: str):
    items = []
    for line in (repo_list_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = re.split(r"\s+", line, maxsplit=1)
        if len(parts) == 1:
            kind, link = "ckpt", parts[0]
        else:
            kind, link = parts[0].lower(), parts[1]
        items.append({"kind": kind, "link": link})
    return items

def _whitelist_paths(repo_items):
    wl = set()
    for it in repo_items:
        wl.add(_dest_from_link(it["kind"], it["link"]))
    return wl

def ensure_and_prune(repo_list_text: str):
    repo_items = _parse_repo_list(repo_list_text)
    want = _whitelist_paths(repo_items)
    ensured = []
    for it in repo_items:
        dst, downloaded = _ensure_from_link(it["kind"], it["link"])
        ensured.append({"kind": it["kind"], "dst": dst, "downloaded": downloaded})
    pruned = []
    for root, _, files in os.walk(MODELS_DIR):
        for f in files:
            if not f.endswith(".safetensors"): continue
            p = os.path.join(root, f)
            if p not in want:
                try: os.remove(p); pruned.append(p)
                except Exception: pass
    return {"ensured": ensured, "pruned": pruned}

def _inject_prefix(prompt_json, prefix):
    for _, node in (prompt_json.get("nodes") or {}).items():
        if node.get("class_type") == "SaveImage":
            inputs = node.setdefault("inputs", {})
            old = inputs.get("filename_prefix", "ComfyUI")
            inputs["filename_prefix"] = f"{prefix}_{old}"
    return prompt_json

def _collect_output_files(prefix):
    if not os.path.isdir(OUTPUT_DIR): return []
    return [os.path.join(OUTPUT_DIR, n) for n in os.listdir(OUTPUT_DIR) if n.startswith(prefix)]

def run_prompt(prompt):
    req_prefix = f"job_{uuid.uuid4().hex[:8]}"
    prompt = _inject_prefix(prompt, req_prefix)
    r = requests.post(f"{COMFY}/prompt", json=prompt, timeout=60); r.raise_for_status()
    pid = r.json()["prompt_id"]
    while True:
        h = requests.get(f"{COMFY}/history/{pid}", timeout=60).json()
        if pid in h and "outputs" in h[pid]: break
        time.sleep(POLL)
    images_b64 = []
    try:
        for node_out in h[pid]["outputs"].values():
            for img in node_out.get("images", []):
                url = f"{COMFY}/view?filename={img['filename']}&subfolder={img['subfolder']}&type={img['type']}"
                data = requests.get(url, timeout=120).content
                images_b64.append({"b64": base64.b64encode(data).decode("utf-8")})
    finally:
        for p in _collect_output_files(req_prefix):
            try: os.remove(p)
            except Exception: pass
    return {"images": images_b64}

def handler(event):
    inp = event.get("input", {})
    repo_list = inp.get("repo_list", "")
    action = (inp.get("action") or "run").lower()
    if repo_list:
        ensure_and_prune(repo_list)
    if action == "run":
        prompt = inp.get("prompt")
        if not isinstance(prompt, dict):
            return {"error": "input.prompt (ComfyUI API prompt JSON) required"}
        return run_prompt(prompt)
    if action == "ensure":
        return ensure_and_prune(repo_list)
    if action == "check":
        items = _parse_repo_list(repo_list)
        want = sorted(list(_whitelist_paths(items)))
        return {"would_keep": want}
    return {"error": f"unknown action '{action}'"}

runpod.serverless.start({"handler": handler})
