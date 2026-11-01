"""Identity precondition for a face reviewed before an additive assignment."""
import hashlib
import json


def face_identity_token(face_id, path, index, box, model, embedding):
    metadata = json.dumps([face_id, path, index, list(box), model], ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
    payload = embedding if isinstance(embedding, bytes) else repr(embedding).encode('utf-8')
    return hashlib.sha256(metadata + b'\0' + payload).hexdigest()
