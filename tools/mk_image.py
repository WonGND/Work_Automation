# 도커 이미지(.tar)를 도커 없이 만듦 — 시놀로지 Container Manager '이미지 > 추가 > 파일에서 추가'로 불러옴
# 사용: python3 mk_image.py <리눅스 실행파일> <seed.json> <out.tar> <태그 예: workmgmt:0.4.0>
import sys, tarfile, io, json, hashlib, os, time
BIN, SEED, OUT, TAG = sys.argv[1:5]
LIBS = ["/lib64/ld-linux-x86-64.so.2", "/lib/x86_64-linux-gnu/libc.so.6", "/lib/x86_64-linux-gnu/libpthread.so.0", "/lib/x86_64-linux-gnu/libdl.so.2", "/lib/x86_64-linux-gnu/libm.so.6"]
MT = int(time.time())
def add_dir(t, name, mode=0o755):
    ti = tarfile.TarInfo(name); ti.type = tarfile.DIRTYPE; ti.mode = mode; ti.mtime = MT; t.addfile(ti)
def add_bytes(t, name, data, mode=0o644):
    ti = tarfile.TarInfo(name); ti.size = len(data); ti.mode = mode; ti.mtime = MT; t.addfile(ti, io.BytesIO(data))
def add_link(t, name, target):
    ti = tarfile.TarInfo(name); ti.type = tarfile.SYMTYPE; ti.linkname = target; ti.mtime = MT; t.addfile(ti)
layer = io.BytesIO()
with tarfile.open(fileobj=layer, mode="w", format=tarfile.GNU_FORMAT) as t:
    for d in ["app", "data", "keys", "tmp", "etc", "lib", "lib/x86_64-linux-gnu", "lib64", "usr", "usr/share", "usr/share/zoneinfo", "usr/share/zoneinfo/Asia", "proc", "sys", "dev"]:
        add_dir(t, d, 0o1777 if d == "tmp" else 0o755)
    for L in LIBS: add_bytes(t, L.lstrip("/"), open(os.path.realpath(L), "rb").read(), 0o755)
    add_bytes(t, "usr/share/zoneinfo/Asia/Seoul", open("/usr/share/zoneinfo/Asia/Seoul", "rb").read())
    add_link(t, "etc/localtime", "/usr/share/zoneinfo/Asia/Seoul")
    add_bytes(t, "etc/passwd", b"root:x:0:0:root:/root:/sbin/nologin\n")
    add_bytes(t, "etc/group", b"root:x:0:\n")
    add_bytes(t, "etc/nsswitch.conf", b"hosts: files dns\n")
    add_bytes(t, "app/workmgmt", open(BIN, "rb").read(), 0o755)
    add_bytes(t, "app/seed.json", open(SEED, "rb").read())
lb = layer.getvalue(); diff = hashlib.sha256(lb).hexdigest()
cfg = {"architecture": "amd64", "os": "linux", "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(MT)),
  "config": {"Env": ["PATH=/app", "TZ=Asia/Seoul", "LANG=C.UTF-8", "WL_DATA=/data", "WL_KEY_FILE=/keys/secret.key", "WL_SELF_SIGNED=1", "WL_HTTP_PORT=8000"],
             "Entrypoint": ["/app/workmgmt"], "Cmd": ["--port", "8443"], "WorkingDir": "/app",
             "ExposedPorts": {"8443/tcp": {}, "8000/tcp": {}}, "Volumes": {"/data": {}, "/keys": {}},
             "Labels": {"org.opencontainers.image.title": "회로팀 업무관리", "org.opencontainers.image.version": TAG.split(":")[-1]}},
  "rootfs": {"type": "layers", "diff_ids": ["sha256:" + diff]},
  "history": [{"created_by": "mk_image.py: 업무관리 실행파일 + glibc + Asia/Seoul 시간대"}]}
cb = json.dumps(cfg, ensure_ascii=False).encode(); ch = hashlib.sha256(cb).hexdigest()
with tarfile.open(OUT, "w") as o:
    add_bytes(o, f"{diff}/layer.tar", lb); add_bytes(o, f"{diff}/VERSION", b"1.0")
    add_bytes(o, f"{ch}.json", cb)
    add_bytes(o, "manifest.json", json.dumps([{"Config": f"{ch}.json", "RepoTags": [TAG], "Layers": [f"{diff}/layer.tar"]}]).encode())
    add_bytes(o, "repositories", json.dumps({TAG.split(":")[0]: {TAG.split(":")[1]: diff}}).encode())
print("이미지", OUT, os.path.getsize(OUT) // 1024 // 1024, "MB · 레이어", diff[:12])
