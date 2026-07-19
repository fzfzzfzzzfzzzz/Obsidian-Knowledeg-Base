"""原子写 + 文件锁(v0.4.5)。

原子写:write_text 用临时文件 + os.replace,并发读不会读到截断内容。
文件锁:_file_lock 跨平台(Unix fcntl / Windows msvcrt),串行化 read-modify-write。
"""
import threading
import time
from pathlib import Path

import kb


# —— 原子写 ——

def test_atomic_write_basic(tmp_path):
    """write_text 正常写入。"""
    p = tmp_path / "f.txt"
    kb.write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"


def test_atomic_write_overwrites(tmp_path):
    """覆写旧文件正常。"""
    p = tmp_path / "f.txt"
    kb.write_text(p, "old")
    kb.write_text(p, "new content")
    assert p.read_text(encoding="utf-8") == "new content"


def test_atomic_write_no_tmp_leftover(tmp_path):
    """写入后不留临时文件残留。"""
    p = tmp_path / "f.txt"
    kb.write_text(p, "x")
    tmps = list(tmp_path.glob("*.tmp_*"))
    assert tmps == [], f"残留临时文件: {tmps}"


def test_atomic_write_creates_parent(tmp_path):
    """自动创建父目录。"""
    p = tmp_path / "deep" / "nested" / "f.txt"
    kb.write_text(p, "x")
    assert p.read_text(encoding="utf-8") == "x"


def test_atomic_write_failure_no_corrupt(tmp_path, monkeypatch):
    """写入失败时不污染原文件(原子性)。

    模拟 os.replace 抛错,验证原文件内容不变。
    """
    p = tmp_path / "f.txt"
    kb.write_text(p, "original")

    # 让 os.replace 抛错
    real_replace = kb.os.replace

    def boom(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(kb.os, "replace", boom)
    try:
        try:
            kb.write_text(p, "should not be written")
            assert False, "应该抛 OSError"
        except OSError:
            pass
    finally:
        monkeypatch.setattr(kb.os, "replace", real_replace)

    # 原文件应保持不变
    assert p.read_text(encoding="utf-8") == "original"


# —— 文件锁 ——

def test_file_lock_serializes_concurrent(tmp_path):
    """两个线程抢同一锁:第二个必须等第一个释放。"""
    lock = tmp_path / "test.lock"
    events = []

    def worker(name, hold_sec):
        with kb._file_lock(lock, timeout=5):
            t = time.monotonic()
            events.append((name, "acquired", t))
            time.sleep(hold_sec)
            events.append((name, "released", time.monotonic()))

    t1 = threading.Thread(target=worker, args=("A", 0.2))
    t2 = threading.Thread(target=worker, args=("B", 0.05))
    t1.start()
    time.sleep(0.02)  # 让 A 先拿到
    t2.start()
    t1.join()
    t2.join()

    # 找到 A acquired 和 B acquired 的时间
    a_acq = next(e[2] for e in events if e[0] == "A" and e[1] == "acquired")
    b_acq = next(e[2] for e in events if e[0] == "B" and e[1] == "acquired")
    a_rel = next(e[2] for e in events if e[0] == "A" and e[1] == "released")

    # B 必须在 A 释放之后才拿到
    assert b_acq >= a_rel - 0.01, f"B 在 A 释放前就拿到锁了!A_rel={a_rel}, B_acq={b_acq}"


def test_file_lock_timeout_raises(tmp_path):
    """锁被占时,超时应抛 TimeoutError。"""
    lock = tmp_path / "test.lock"
    barrier = threading.Event()
    release = threading.Event()

    def hold():
        with kb._file_lock(lock, timeout=1):
            barrier.set()
            release.wait(timeout=2)

    holder = threading.Thread(target=hold)
    holder.start()
    barrier.wait(timeout=1)

    # 第二个请求短超时
    try:
        with kb._file_lock(lock, timeout=0.3):
            assert False, "应该超时"
    except TimeoutError as e:
        assert "超时" in str(e) or "timeout" in str(e).lower()
    finally:
        release.set()
        holder.join()


def test_file_lock_releases_on_exception(tmp_path):
    """with 内抛异常时锁应被释放(下次能再拿)。"""
    lock = tmp_path / "test.lock"
    try:
        with kb._file_lock(lock, timeout=1):
            raise ValueError("simulated error")
    except ValueError:
        pass

    # 应能再次获取(说明上次的锁已释放)
    with kb._file_lock(lock, timeout=1):
        pass


def test_file_lock_creates_parent_dir(tmp_path):
    """锁文件的父目录自动创建。"""
    lock = tmp_path / "deep" / "nested" / "test.lock"
    with kb._file_lock(lock, timeout=1):
        pass
    assert lock.parent.exists()
