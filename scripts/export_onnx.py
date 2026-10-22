"""Export the T5 frame model and the local cross-encoder to ONNX (fp32 and int8) for the browser.

T5: encoder.onnx (input_ids, attention_mask -> hidden) and decoder.onnx (decoder_input_ids,
encoder_hidden_states, encoder_attention_mask -> logits). No key-value cache: the beam search runs the
decoder on the whole prefix at each step. Frames are short (under 50 tokens).
Cross-encoder: model.onnx (input_ids, attention_mask, token_type_ids -> logits).

Usage: uv run python scripts/export_onnx.py [--t5 models/t5/current] [--xenc models/local/current]
Output: web/public/models/{t5,xenc}/
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModelForSeq2SeqLM, AutoModelForSequenceClassification, AutoTokenizer

from geoparse.config import REPO_ROOT

OUT = REPO_ROOT / "web" / "public" / "models"


class Enc(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.e = m.get_encoder()

    def forward(self, input_ids, attention_mask):
        return self.e(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state


class Dec(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, decoder_input_ids, encoder_hidden_states, encoder_attention_mask):
        out = self.m(encoder_outputs=(encoder_hidden_states,), attention_mask=encoder_attention_mask,
                     decoder_input_ids=decoder_input_ids, use_cache=False)
        return out.logits


def quant(src: Path) -> Path:
    dst = src.with_name(src.stem + "_int8.onnx")
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    return dst


def export_t5(d: Path) -> None:
    out = OUT / "t5"
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(str(d))
    m = AutoModelForSeq2SeqLM.from_pretrained(str(d)).eval()
    x = tok(["parse: districts near the sea in Gujarat"], return_tensors="pt")
    with torch.no_grad():
        h = Enc(m)(x.input_ids, x.attention_mask)
    torch.onnx.export(Enc(m), (x.input_ids, x.attention_mask), str(out / "encoder.onnx"),
                      input_names=["input_ids", "attention_mask"], output_names=["last_hidden_state"],
                      dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                                    "last_hidden_state": {0: "b", 1: "s"}}, opset_version=17, dynamo=False)
    dec_ids = torch.tensor([[m.config.decoder_start_token_id, 100, 200]])
    torch.onnx.export(Dec(m), (dec_ids, h, x.attention_mask), str(out / "decoder.onnx"),
                      input_names=["decoder_input_ids", "encoder_hidden_states", "encoder_attention_mask"],
                      output_names=["logits"],
                      dynamic_axes={"decoder_input_ids": {0: "b", 1: "t"}, "encoder_hidden_states": {0: "b", 1: "s"},
                                    "encoder_attention_mask": {0: "b", 1: "s"}, "logits": {0: "b", 1: "t"}},
                      opset_version=17, dynamo=False)
    for f in ("encoder.onnx", "decoder.onnx"):
        quant(out / f)
    tok.save_pretrained(str(out))
    (out / "generation.json").write_text(json.dumps({
        "decoder_start_token_id": m.config.decoder_start_token_id, "eos_token_id": m.config.eos_token_id,
        "pad_token_id": m.config.pad_token_id, "prefix": "parse: ", "max_new_tokens": 96}))
    print("t5:", {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in sorted(out.glob('*.onnx'))})


def export_xenc(d: Path) -> None:
    out = OUT / "xenc"
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(str(d))
    m = AutoModelForSequenceClassification.from_pretrained(str(d)).eval()
    x = tok(["a question"], ["an option"], return_tensors="pt")
    names = ["input_ids", "attention_mask"] + (["token_type_ids"] if "token_type_ids" in x else [])
    args = tuple(x[n] for n in names)
    torch.onnx.export(m, args, str(out / "model.onnx"), input_names=names, output_names=["logits"],
                      dynamic_axes={**{n: {0: "b", 1: "s"} for n in names}, "logits": {0: "b"}},
                      opset_version=17, dynamo=False)
    quant(out / "model.onnx")
    tok.save_pretrained(str(out))
    shutil.copy(d / "calibration.json", out / "calibration.json")
    (out / "inputs.json").write_text(json.dumps({"input_names": names, "max_length": 128}))
    print("xenc:", {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in sorted(out.glob('*.onnx'))})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t5", default=str(REPO_ROOT / "models" / "t5" / "current"))
    ap.add_argument("--xenc", default=str(REPO_ROOT / "models" / "local" / "current"))
    args = ap.parse_args()
    export_t5(Path(args.t5).resolve())
    export_xenc(Path(args.xenc).resolve())


if __name__ == "__main__":
    main()
