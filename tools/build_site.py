#!/usr/bin/env python3
"""Build the friends' website from the planner page and its public data.

Usage: build_site.py --page PAGE.html --data DATA_DIR --assets ASSET_DIR --out OUT_DIR [--password PW]
Reads the planner page, DATA_DIR/<collection>/<doc>.json and ASSET_DIR/<asset>.jpg (only needed for photos
not yet on the site: existing OUT_DIR/img/<asset>.bin files are kept as they are)
Writes OUT_DIR/index.html (+ img/<asset>.bin, robots.txt). With a password,
the page and every photo are AES-GCM encrypted (key from PBKDF2-SHA256).
"""
import base64, glob, gzip, io, json, os, sys
from PIL import Image, ImageOps
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

HERE = os.path.dirname(os.path.abspath(__file__))
arg = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
OUT, PW = arg("--out"), arg("--password")
PAGE, DATA, ASSETS = arg("--page"), arg("--data"), arg("--assets", "assets")
ITER = 250000
COLLS = ["public", "tracks", "j1tracks", "j3tracks", "weather", "j1weather", "j3weather"]

page = open(PAGE, encoding="utf-8").read()
store = {}
for c in COLLS:
    for fp in sorted(glob.glob(os.path.join(DATA, c, "*.json"))):
        d = json.load(open(fp, encoding="utf-8"))
        store[f"{c}/{os.path.basename(fp)[:-5]}"] = d.get("data", d) if isinstance(d, dict) and set(d) >= {"data", "id"} else d
# photos friends may see = those in the public docs
assets = sorted({p["asset"] for k, v in store.items() if k.startswith("public/") for p in (v.get("photos") or [])})

shim = r"""<script>
(function(){const STORE=%s;
const snap=(p)=>({id:p.split("/").pop(),exists:p in STORE,data:()=>STORE[p],metadata:{}});
const db={collection:(c)=>({onSnapshot:(n)=>{setTimeout(()=>{const ks=Object.keys(STORE).filter(k=>k.startsWith(c+"/"));n({docs:ks.map(snap),size:ks.length,empty:!ks.length,docChanges:()=>[]})},0);return()=>{}},doc:(id)=>db.doc(c+"/"+id)}),
doc:(p)=>({get:async()=>snap(p),onSnapshot:(n)=>{setTimeout(()=>n(snap(p)),0);return()=>{}},set:async()=>{},update:async()=>{},delete:async()=>{}})};
window.claude={use:async(n)=>n==="db"?db:(n==="user"?{can:async()=>false,canEdit:async()=>false}:null)};
const BLANK="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",cache={},busy={};
const fix=()=>{document.querySelectorAll('img[src*="#a="],image[href*="#a="],[style*="#a="]').forEach((el)=>{
  for(const at of ["src","href","style"]){const v=el.getAttribute(at);if(!v||!v.includes("#a="))continue;
    const m=v.match(/data:image\/gif;base64,[A-Za-z0-9+\/=]+#a=([0-9a-f]+)/);if(m&&cache[m[1]])el.setAttribute(at,v.split(m[0]).join(cache[m[1]]));}});};
async function load(a){if(busy[a])return;busy[a]=1;try{const r=await fetch("img/"+a+".bin");const b=new Uint8Array(await r.arrayBuffer());
  const raw=window.__KEY?await crypto.subtle.decrypt({name:"AES-GCM",iv:b.slice(0,12)},window.__KEY,b.slice(12)):b;
  cache[a]=URL.createObjectURL(new Blob([raw],{type:"image/jpeg"}));fix();}catch(e){busy[a]=0;}}
window.__pic=(a)=>{if(cache[a])return cache[a];load(a);return BLANK+"#a="+a;};
let t=0;new MutationObserver(()=>{if(!t)t=setTimeout(()=>{t=0;fix();},30);}).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:["src","href","style"]});
})();
</script>""" % json.dumps(store, ensure_ascii=False)

inner = ('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<meta name="robots" content="noindex,nofollow"><title>Zu Fuss durch Japan</title><link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png"><link rel="apple-touch-icon" href="apple-touch-icon.png"><link rel="manifest" href="manifest.webmanifest"><meta name="apple-mobile-web-app-title" content="Japan zu Fuss"><meta name="theme-color" content="#EEEDE8" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#13161B" media="(prefers-color-scheme: dark)"></head><body>' + shim + page + "</body></html>")

import hashlib
digest = hashlib.sha256((inner + "|" + " ".join(assets) + "|" + (PW or "") + "|" + open(os.path.join(HERE, "loader.html"), encoding="utf-8").read()).encode()).hexdigest()
hp = os.path.join(OUT, ".build-hash")
if os.path.exists(hp) and open(hp).read().strip() == digest and os.path.exists(os.path.join(OUT, "index.html")) and all(os.path.exists(os.path.join(OUT, "img", a + ".bin")) for a in assets):
    print("unchanged: nothing to publish"); sys.exit(0)
os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
for old in glob.glob(os.path.join(OUT, "img", "*.bin")):
    if os.path.basename(old)[:-4] not in assets: os.remove(old)

key = salt = None
if PW:
    salt = b"sanyodo-friends-v1"  # fixed salt so a remembered key keeps working across rebuilds
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(PW.strip().lower().encode())
def enc(data):
    if not key: return data
    iv = os.urandom(12); return iv + AESGCM(key).encrypt(iv, data, None)

missing = []
for a in assets:
    dst = os.path.join(OUT, "img", a + ".bin")
    if os.path.exists(dst): continue
    src = os.path.join(ASSETS, a + ".jpg")
    if not os.path.exists(src): missing.append(a); continue
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB"); im.thumbnail((1600, 1600))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    open(dst, "wb").write(enc(buf.getvalue()))

if not key:
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(inner)
else:
    blob = base64.b64encode(enc(gzip.compress(inner.encode("utf-8"), 9))).decode()
    loader = open(os.path.join(HERE, "loader.html"), encoding="utf-8").read()
    loader = loader.replace("__SALT__", base64.b64encode(salt).decode()).replace("__ITER__", str(ITER)).replace("__BLOB__", blob)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(loader)
open(hp, "w").write(digest + "\n")
open(os.path.join(OUT, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")
open(os.path.join(OUT, ".nojekyll"), "w").write("")
print("built", OUT, "photos", len(assets), "index", os.path.getsize(os.path.join(OUT, "index.html")))
if missing: print("MISSING photo files (download these assets, then rebuild):", " ".join(missing)); sys.exit(2)
