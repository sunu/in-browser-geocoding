"""Export the T5 frame model and the local cross-encoder to ONNX (fp32 and int8) for the browser.

T5: encoder.onnx (input_ids, attention_mask -> cross_kv, the cross-attention keys and values of each decoder layer)
and decoder.onnx, one step with a key-value cache (input_ids [n, 1], past, cross_kv, encoder_attention_mask ->
logits [n, V], present). past and present: [layers, 2, n, heads, t, d_kv]; the first step has t = 0. cross_kv
has batch 1 for all beams. The int8 files share one embedding table (embed.bin, external data): the int8 lm_head
weight [d_model, V], also read by the token lookups of the encoder and the decoder.
Cross-encoder: model.onnx (input_ids, attention_mask, token_type_ids -> logits).

Usage: uv run python scripts/export_onnx.py [--t5 models/t5/current] [--xenc models/local/current] [--only t5|xenc]
Output: web/public/models/{t5,xenc}/
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import onnx
import torch
from onnx import external_data_helper, helper, numpy_helper
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModelForSeq2SeqLM, AutoModelForSequenceClassification, AutoTokenizer
from transformers.models.t5.modeling_t5 import T5Attention

from geoparse.config import REPO_ROOT

OUT = REPO_ROOT / "web" / "public" / "models"


def heads(x, h: int, d: int):
    return x.view(x.shape[0], -1, h, d).transpose(1, 2)


def attend(q, k, v, bias):
    """T5 attention: no 1/sqrt(d) scale. bias: the position bias or the additive mask."""
    w = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) + bias, dim=-1)
    return torch.matmul(w, v).transpose(1, 2).reshape(q.shape[0], -1, q.shape[1] * q.shape[3])


class Enc(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.e = m.get_encoder()
        self.cross = torch.nn.ModuleList(b.layer[1].EncDecAttention for b in m.get_decoder().block)
        self.h, self.d = m.config.num_heads, m.config.d_kv

    def forward(self, input_ids, attention_mask):
        x = self.e(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return torch.stack([torch.stack([heads(a.k(x), self.h, self.d), heads(a.v(x), self.h, self.d)])
                            for a in self.cross])


class Dec(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.dec = m.get_decoder()
        self.lm_head = m.lm_head
        c = m.config
        self.h, self.d, self.buckets, self.max_dist = c.num_heads, c.d_kv, c.relative_attention_num_buckets, \
            c.relative_attention_max_distance
        self.scale = c.d_model ** -0.5 if c.scale_decoder_outputs else 1.0

    def forward(self, input_ids, past, cross_kv, encoder_attention_mask):
        t = past.shape[4]
        x = self.dec.embed_tokens(input_ids)
        rel = self.dec.block[0].layer[0].SelfAttention
        bucket = T5Attention._relative_position_bucket(torch.arange(t + 1) - t, bidirectional=False,
                                                       num_buckets=self.buckets, max_distance=self.max_dist)
        bias = rel.relative_attention_bias(bucket).t()[None, :, None, :]
        mask = (1.0 - encoder_attention_mask[:, None, None, :].float()) * torch.finfo(torch.float32).min
        present = []
        for i, b in enumerate(self.dec.block):
            sa, ca = b.layer[0], b.layer[1]
            a = sa.SelfAttention
            y = sa.layer_norm(x)
            k = torch.cat([past[i, 0], heads(a.k(y), self.h, self.d)], 2)
            v = torch.cat([past[i, 1], heads(a.v(y), self.h, self.d)], 2)
            present.append(torch.stack([k, v]))
            x = x + a.o(attend(heads(a.q(y), self.h, self.d), k, v, bias))
            a = ca.EncDecAttention
            y = ca.layer_norm(x)
            x = x + a.o(attend(heads(a.q(y), self.h, self.d), cross_kv[i, 0], cross_kv[i, 1], mask))
            x = b.layer[2](x)
        x = self.dec.final_layer_norm(x) * self.scale
        return self.lm_head(x)[:, 0], torch.stack(present)


def check_t5(m, enc: Enc, dec: Dec, x) -> None:
    """The cached steps against the logits of the whole model (3 beams, 6 steps). Stop on a difference."""
    with torch.no_grad():
        kv = enc(x.input_ids, x.attention_mask)
        n, c = 3, m.config
        seq = torch.full((n, 1), c.decoder_start_token_id)
        past = torch.zeros(c.num_decoder_layers, 2, n, c.num_heads, 0, c.d_kv)
        for step in range(6):
            logits, past = dec(seq[:, -1:], past, kv, x.attention_mask)
            ref = m(input_ids=x.input_ids.repeat(n, 1), attention_mask=x.attention_mask.repeat(n, 1),
                    decoder_input_ids=seq, use_cache=False).logits[:, -1]
            diff = (logits - ref).abs().max().item()
            if diff > 1e-4:
                raise SystemExit(f"t5 export: step {step} differs from the model by {diff}")
            seq = torch.cat([seq, torch.tensor([[100 + step], [200 + step], [300 + step]])], 1)


def quant(src: Path) -> Path:
    dst = src.with_name(src.stem + "_int8.onnx")
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    return dst


def share_embedding(enc_path: Path, dec_path: Path) -> None:
    """Replace the uint8 embedding tables of both int8 graphs with lookups in the int8 lm_head weight (tied), and
    store that weight once in embed.bin."""
    dec, enc = onnx.load(str(dec_path)), onnx.load(str(enc_path))
    inits = {t.name: t for t in dec.graph.initializer}
    head = next(n for n in dec.graph.node if n.op_type == "MatMulInteger" and n.name.startswith("/lm_head/"))
    w = inits[head.input[1]]
    scale, zero = inits[head.input[1].replace("_quantized", "_scale")], inits[head.input[3]]
    data = numpy_helper.to_array(w)
    (enc_path.parent / "embed.bin").write_bytes(data.tobytes())
    for m in (enc, dec):
        g = m.graph
        gather = next(n for n in g.node if n.op_type == "Gather" and n.input[0].endswith("embed_tokens.weight_quantized"))
        deq = next(n for n in g.node if n.op_type == "DequantizeLinear" and n.input[0] == gather.output[0])
        drop = set(deq.input[1:]) | {gather.input[0]}
        i = list(g.node).index(gather)
        new = [helper.make_node("Gather", ["shared.weight", gather.input[1]], ["shared/gather"], axis=1),
               helper.make_node("Transpose", ["shared/gather"], ["shared/rows"], perm=[1, 2, 0]),
               helper.make_node("DequantizeLinear", ["shared/rows", "shared.scale", "shared.zero_point"], deq.output)]
        g.node.remove(gather)
        g.node.remove(deq)
        for k, n in enumerate(new):
            g.node.insert(i + k, n)
        if m is dec:
            head.input[1], head.input[3] = "shared.weight", "shared.zero_point"
            for n in g.node:
                for j, x in enumerate(n.input):
                    if x == scale.name:
                        n.input[j] = "shared.scale"
            drop |= {w.name, scale.name, zero.name}
        keep = [t for t in g.initializer if t.name not in drop]
        del g.initializer[:]
        g.initializer.extend(keep)
        t = numpy_helper.from_array(data, "shared.weight")
        external_data_helper.set_external_data(t, "embed.bin", offset=0, length=data.nbytes)
        t.data_location = onnx.TensorProto.EXTERNAL
        t.ClearField("raw_data")
        g.initializer.extend([t, numpy_helper.from_array(numpy_helper.to_array(scale), "shared.scale"),
                              numpy_helper.from_array(numpy_helper.to_array(zero), "shared.zero_point")])
    onnx.save(enc, str(enc_path))
    onnx.save(dec, str(dec_path))


def export_t5(d: Path) -> None:
    out = OUT / "t5"
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(str(d))
    m = AutoModelForSeq2SeqLM.from_pretrained(str(d)).eval()
    x = tok(["parse: districts near the sea in Gujarat"], return_tensors="pt")
    enc, dec = Enc(m).eval(), Dec(m).eval()
    check_t5(m, enc, dec, x)
    with torch.no_grad():
        kv = enc(x.input_ids, x.attention_mask)
    c = m.config
    torch.onnx.export(enc, (x.input_ids, x.attention_mask), str(out / "encoder.onnx"),
                      input_names=["input_ids", "attention_mask"], output_names=["cross_kv"],
                      dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                                    "cross_kv": {2: "b", 4: "s"}}, opset_version=17, dynamo=False)
    ids = torch.tensor([[100], [200]])
    past = torch.zeros(c.num_decoder_layers, 2, 2, c.num_heads, 3, c.d_kv)
    torch.onnx.export(dec, (ids, past, kv, x.attention_mask), str(out / "decoder.onnx"),
                      input_names=["input_ids", "past", "cross_kv", "encoder_attention_mask"],
                      output_names=["logits", "present"],
                      dynamic_axes={"input_ids": {0: "n"}, "past": {2: "n", 4: "t"}, "cross_kv": {4: "s"},
                                    "encoder_attention_mask": {1: "s"}, "logits": {0: "n"},
                                    "present": {2: "n", 4: "t1"}},
                      opset_version=17, dynamo=False)
    share_embedding(quant(out / "encoder.onnx"), quant(out / "decoder.onnx"))
    tok.save_pretrained(str(out))
    (out / "generation.json").write_text(json.dumps({
        "decoder_start_token_id": m.config.decoder_start_token_id, "eos_token_id": m.config.eos_token_id,
        "pad_token_id": m.config.pad_token_id, "prefix": "parse: ", "max_new_tokens": 96}))
    print("t5:", {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in sorted([*out.glob('*.onnx'), out / 'embed.bin'])})


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
    print("xenc:", {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in sorted([*out.glob('*.onnx'), out / 'embed.bin'])})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t5", default=str(REPO_ROOT / "models" / "t5" / "current"))
    ap.add_argument("--xenc", default=str(REPO_ROOT / "models" / "local" / "current"))
    ap.add_argument("--only", choices=["t5", "xenc"])
    args = ap.parse_args()
    if args.only != "xenc":
        export_t5(Path(args.t5).resolve())
    if args.only != "t5":
        export_xenc(Path(args.xenc).resolve())


if __name__ == "__main__":
    main()
