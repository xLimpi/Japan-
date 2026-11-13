#!/usr/bin/env python3
"""Build the friends' website from the planner page and its public data.

Usage: build_site.py --out OUT_DIR [--password PW] [--bundle BUNDLE.png] [--page PAGE.html] [--data DATA_DIR] [--assets ASSET_DIR]

Everything except --out is optional: whatever is not given is taken from the site already in OUT_DIR
(its index.html is decrypted with the password and the page and data inside are reused).
  --bundle  the planner's "site bundle" asset (a PNG that carries the public data as bytes; its asset id is
            in the planner database, document public/bundle, field "asset"). Replaces the current journey's data.
  --bundle-key  the "key" field of public/bundle; stored in OUT_DIR/.bundle-key once the site holds that
            bundle, so the next run can stop early when the key has not changed.
  --page    the planner page (index.html of the artifact). Only needed when the page itself changed.
  --data    DATA_DIR/<collection>/<doc>.json files; these override single documents.
  --assets  ASSET_DIR/<asset id>.jpg (any image extension works) for photos not yet on the site;
            existing OUT_DIR/img/<asset>.bin files are kept as they are.
Exit codes: 0 built or unchanged, 2 photos missing (download them, run again), 3 bundle unreadable.
Writes OUT_DIR/index.html (+ img/<asset>.bin, robots.txt). With a password,
the page and every photo are AES-GCM encrypted (key from PBKDF2-SHA256).
"""
import base64, glob, gzip, io, json, os, re, struct, sys, zlib
try:
    from PIL import Image, ImageOps
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
except ImportError as e:
    sys.exit(f"Missing Python package ({e}). Run: pip install pillow cryptography --break-system-packages")

HERE = os.path.dirname(os.path.abspath(__file__))
arg = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
OUT, PW = arg("--out"), arg("--password")
PAGE, DATA, ASSETS, BUNDLE, BKEY = arg("--page"), arg("--data"), arg("--assets", "assets"), arg("--bundle"), arg("--bundle-key")
def keep_key():
    if BKEY and BUNDLE: open(os.path.join(OUT, ".bundle-key"), "w").write(BKEY.strip() + "\n")
SALT = b"sanyodo-friends-v1"  # fixed salt so a remembered key keeps working across rebuilds
ITER = 250000
COLLS = ["public", "tracks", "j1tracks", "j3tracks", "weather", "j1weather", "j3weather"]

def derive(pw): return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=ITER).derive(pw.strip().lower().encode())
TAIL = "</body></html>"
def previous():
    """Page and data of the site that is already in OUT (None, {} when there is none)."""
    fp = os.path.join(OUT, "index.html")
    if not os.path.exists(fp): return None, {}
    html = open(fp, encoding="utf-8").read()
    m = re.search(r'BLOB = "([A-Za-z0-9+/=]+)"', html)
    if m:
        if not PW: sys.exit("The existing site is encrypted: pass --password to reuse it.")
        raw = base64.b64decode(m.group(1))
        try: html = gzip.decompress(AESGCM(derive(PW)).decrypt(raw[:12], raw[12:], None)).decode("utf-8")
        except Exception: sys.exit("Could not decrypt the existing site with this password.")
    a = html.find("(function(){const STORE=")
    if a < 0: return None, {}
    a += len("(function(){const STORE="); b = html.index(";\nconst snap=", a); c = html.index("</script>", b) + len("</script>")
    return html[c:html.rindex(TAIL)], json.loads(html[a:b])
def read_bundle(fp):
    """The planner packs its public data into a PNG: 'SYB1', length, CRC-32, then the JSON bytes as RGB pixels."""
    try:
        raw = Image.open(fp).convert("RGB").tobytes()
        if raw[:4] != b"SYB1": raise ValueError("not a site bundle")
        n, crc = struct.unpack(">II", raw[4:12]); data = raw[12:12 + n]
        if len(data) != n or zlib.crc32(data) != crc: raise ValueError("checksum mismatch")
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        print("BUNDLE unreadable:", e); sys.exit(3)

prev_page, store = previous()
page = open(PAGE, encoding="utf-8").read() if PAGE else prev_page
if page is None: sys.exit("No page: pass --page, or run against an OUT_DIR that already holds the site.")
if BUNDLE:
    b = read_bundle(BUNDLE)
    for k in [k for k in store if k.split("/")[0] in ("tracks", "weather")]: del store[k]
    for name, doc in (b.get("public") or {}).items(): store[f"public/{name}"] = doc
    for c in ("tracks", "weather"):
        for name, doc in (b.get(c) or {}).items(): store[f"{c}/{name}"] = doc
    print("bundle:", b.get("updatedAt"), "| days done:", sum(1 for d in (store.get("public/trip", {}).get("days") or []) if d.get("done")), "| photos:", len(store.get("public/trip", {}).get("photos") or []), "| tracks:", len(b.get("tracks") or {}))
for c in COLLS if DATA else []:
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
         '<meta name="robots" content="noindex,nofollow"><title>Zu Fuss durch Japan</title><link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png"><link rel="apple-touch-icon" href="apple-touch-icon.png"><link rel="manifest" href="manifest.webmanifest"><meta name="apple-mobile-web-app-title" content="Japan zu Fuss"><meta name="theme-color" content="#EEEDE8" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#13161B" media="(prefers-color-scheme: dark)"></head><body>' + shim + page + TAIL)

import hashlib
digest = hashlib.sha256((inner + "|" + " ".join(assets) + "|" + (PW or "") + "|" + open(os.path.join(HERE, "loader.html"), encoding="utf-8").read()).encode()).hexdigest()
hp = os.path.join(OUT, ".build-hash")
if os.path.exists(hp) and open(hp).read().strip() == digest and os.path.exists(os.path.join(OUT, "index.html")) and all(os.path.exists(os.path.join(OUT, "img", a + ".bin")) for a in assets):
    keep_key(); print("unchanged: nothing to publish"); sys.exit(0)
os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
for old in glob.glob(os.path.join(OUT, "img", "*.bin")):
    if os.path.basename(old)[:-4] not in assets: os.remove(old)

key = salt = None
if PW:
    salt = SALT
    key = derive(PW)
def enc(data):
    if not key: return data
    iv = os.urandom(12); return iv + AESGCM(key).encrypt(iv, data, None)

missing = []
for a in assets:
    dst = os.path.join(OUT, "img", a + ".bin")
    if os.path.exists(dst): continue
    src = next(iter(sorted(glob.glob(os.path.join(ASSETS, a + ".*")))), None)
    if not src: missing.append(a); continue
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
keep_key()
