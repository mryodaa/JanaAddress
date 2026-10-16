"""Экспорт теггера: эмиссии BiLSTM в ONNX, int8-квантование, калибровка, models/tagger.onnx + tagger_meta.json.

    .venv-train/Scripts/python -m training.export --run training/runs/v1 --val data/tagger/val.jsonl \
        --unseen data/tagger/unseen.jsonl [--out models]

Оценка идёт через рантайм сервиса (jana_address.tagger.runtime: onnxruntime + CRF на numpy), то есть ровно
тем кодом, который работает в образе. int8 берётся, если span-F1 на val падает не больше чем на 0.3 п.
Калибровка: изотоническая регрессия «средняя маргинальная вероятность спана -> спан верен» по меткам на val.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.isotonic import IsotonicRegression

from jana_address.tagger.features import FEATURES_VERSION, TAGS
from jana_address.tagger.runtime import Tagger as Runtime

from .data import read_jsonl, span_f1
from .model import Tagger

MAX_F1_DROP = 0.003


class EmissionsOnly(torch.nn.Module):
    def __init__(self, model: Tagger) -> None:
        super().__init__()
        self.m = model.emissions

    def forward(
        self, chars: torch.Tensor, case: torch.Tensor, cls: torch.Tensor, lengths: torch.Tensor
    ) -> torch.Tensor:
        return self.m(chars, case, cls, lengths)


def export_onnx(model: Tagger, path: Path) -> None:
    model.eval()
    b, t = 2, 16
    args = (
        torch.ones(b, t, dtype=torch.long),
        torch.ones(b, t, dtype=torch.long),
        torch.ones(b, t, dtype=torch.long),
        torch.tensor([t, t - 3], dtype=torch.long),
    )
    axes = {"chars": {0: "B", 1: "T"}, "case": {0: "B", 1: "T"}, "cls": {0: "B", 1: "T"}, "lengths": {0: "B"},
            "emissions": {0: "B", 1: "T"}}  # fmt: skip
    torch.onnx.export(
        EmissionsOnly(model),
        args,
        str(path),
        input_names=["chars", "case", "cls", "lengths"],
        output_names=["emissions"],
        dynamic_axes=axes,
        opset_version=17,
        dynamo=False,
    )


def quantize(src: Path, dst: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "LSTM", "Gemm"])


def meta_for(ckpt: dict[str, Any], model: Tagger) -> dict[str, Any]:
    trans, start, end = (p.detach().cpu().numpy().astype(float) for p in model.crf.params())
    return {
        "version": f"tagger-{time.strftime('%Y%m%d')}-e{ckpt['epoch']}",
        "features_version": FEATURES_VERSION,
        "tags": list(TAGS),
        "chars": ckpt["chars"],
        "max_len": ckpt["max_len"],
        "crf": {
            "trans": np.round(trans, 5).tolist(),
            "start": np.round(start, 5).tolist(),
            "end": np.round(end, 5).tolist(),
        },
        "hparams": ckpt["hparams"],
        "n_params": ckpt["n_params"],
        "train": {
            "data_sha256": ckpt["data_sha256"],
            "files": ckpt["data_files"],
            "seed": ckpt["seed"],
            "epoch": ckpt["epoch"],
        },
        "calibration": {},
        "metrics": {},
    }


def evaluate(rt: Runtime, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[tuple[str, float, bool]]]:
    """span-F1 рантайма + пары (метка, p_mean, верен) для калибровки."""
    raws = [str(r["raw"]) for r in rows]
    preds = rt.predict(raws)
    gold, pred, pairs = [], [], []
    for r, p in zip(rows, preds, strict=True):
        g = {(int(s), min(int(e), rt.max_len), str(lab)) for s, e, lab in r["spans"] if int(s) < rt.max_len}
        ps = [(sp.start, sp.end, sp.label) for sp in p.spans]
        gold.append(sorted(g))
        pred.append(ps)
        pairs += [(sp.label, sp.p_mean, (sp.start, sp.end, sp.label) in g) for sp in p.spans]
    return span_f1(gold, pred), pairs


def fit_calibration(pairs: list[tuple[str, float, bool]], knots: int = 24) -> dict[str, dict[str, list[float]]]:
    out = {}
    for lab in sorted({p[0] for p in pairs}):
        xs = np.array([p[1] for p in pairs if p[0] == lab])
        ys = np.array([float(p[2]) for p in pairs if p[0] == lab])
        if len(xs) < 30:
            continue
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(xs, ys)
        grid = np.unique(np.quantile(xs, np.linspace(0, 1, knots)))
        out[lab] = {"x": np.round(grid, 4).tolist(), "y": np.round(iso.predict(grid), 4).tolist()}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--val", type=Path, required=True)
    ap.add_argument("--unseen", type=Path)
    ap.add_argument("--out", type=Path, default=Path("models"))
    args = ap.parse_args(argv)

    ckpt = torch.load(args.run / "best.pt", map_location="cpu", weights_only=False)
    model = Tagger(len(ckpt["chars"]) + 2, **ckpt["hparams"])
    model.load_state_dict(ckpt["state"])
    model.eval()
    meta = meta_for(ckpt, model)
    val = read_jsonl(args.val)
    unseen = read_jsonl(args.unseen) if args.unseen else []

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        fp32, int8, meta_path = d / "fp32.onnx", d / "int8.onnx", d / "meta.json"
        export_onnx(model, fp32)
        quantize(fp32, int8)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        res = {}
        for name, path in (("fp32", fp32), ("int8", int8)):
            t0 = time.perf_counter()
            f1, _ = evaluate(Runtime(path, meta_path), val)
            kb, sec = round(path.stat().st_size / 1024), time.perf_counter() - t0
            res[name] = {"f1": f1["f1"], "size_kb": kb, "sec": sec}
            print(f"{name}: val F1 {f1['f1']:.4f}, {kb} КБ, {sec:.1f} с на {len(val)} строк")
        chosen = "int8" if res["fp32"]["f1"] - res["int8"]["f1"] <= MAX_F1_DROP else "fp32"
        path = int8 if chosen == "int8" else fp32
        rt = Runtime(path, meta_path)
        f1_val, pairs = evaluate(rt, val)
        meta["calibration"] = fit_calibration(pairs)
        meta["quantization"] = chosen
        meta["metrics"] = {
            "val_span_f1": round(float(f1_val["f1"]), 4),
            "val_by_label": f1_val["by_label"],
            "fp32_val_span_f1": round(float(res["fp32"]["f1"]), 4),
            "int8_val_span_f1": round(float(res["int8"]["f1"]), 4),
        }
        if unseen:
            f1_u, _ = evaluate(rt, unseen)
            meta["metrics"]["unseen_span_f1"] = round(float(f1_u["f1"]), 4)
            meta["metrics"]["unseen_by_label"] = f1_u["by_label"]
            print(f"unseen (топонимы вне обучения): span F1 {f1_u['f1']:.4f}")
        args.out.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, args.out / "tagger.onnx")
        (args.out / "tagger_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    size = (args.out / "tagger.onnx").stat().st_size + (args.out / "tagger_meta.json").stat().st_size
    print(f"-> {args.out}: {chosen}, {size / 1024:.0f} КБ всего; val F1 {meta['metrics']['val_span_f1']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
