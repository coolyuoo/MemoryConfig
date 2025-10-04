from flask import Flask, request, jsonify
import threading

app = Flask(__name__)

# 全域記憶體池：用很多小 chunk 組成，避免一次性大塊分配失敗
_mem_lock = threading.Lock()
_chunks = []            # 例如 [[bytearray(...), ...], [bytearray(...), ...]]
CHUNK_MB_DEFAULT = 8    # 每塊 8MB，避免一次塞太大

def _alloc_mb(mb: int, chunk_mb: int = CHUNK_MB_DEFAULT):
    blocks = []
    remain = mb
    while remain > 0:
        take = min(chunk_mb, remain)
        blocks.append(bytearray(take * 1024 * 1024))
        remain -= take
    return blocks

def _current_mb():
    # 估算目前總配額（以我們的切塊大小為準）
    return sum(len(b) for group in _chunks for b in group) // (1024 * 1024)

@app.get("/")
def mem_status():
    with _mem_lock:
        return jsonify(
            allocated_mb=_current_mb(),
            groups=len(_chunks),
            tip="搭配 docker stats 觀察容器 RSS/使用率"
        )

@app.post("/mem/add")
def mem_add():
    """追加配額：/mem/add?mb=300&chunk=8"""
    try:
        mb = int(request.args.get("mb", "100"))
        chunk = int(request.args.get("chunk", str(CHUNK_MB_DEFAULT)))
        if mb <= 0 or chunk <= 0:
            return jsonify(error="mb/chunk 必須 > 0"), 400
        # 安全上限（避免誤觸太大，自己調整）
        if mb > 4096:
            return jsonify(error="單次追加上限 4096MB，可自行放寬"), 400
    except ValueError:
        return jsonify(error="參數需為整數"), 400

    blocks = _alloc_mb(mb, chunk)
    with _mem_lock:
        _chunks.append(blocks)
        total = _current_mb()
    return jsonify(ok=True, added_mb=mb, chunk_mb=chunk, total_mb=total)

@app.post("/mem/set")
def mem_set():
    """設定目標總量：/mem/set?mb=600"""
    try:
        target = int(request.args.get("mb", "0"))
        if target < 0:
            return jsonify(error="mb 必須 >= 0"), 400
    except ValueError:
        return jsonify(error="參數需為整數"), 400

    with _mem_lock:
        curr = _current_mb()
        if target == curr:
            return jsonify(ok=True, total_mb=curr, note="已達目標")
        elif target > curr:
            blocks = _alloc_mb(target - curr, CHUNK_MB_DEFAULT)
            _chunks.append(blocks)
        else:
            # 釋放到接近 target：從最後一組開始丟
            to_free = curr - target
            while to_free > 0 and _chunks:
                group = _chunks[-1]
                while group and to_free > 0:
                    b = group.pop()
                    to_free -= len(b) // (1024 * 1024)
                if not group:
                    _chunks.pop()
        total = _current_mb()
    return jsonify(ok=True, total_mb=total)

@app.post("/mem/free")
def mem_free():
    """釋放指定量：/mem/free?mb=200"""
    try:
        mb = int(request.args.get("mb", "0"))
        if mb <= 0:
            return jsonify(error="mb 必須 > 0"), 400
    except ValueError:
        return jsonify(error="參數需為整數"), 400

    with _mem_lock:
        remain = mb
        while remain > 0 and _chunks:
            group = _chunks[-1]
            while group and remain > 0:
                b = group.pop()
                remain -= len(b) // (1024 * 1024)
            if not group:
                _chunks.pop()
        total = _current_mb()
    return jsonify(ok=True, freed_request_mb=mb, total_mb=total)

@app.post("/mem/clear")
def mem_clear():
    """釋放全部：/mem/clear"""
    with _mem_lock:
        _chunks.clear()
        total = _current_mb()
    return jsonify(ok=True, total_mb=total)

@app.get("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    # threaded=True 讓請求可同時來；debug=False 避免 reloader 造成雙進程
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
