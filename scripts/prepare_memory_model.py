"""Fetch the reviewed, immutable evaluation model; never executed by agent runtime."""
import argparse
import json
import shutil
from pathlib import Path

MODEL_ID='sentence-transformers/all-MiniLM-L6-v2'
REVISION='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
FILES=('config.json','config_sentence_transformers.json','sentence_bert_config.json',
       'modules.json','1_Pooling/config.json','model.safetensors','tokenizer.json',
       'tokenizer_config.json','special_tokens_map.json','vocab.txt','README.md')


def prepare(destination):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError("Install the semantic extra before preparing an evaluation model: pip install -e .[semantic]") from exc
    root=Path(destination)
    if root.exists():raise ValueError('Use a new, empty model destination')
    root.mkdir(parents=True)
    for name in FILES:
        cached=hf_hub_download(repo_id=MODEL_ID,filename=name,revision=REVISION)
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(cached,target)  # Materialize bytes, not cache symlinks.
    return {'model_id':MODEL_ID,'revision':REVISION,'files':list(FILES),
            'license':'Apache-2.0','remote_code':False,'weights_format':'safetensors'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.destination),indent=2))
