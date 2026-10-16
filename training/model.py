"""Char BiLSTM-CRF. Обратное направление LSTM считается как прямой LSTM по развёрнутой в пределах длины
последовательности: паддинг справа не влияет ни на одно направление, и граф экспортируется в ONNX без
packed sequences (два однонаправленных ONNX LSTM на слой, квантуются DynamicQuantizeLSTM).
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

from jana_address.tagger.features import N_CASE, N_CLS, TAGS, allowed_transitions

NEG = -1e4  # запрещённый переход BIO (не -inf: без NaN в logsumexp)


class Emissions(nn.Module):
    def __init__(self, n_chars: int, emb: int = 48, hidden: int = 128, layers: int = 2, dropout: float = 0.2) -> None:
        super().__init__()
        self.char = nn.Embedding(n_chars, emb, padding_idx=0)
        self.case = nn.Embedding(N_CASE, 4, padding_idx=0)
        self.cls = nn.Embedding(N_CLS, 8, padding_idx=0)
        self.fw = nn.ModuleList()
        self.bw = nn.ModuleList()
        for i in range(layers):
            inp = emb + 12 if i == 0 else 2 * hidden
            self.fw.append(nn.LSTM(inp, hidden, batch_first=True))
            self.bw.append(nn.LSTM(inp, hidden, batch_first=True))
        self.drop = nn.Dropout(dropout)
        self.out = nn.Linear(2 * hidden, len(TAGS))

    def forward(self, chars: Tensor, case: Tensor, cls: Tensor, lengths: Tensor) -> Tensor:
        width = chars.shape[1]
        t = torch.arange(width, device=chars.device).unsqueeze(0)
        ln = lengths.unsqueeze(1)
        rev = torch.where(t < ln, ln - 1 - t, t)  # индекс разворота внутри длины, паддинг на месте
        x = self.drop(torch.cat([self.char(chars), self.case(case), self.cls(cls)], dim=-1))
        for fw, bw in zip(self.fw, self.bw, strict=True):
            f, _ = fw(x)
            idx = rev.unsqueeze(-1).expand(-1, -1, x.shape[-1])
            b, _ = bw(torch.gather(x, 1, idx))
            b = torch.gather(b, 1, rev.unsqueeze(-1).expand(-1, -1, b.shape[-1]))
            x = self.drop(torch.cat([f, b], dim=-1))
        return self.out(x)


class CRF(nn.Module):
    def __init__(self, n: int) -> None:
        super().__init__()
        self.trans = nn.Parameter(torch.zeros(n, n))
        self.start = nn.Parameter(torch.zeros(n))
        self.end = nn.Parameter(torch.zeros(n))
        allowed, start_ok = allowed_transitions()
        self.register_buffer("tmask", torch.tensor(~allowed, dtype=torch.float32) * NEG)
        self.register_buffer("smask", torch.tensor(~start_ok, dtype=torch.float32) * NEG)

    def params(self) -> tuple[Tensor, Tensor, Tensor]:
        """Переходы с маской BIO: именно они уходят в tagger_meta.json и в numpy-CRF рантайма."""
        return self.trans + self.tmask, self.start + self.smask, self.end

    def nll(self, em: Tensor, tags: Tensor, lengths: Tensor) -> Tensor:
        trans, start, end = self.params()
        bsz, width, _ = em.shape
        mask = torch.arange(width, device=em.device).unsqueeze(0) < lengths.unsqueeze(1)
        # счёт эталонного пути
        ar = torch.arange(bsz, device=em.device)
        gold = start[tags[:, 0]] + em[ar, 0, tags[:, 0]]
        for t in range(1, width):
            step = trans[tags[:, t - 1], tags[:, t]] + em[ar, t, tags[:, t]]
            gold = gold + step * mask[:, t]
        last = tags[ar, lengths - 1]
        gold = gold + end[last]
        # статсумма
        alpha = start.unsqueeze(0) + em[:, 0]
        for t in range(1, width):
            nxt = torch.logsumexp(alpha.unsqueeze(2) + trans.unsqueeze(0), dim=1) + em[:, t]
            alpha = torch.where(mask[:, t].unsqueeze(1), nxt, alpha)
        log_z = torch.logsumexp(alpha + end.unsqueeze(0), dim=1)
        return (log_z - gold).mean()

    @torch.no_grad()
    def decode(self, em: Tensor, lengths: Tensor) -> list[list[int]]:
        trans, start, end = self.params()
        bsz, width, _ = em.shape
        score = start.unsqueeze(0) + em[:, 0]
        back = []
        for t in range(1, width):
            cand = score.unsqueeze(2) + trans.unsqueeze(0)
            best, arg = cand.max(dim=1)
            back.append(arg)
            score = torch.where((t < lengths).unsqueeze(1), best + em[:, t], score)
        last = (score + end.unsqueeze(0)).argmax(dim=1).tolist()
        back_cpu = [b.cpu() for b in back]
        out = []
        for b in range(bsz):
            n = int(lengths[b])
            path = [last[b]]
            for t in range(n - 1, 0, -1):
                path.append(int(back_cpu[t - 1][b, path[-1]]))
            out.append(path[::-1])
        return out


class Tagger(nn.Module):
    def __init__(self, n_chars: int, **kw: int | float) -> None:
        super().__init__()
        self.emissions = Emissions(n_chars, **kw)  # type: ignore[arg-type]
        self.crf = CRF(len(TAGS))
