import base64
import json
import pytest
from tools.split_turn_review import split_review


def test_split_preserves_measurement_evidence_and_image_bytes(tmp_path):
    data=b'RIFF'+b'\x04\x00\x00\x00'+b'WEBP'+b'synthetic'
    bundle={'digest':'unchanged','events':[{'time':1.25,'pts':112500}],
            'images':{'7':'data:image/webp;base64,'+base64.b64encode(data).decode()}}
    source=tmp_path/'source.html'
    source.write_text('<script type="application/json" id="bundle">'+json.dumps(bundle)+'</script>',encoding='utf-8')
    target=tmp_path/'split';result=split_review(source,target)
    text=(target/'index.html').read_text(encoding='utf-8')
    saved=json.loads(text.split('>',1)[1].split('</script>')[0])
    assert saved['digest']==bundle['digest'] and saved['events']==bundle['events']
    assert (target/saved['images']['7']).read_bytes()==data
    assert 'data:image' not in text and result['external_publication_performed'] is False
    with pytest.raises(FileExistsError):split_review(source,target)


def test_remote_images_are_not_fetched_or_exported(tmp_path):
    source=tmp_path/'source.html';target=tmp_path/'split'
    source.write_text('<script type="application/json" id="bundle">'+json.dumps({'images':{'1':'https://example.com/private'}})+'</script>')
    with pytest.raises(ValueError,match='embedded_webp'):split_review(source,target)
    assert not target.exists()
