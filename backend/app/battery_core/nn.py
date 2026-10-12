"""Small PyTorch MLP regressor for tabular data, with built-in feature scaling.

Both the SOH model and the range (Wh/km) model use this. The saved checkpoint
holds weights + scaler stats + feature names, so inference needs nothing else.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch import nn


class MLP(nn.Module):
    def __init__(self, n_in: int, hidden: tuple[int, ...] = (64, 64), dropout: float = 0.05):
        super().__init__()
        layers, prev = [], n_in
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.SiLU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).squeeze(-1)


class TabularRegressor:
    def __init__(self, feature_names: list[str], hidden=(64, 64), log_target=False):
        self.feature_names = list(feature_names)
        self.hidden = tuple(hidden)
        self.log_target = log_target
        self.model = MLP(len(feature_names), self.hidden)
        self.x_mean = self.x_std = None
        self.y_mean = self.y_std = 0.0

    # -- training -------------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray, X_val=None, y_val=None,
            epochs=80, lr=2e-3, batch_size=256, seed=0, verbose=True):
        torch.manual_seed(seed)
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)
        if self.log_target:
            y = np.log(y)
        self.x_mean, self.x_std = X.mean(0), X.std(0) + 1e-6
        self.y_mean, self.y_std = float(y.mean()), float(y.std() + 1e-6)

        Xt = torch.from_numpy((X - self.x_mean) / self.x_std)
        yt = torch.from_numpy((y - self.y_mean) / self.y_std)
        opt = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
        loss_fn = nn.MSELoss()

        for epoch in range(epochs):
            self.model.train()
            perm = torch.randperm(len(Xt))
            total = 0.0
            for i in range(0, len(Xt), batch_size):
                idx = perm[i : i + batch_size]
                opt.zero_grad()
                loss = loss_fn(self.model(Xt[idx]), yt[idx])
                loss.backward()
                opt.step()
                total += loss.item() * len(idx)
            sched.step()
            if verbose and (epoch % 10 == 0 or epoch == epochs - 1):
                msg = f"  epoch {epoch:3d}  train_mse={total / len(Xt):.4f}"
                if X_val is not None:
                    pred = self.predict(X_val)
                    msg += f"  val_mae={np.mean(np.abs(pred - y_val)):.4f}"
                print(msg)
        return self

    # -- inference ------------------------------------------------------------
    @torch.no_grad()
    def predict(self, X: np.ndarray) -> np.ndarray:
        self.model.eval()
        X = np.asarray(X, dtype=np.float32)
        out = self.model(torch.from_numpy((X - self.x_mean) / self.x_std)).numpy()
        out = out * self.y_std + self.y_mean
        return np.exp(out) if self.log_target else out

    # -- persistence ----------------------------------------------------------
    def save(self, path: Path, metrics: dict | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "feature_names": self.feature_names,
                "hidden": self.hidden,
                "log_target": self.log_target,
                "x_mean": [float(v) for v in self.x_mean],
                "x_std": [float(v) for v in self.x_std],
                "y_mean": self.y_mean,
                "y_std": self.y_std,
                "metrics": metrics or {},
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "TabularRegressor":
        ck = torch.load(path, map_location="cpu", weights_only=True)
        obj = cls(ck["feature_names"], tuple(ck["hidden"]), ck["log_target"])
        obj.model.load_state_dict(ck["state_dict"])
        obj.x_mean = np.array(ck["x_mean"], dtype=np.float32)
        obj.x_std = np.array(ck["x_std"], dtype=np.float32)
        obj.y_mean, obj.y_std = ck["y_mean"], ck["y_std"]
        obj.metrics = ck.get("metrics", {})
        return obj
