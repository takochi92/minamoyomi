"""Bind private research outputs to an exact decoded frame export, not just video."""
import hashlib
import json
import re


def frame_binding(manifest):
    source=manifest['source'];base=source.get('time_base');frames=manifest['frames']
    if (manifest.get('schema')!=2 or source.get('clock')!='decoded_pts'
            or not isinstance(base,list) or len(base)!=2
            or any(type(v) is not int or v<=0 for v in base) or not frames):
        raise ValueError('original_pts_required')
    previous=None;rows=[]
    for frame in frames:
        pts=frame.get('pts');sha=frame.get('sha256')
        if (type(pts) is not int or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
                or previous is not None and not 0<(pts-previous)*base[0]/base[1]<=.12):
            raise ValueError('invalid_frame_clock_or_digest')
        rows.append([pts,sha]);previous=pts
    payload={'source_sha256':source['sha256'],'time_base':base,'frames':rows}
    return {'frame_export_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'source_sha256':source['sha256'],'time_base':base,'first_pts':frames[0]['pts'],'frame_count':len(frames)}


def require_frame_binding(manifest,result):
    expected=frame_binding(manifest)
    if result.get('frame_binding')!=expected:raise ValueError('frame_export_mismatch')
    return expected
