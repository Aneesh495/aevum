"""Two structured mortality estimators optimized against death counts."""

from dataclasses import asdict, dataclass
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import numpy as np
import torch
from torch import Tensor, nn

from .cube import Cube, Float, Population

LearnedFamily = Literal["structured", "state_space"]


@dataclass(frozen=True, slots=True)
class TrainingSpec:
    family: LearnedFamily
    seed: int
    steps: int = 180
    learning_rate: float = 0.045
    likelihood: Literal["poisson", "negative_binomial"] = "poisson"
    hierarchy: bool = True
    age_basis: bool = True
    shock: bool = True
    dynamics: bool = True

    def __post_init__(self) -> None:
        if self.family not in {"structured", "state_space"}:
            raise ValueError("unrecognized learned family")
        if not 0 <= self.seed < 2 ** 32 or not 1 <= self.steps <= 2000:
            raise ValueError("unsupported training seed or budget")
        if not isfinite(self.learning_rate) or not 0 < self.learning_rate <= 0.2:
            raise ValueError("unsupported learning rate")
        if self.likelihood not in {"poisson", "negative_binomial"}:
            raise ValueError("unsupported likelihood")


@dataclass(frozen=True, slots=True)
class Support:
    groups: tuple[Population, ...]
    ages: tuple[int, ...]
    first: int
    origin: int
    vintage: str

    @classmethod
    def from_cube(cls, train: Cube) -> "Support":
        return cls(train.groups, tuple(age.start for age in train.ages), train.years[0], train.years[-1], train.vintage)

    @property
    def countries(self) -> tuple[str, ...]:
        return tuple(sorted({group.country for group in self.groups}))


def poisson_loss(log_rate: Tensor, deaths: Tensor, exposure: Tensor) -> Tensor:
    """Poisson negative log likelihood up to constants independent of the model."""
    log_mean = log_rate + exposure.log()
    return log_mean.exp() - deaths * log_mean


def nb_loss(log_rate: Tensor, deaths: Tensor, exposure: Tensor, alpha: Tensor) -> Tensor:
    """NB2 likelihood with variance mean + alpha * mean squared."""
    log_mean = log_rate + exposure.log()
    inv = alpha.reciprocal()
    log_denom = torch.logaddexp(log_mean, inv.log())
    return (
        torch.lgamma(inv) + torch.lgamma(deaths + 1) - torch.lgamma(deaths + inv)
        + inv * (log_denom - inv.log()) + deaths * (log_denom - log_mean)
    )


def _rbf(ages: tuple[int, ...], enabled: bool) -> Tensor:
    if not enabled:
        return torch.eye(len(ages))
    age = torch.tensor(ages, dtype=torch.float32)
    centers = torch.tensor([5, 14, 25, 40, 55, 70, 83, 95])
    rbf = torch.exp(-0.5 * ((age[:, None] - centers) / 9.0) ** 2)
    return torch.column_stack((torch.ones_like(age), (age == 0).float(), rbf))


def _prior(ages: tuple[int, ...]) -> Tensor:
    age = torch.tensor(ages, dtype=torch.float32)
    # Broad initialization permits declining mortality in infancy and childhood.
    rate = 0.00015 + 0.018 * torch.exp(-age / 1.5) + 0.001 * torch.exp((age - 35) / 11)
    return rate.log()


class MortalityModel(nn.Module):
    def __init__(self, spec: TrainingSpec, support: Support):
        super().__init__()
        self.spec = spec
        self.support = support
        self.country_index = {country: i + 1 for i, country in enumerate(support.countries)}
        self.register_buffer("basis", _rbf(support.ages, spec.age_basis))
        self.register_buffer("anchor", _prior(support.ages))
        count = self.basis.shape[1]
        self.sex_level = nn.Parameter(torch.randn(2, count) * 0.05)
        self.country_level = nn.Embedding(len(self.country_index) + 1, 2 * count, padding_idx=0)
        with torch.no_grad():
            self.country_level.weight[1:].normal_(std=0.03)
        self.trend = nn.Parameter(torch.randn(2, count) * 0.015 - 0.05)
        self.shock_level = nn.Parameter(torch.zeros(2, count))
        self.dispersion = nn.Parameter(torch.full((len(support.ages),), -5.0))
        if spec.family == "structured":
            self.period = nn.Sequential(nn.Linear(1, 12), nn.Tanh(), nn.Linear(12, count))
        else:
            self.state = nn.Parameter(torch.randn(4) * 0.1)
            self.innovations = nn.Parameter(torch.zeros(support.origin - support.first, 4))
            self.transition = nn.Sequential(nn.Linear(4, 10), nn.Tanh(), nn.Linear(10, 4))
            self.loadings = nn.Parameter(torch.randn(4, count) * 0.12)

    def _time(self, years: Tensor) -> Tensor:
        time = (years - self.support.origin).float() / 10
        if not self.spec.dynamics:
            return torch.zeros((len(years), self.basis.shape[1]), device=self.basis.device)
        if self.spec.family == "structured":
            endpoint = self.period(torch.zeros((1, 1), device=self.basis.device))
            bounded = self.period(time.clamp(max=0)[:, None]) - endpoint
            return bounded
        path = [self.state]
        for i in range(self.support.first + 1, int(years.max()) + 1):
            previous = path[-1]
            predicted = 0.94 * previous + 0.06 * self.transition(previous).tanh()
            if i <= self.support.origin:
                predicted = predicted + 0.15 * self.innovations[i - self.support.first - 1].tanh()
            path.append(predicted)
        return torch.stack(path)[years - self.support.first] @ self.loadings

    def forward(self, groups: tuple[Population, ...], years: Tensor) -> Tensor:
        if len(groups) == 0 or not self.support.first <= int(years.min()) <= int(years.max()) <= self.support.origin + 50:
            raise ValueError("unsupported prediction calendar or populations")
        if any(group.sex not in {"female", "male"} for group in groups):
            raise ValueError("model supports published female and male strata")
        device = self.basis.device
        sex = torch.tensor([int(group.sex == "male") for group in groups], device=device)
        country = torch.tensor([self.country_index.get(group.country, 0) for group in groups], device=device)
        local = self.country_level(country).reshape(len(groups), 2, -1)
        local = local[torch.arange(len(groups), device=device), sex] if self.spec.hierarchy else 0.0
        intercept = self.sex_level[sex] + local
        time = (years - self.support.origin).float() / 10
        linear = time[None, :, None] * self.trend[sex, None, :]
        temporal = self._time(years)
        shock = ((years >= 2020) & (years <= 2021) & (years <= self.support.origin)).float()
        event = shock[None, :, None] * self.shock_level[sex, None, :] if self.spec.shock else 0.0
        coefficients = intercept[:, None, :] + linear + temporal[None, :, :] + event
        return self.anchor + coefficients @ self.basis.T

    def regularizer(self) -> Tensor:
        penalty = 0.02 * self.country_level.weight.square().mean() + 0.015 * self.trend.square().mean()
        penalty = penalty + 0.025 * self.shock_level.square().mean()
        if self.spec.family == "state_space":
            penalty = penalty + 0.04 * self.innovations.square().mean()
        else:
            penalty = penalty + 0.002 * self.period[0].weight.square().mean()
        return penalty

    def support_status(self, target: Population) -> str:
        if target in self.support.groups:
            return "training_population"
        if target.country in self.country_index:
            return "unseen_country_sex_pair"
        return "unseen_country_same_sex_pool"


def _torch_inputs(train: Cube) -> tuple[Tensor, Tensor, Tensor]:
    deaths = torch.tensor(train.deaths, dtype=torch.float32)
    exposures = torch.tensor(train.exposure, dtype=torch.float32)
    years = torch.tensor(train.years)
    return deaths, exposures, years


def _weighted_loss(model: MortalityModel, log_rate: Tensor, d: Tensor, e: Tensor) -> Tensor:
    if model.spec.likelihood == "negative_binomial":
        loss = nb_loss(log_rate, d, e, nn.functional.softplus(model.dispersion) + 1e-5)
    else:
        loss = poisson_loss(log_rate, d, e)
    return (loss.sum(dim=(1, 2)) / d.sum(dim=(1, 2)).clamp(min=1)).mean()


def _forecast(model: MortalityModel, groups: tuple[Population, ...], years: tuple[int, ...]) -> Float:
    model.eval()
    with torch.inference_mode():
        values = model(groups, torch.tensor(years)).numpy().astype(np.float64)
    if not np.isfinite(values).all() or np.max(np.abs(values)) > 30:
        raise ValueError("forecast lies outside the bounded log-rate domain")
    return values


def atomic_save(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            torch.save(content, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def fit(train: Cube, spec: TrainingSpec, checkpoint: Path, data_sha256: str) -> dict:
    if len(train.years) < 12 or len(train.groups) < 2:
        raise ValueError("training requires at least 12 years and two strata")
    torch.manual_seed(spec.seed)
    torch.set_num_threads(2)
    model = MortalityModel(spec, Support.from_cube(train))
    d, e, years = _torch_inputs(train)
    optimizer = torch.optim.AdamW(model.parameters(), lr=spec.learning_rate, weight_decay=0.001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=spec.steps, eta_min=0.004)
    initial = {name: value.detach().clone() for name, value in model.named_parameters()}
    first = None
    trace = []
    max_gradient = 0.0
    for step in range(spec.steps):
        optimizer.zero_grad(set_to_none=True)
        log_rate = model(train.groups, years)
        loss = _weighted_loss(model, log_rate, d, e)
        if not torch.isfinite(loss):
            raise ArithmeticError(f"nonfinite objective at step {step}")
        if first is None:
            first = float(loss.detach())
        (loss + model.regularizer()).backward()
        gradient = nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0, error_if_nonfinite=True)
        max_gradient = max(max_gradient, float(gradient))
        optimizer.step()
        scheduler.step()
        if step == 0 or (step + 1) % 20 == 0 or step + 1 == spec.steps:
            trace.append({"step": step + 1, "objective_before_update": float(loss.detach())})
    with torch.inference_mode():
        fitted = model(train.groups, years)
        final = float(_weighted_loss(model, fitted, d, e))
        delta = float(sum((value - initial[name]).square().sum() for name, value in model.named_parameters()).sqrt())
    diagnostics = {
        "initial_objective": first, "final_objective": final, "max_gradient": max_gradient,
        "parameter_l2_change": delta, "trace": trace,
    }
    if first is None or not final < first or not delta > 0 or not max_gradient > 0:
        raise ArithmeticError("learned model did not improve over initialization")
    atomic_save(checkpoint, {
        "schema": 1, "spec": asdict(spec), "support": asdict(model.support),
        "model": model.state_dict(), "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(), "rng": torch.random.get_rng_state(),
        "completed_steps": spec.steps, "sampler": "deterministic-full-batch",
        "dataset_sha256": data_sha256, "training_diagnostics": diagnostics,
        "initial_parameters": initial,
    })
    return diagnostics


def load(checkpoint: Path, data_sha256: str) -> MortalityModel:
    if checkpoint.stat().st_size > 5_000_000:
        raise ValueError("checkpoint exceeds the serving size limit")
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if payload.get("schema") != 1 or payload.get("dataset_sha256") != data_sha256:
        raise ValueError("checkpoint schema or dataset identity mismatch")
    spec = TrainingSpec(**payload["spec"])
    if payload.get("completed_steps") != spec.steps:
        raise ValueError("checkpoint step count contradicts the training spec")
    metadata = dict(payload["support"])
    metadata["groups"] = tuple(Population(**group) for group in metadata["groups"])
    support = Support(**metadata)
    model = MortalityModel(spec, support)
    model.load_state_dict(payload["model"], strict=True)
    return model.eval()


def predict(model: MortalityModel, groups: tuple[Population, ...], years: tuple[int, ...]) -> Float:
    if not 1 <= len(groups) <= 200 or not 1 <= len(years) <= 150:
        raise ValueError("prediction batch exceeds supported shape")
    return _forecast(model, groups, years)
