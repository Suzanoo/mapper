# -*- coding: utf-8 -*-
"""Single-writer working files. Replacement is the commit boundary."""
from __future__ import unicode_literals
import copy
import hashlib
import json
import os
import sys
import uuid
from . import core
from .p6 import MappingError

MAX_BYTES = 64 * 1024 * 1024


def payload(value):
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise MappingError('Working/export file exceeds the 64 MiB pilot limit.')
    return data


def _pairs(rows):
    result = {}
    for k, v in rows:
        if k in result:
            raise MappingError('Duplicate JSON field: ' + k)
        result[k] = v
    return result


def read(path):
    with open(path, 'rb') as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise MappingError('File exceeds the 64 MiB pilot limit.')
    try:
        obj = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_pairs,
                         parse_constant=lambda x: (_ for _ in ()).throw(MappingError('Invalid JSON number: ' + x)))
    except (ValueError, UnicodeError) as ex:
        raise MappingError('Cannot read mapping JSON: %s' % ex)
    return obj, hashlib.sha256(data).hexdigest()


class FileLock(object):
    """OS-held lock, released after process exit. The marker file may remain."""
    def __init__(self, path):
        self.handle = None
        self.path = path + '.lock'
        try:
            if sys.platform == 'cli':
                from System.IO import FileStream, FileMode, FileAccess, FileShare
                self.handle = FileStream(self.path, FileMode.OpenOrCreate, FileAccess.ReadWrite, getattr(FileShare, "None"))
                self.kind = 'dotnet'
            else:
                self.handle = open(self.path, 'a+b')
                if os.name == 'nt':
                    import msvcrt
                    self.handle.seek(0)
                    if not self.handle.read(1):
                        self.handle.write(b'0'); self.handle.flush()
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                    self.kind = 'windows'
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.kind = 'posix'
        except Exception as ex:
            if self.handle is not None:
                try:
                    self.handle.close()
                except Exception:
                    pass
            self.handle = None
            raise MappingError('Cannot acquire writer lock. Close the other Mapping window/process '
                               'or check folder permissions. Do not delete live lock files. Details: %s' % ex)

    def close(self):
        if self.handle is None:
            return
        if self.kind == 'dotnet':
            self.handle.Dispose()
        else:
            if self.kind == 'windows':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()
        self.handle = None


def _temp_write(path, data):
    temp = path + '.tmp-' + uuid.uuid4().hex
    try:
        if sys.platform == 'cli':
            from System import Array, Byte
            from System.IO import FileStream, FileMode, FileAccess, FileShare
            stream = FileStream(temp, FileMode.CreateNew, FileAccess.Write, getattr(FileShare, "None"))
            try:
                raw = Array[Byte](bytearray(data))
                stream.Write(raw, 0, raw.Length)
                stream.Flush(True)
            finally:
                stream.Dispose()
        else:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        return temp
    except Exception:
        if os.path.exists(temp):
            os.remove(temp)
        raise


def _publish_new(temp, destination):
    if sys.platform == 'cli':
        from System.IO import File
        File.Move(temp, destination)  # two-argument overload never overwrites
    elif os.name == 'nt':
        os.rename(temp, destination)  # Windows rename refuses existing target
    else:
        os.link(temp, destination)  # exclusive publication, not check-then-overwrite
        os.unlink(temp)


def _replace(temp, path):
    if sys.platform == 'cli':
        from System.IO import File
        File.Replace(temp, path, path + '.bak', True)
    else:
        # CPython test/maintenance runtime. Preserve old bytes before publishing.
        with open(path, 'rb') as f:
            backup_temp = _temp_write(path + '.bak', f.read())
        try:
            os.replace(backup_temp, path + '.bak')
        finally:
            if os.path.exists(backup_temp):
                os.remove(backup_temp)
        os.replace(temp, path)


def write_new(path, value):
    path = os.path.abspath(path)
    if os.path.exists(path):
        raise MappingError('Destination already exists. Choose a new filename; nothing was overwritten.')
    temp = _temp_write(path, payload(value))
    try:
        _publish_new(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


class WorkingStore(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock = FileLock(self.path)
        self.state = None
        self.digest = None
        self.undo_state = None

    @classmethod
    def open(cls, path):
        store = cls(path)
        try:
            state, digest = read(store.path)
            core.validate(state)
            store.state, store.digest = state, digest
            return store
        except Exception:
            store.close()
            raise

    @classmethod
    def create(cls, path, state):
        core.validate(state)
        store = cls(path)
        try:
            data = payload(state)
            write_new(store.path, state)
            store.state, store.digest = copy.deepcopy(state), hashlib.sha256(data).hexdigest()
            return store
        except Exception:
            store.close()
            raise

    def check_current(self):
        if self.lock.handle is None:
            raise MappingError('Working document is closed.')
        unused, digest = read(self.path)
        if digest != self.digest:
            raise MappingError('Working file changed outside this session. Close and reopen; no overwrite performed.')

    def commit(self, candidate, action, ids, actor):
        if not ids and candidate == self.state:
            self.check_current()
            return False
        self.check_current()
        revised = core.revision(candidate, self.state, actor, action, ids)
        data = payload(revised)
        temp = _temp_write(self.path, data)
        try:
            self.check_current()
            _replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
        # No fallible disk I/O after the commit boundary.
        self.undo_state = self.state
        self.state = revised
        self.digest = hashlib.sha256(data).hexdigest()
        return True

    def undo(self, actor):
        if self.undo_state is None:
            raise MappingError('No committed edit to undo in this session.')
        target = self.undo_state
        changed = [r['id'] for r in self.state['relationships']]
        self.commit(target, 'undo-last-batch', changed, actor)
        self.undo_state = None

    def close(self):
        self.lock.close()


def recover_to_new(backup_path, destination, actor):
    state, unused = read(backup_path)
    core.validate(state)
    recovered = core.revision(state, state, actor, 'recover-backup-to-new-file', [])
    return WorkingStore.create(destination, recovered)
