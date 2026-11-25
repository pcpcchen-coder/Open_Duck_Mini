#!/usr/bin/env python3
"""下載音訊 spike 用的第三方模型到 `robot/audio/models/`（不進版控），核對 SHA-256。

只用標準函式庫。壓縮檔與每個解出的檔案都核對雜湊；不符就刪掉並以非 0 結束。
清單、網址與雜湊沿用 AIOS `prototype/ambient-shell/spike/wake/models.json`（main `8eb53b2` 唯讀查閱，
雜湊是 AIOS 2026-10-29 的下載結果）。

    python tools/fetch_models.py kws-zh-en        # 喚醒詞：zh-en-3M（AIOS 產品用的那一個）
    python tools/fetch_models.py kws-wenetspeech  # 喚醒詞：wenetspeech-3.3M（中文）
    python tools/fetch_models.py tts-melo         # 合成語音 fixture 用（只在開發機用，約 170 MB）

授權（照 AIOS 的查核結果照實寫）：

- kws-zh-en：壓縮檔裡**沒有授權檔、也沒有訓練資料說明**。只在本機 spike 使用，不散布。
- kws-wenetspeech：模型卡寫 Apache-2.0；訓練資料 WenetSpeech 的授權條款互相矛盾（AIOS docs/17 §6.2）。
- tts-melo：MeloTTS，MIT（壓縮檔內有 LICENSE）。
- sherpa-onnx 本身：Apache-2.0。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
MODELS = {
    "kws-zh-en": {
        "dir": "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20",
        "url": f"{BASE}/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2",
        "archive_sha256": "68447f4fbc67e70eee3a93961f36e81e98f47aef73ce7e7ca00885c6cd3616a6",
        "files": {
            "encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx": "408bbd740838c42d5bf6d1c5b80b3c88b616c7860b92d980328b5b068c76ae48",
            "decoder-epoch-13-avg-2-chunk-16-left-64.onnx": "63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21",
            "joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx": "190d4067b4cc20b72a42a1916e69d92052000fb7051a427ebb1bc72a69207dc1",
            "tokens.txt": "2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0",
        },
    },
    "kws-wenetspeech": {
        "dir": "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
        "url": f"{BASE}/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2",
        "archive_sha256": "b2f7c89690dc8ce4c6ed6afeab7cd800c36ad1421fb6b6302b4a4b194cf7f35f",
        "files": {
            "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx": "dd784973fc9d2fabb3b800d6dcd20fc3b0ca84f8e2415afe54b032878e447f4d",
            "decoder-epoch-12-avg-2-chunk-16-left-64.onnx": "fb581d6734511676e246e0dff2fea01b31b0913176cb3ca64576dbab0a177774",
            "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx": "f79760052b87239e325f0567c752ad3130b30d92effb847d4307743c20c59a24",
            "tokens.txt": "72316508d9119696145abc6f1f8cdc46287535c34e5ce7e595f845cb1499cf2e",
        },
    },
    "tts-melo": {
        "dir": "vits-melo-tts-zh_en",
        "url": f"{BASE}/tts-models/vits-melo-tts-zh_en.tar.bz2",
        "archive_sha256": "e58351ed7149f290a54534538badd4077cdbe6fddc964b24d0bee870415d1514",
        "files": {
            "model.onnx": "bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d",
            "lexicon.txt": "7236884b02435ac5d10cf69b4be40a61b45aa676b5300f0e412f185748fee528",
            "tokens.txt": "d18664a7e12bd7ea1022ddaf951e534e136815016c5a809d6b64156bffb4369d",
            "phone.fst": "1ac2b6fa56b1442320c4de7db08353bab8963a2b57f365eebcdd3a2d3562f8d7",
            "date.fst": "eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718",
            "number.fst": "743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd",
            "new_heteronym.fst": "ca14b2127e27baa571664e4bb791e143e7425f56a6bc29db08d74f97e6aa4e29",
            "LICENSE": "88a50e5a02bbc2a5c2f084dc19da751aa97b1690f5fda76cd8005c8634d1ca70",
            "dict/jieba.dict.utf8": "3043b77068e09c9904f27cad82f12b6ebe9dbdb5aeff3b25e45ab7f9c1122b55",
            "dict/hmm_model.utf8": "f17790586ac86dd048c8adffed052c4bd2b28ed0682972c1275e59040c0589a7",
            "dict/user.dict.utf8": "495bbf49270408a1234690e1e6a97328f30a482a7a72aa769e8a12e8714b0c62",
            "dict/idf.utf8": "dbd1e03d72b2263cc8d84a4304ed77677eed9e7deaf43a1a5133bbba9733b535",
            "dict/stop_words.utf8": "b788b8a939d2e2fe079abd579ea98f12f9fb84370bfd0dddd81bb9381f7ab42c",
            "dict/pos_dict/char_state_tab.utf8": "28b7be1dd7369766a51445af4d42e9a2ba4bf374c13be5bc1ca7721e27271dbb",
            "dict/pos_dict/prob_emit.utf8": "c33c4cb7edf3b3a5947df7209b6e9f267eae1f21335d9e2bd2521ea07105457a",
            "dict/pos_dict/prob_trans.utf8": "f22363e2307408293d180c6f9f6b5cb75879d52f722f7764fa2d3d0ae2400236",
            "dict/pos_dict/prob_start.utf8": "13623ea0e9300bdb597cb2da28770b7b385d6c0098d66e516083fb01b6bd5d96",
        },
    },
}
DEFAULT_DEST = Path(__file__).resolve().parents[1] / "models"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(key: str, dest: Path) -> int:
    m = MODELS[key]
    out = dest / m["dir"]
    if all((out / n).exists() and sha256_of(out / n) == s for n, s in m["files"].items()):
        print(f"{key}：已存在且雜湊相符（{out}）")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / (m["dir"] + ".tar.bz2")
    print(f"{key}：下載 {m['url']}")
    req = urllib.request.Request(m["url"], headers={"User-Agent": "fetch-models"})
    with urllib.request.urlopen(req, timeout=600) as r, archive.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = sha256_of(archive)
    if got != m["archive_sha256"]:
        archive.unlink()
        print(f"壓縮檔 SHA-256 不符：期望 {m['archive_sha256']}，得到 {got}", file=sys.stderr)
        return 1
    with tarfile.open(archive, "r:bz2") as tar:
        for name, want in m["files"].items():
            member = tar.getmember(f"{m['dir']}/{name}")
            if not member.isfile():
                print(f"{name} 不是一般檔案", file=sys.stderr)
                return 1
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            assert src is not None
            target.write_bytes(src.read())
            if sha256_of(target) != want:
                target.unlink()
                print(f"{name} SHA-256 不符", file=sys.stderr)
                return 1
    archive.unlink()
    print(f"{key}：完成（{len(m['files'])} 個檔案 → {out}）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("models", nargs="+", choices=sorted(MODELS))
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    a = ap.parse_args()
    sys.exit(max(fetch(k, a.dest) for k in a.models))
