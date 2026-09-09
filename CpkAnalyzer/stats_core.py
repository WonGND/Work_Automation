"""Cp/Cpk 공정능력 통계 계산."""

import numpy as np
from scipy import stats


class CapabilityResult:
    """공정능력 분석 결과를 계산하고 보관한다."""

    def __init__(self, data, lsl, usl):
        values = np.asarray(data, dtype=float)
        self.data = values[np.isfinite(values)]
        self.lsl = lsl
        self.usl = usl
        self._compute()

    def _compute(self):
        data = self.data
        self.n = len(data)
        if self.n < 2:
            raise ValueError("분석을 위해 최소 2개 이상의 데이터가 필요합니다.")

        self.mean = float(np.mean(data))
        self.std = float(np.std(data, ddof=1))
        if self.std <= 0:
            raise ValueError("표준편차가 0입니다. 데이터 값이 모두 동일합니다.")

        self.cp = (self.usl - self.lsl) / (6.0 * self.std)
        cpu = (self.usl - self.mean) / (3.0 * self.std)
        cpl = (self.mean - self.lsl) / (3.0 * self.std)
        self.cpk = min(cpu, cpl)

        p_below = stats.norm.cdf(self.lsl, self.mean, self.std)
        p_above = 1.0 - stats.norm.cdf(self.usl, self.mean, self.std)
        self.ppm = (p_below + p_above) * 1_000_000
