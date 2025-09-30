from abc import ABC, abstractmethod
from typing import Any

from .models import ProviderPricing, UsageMetrics


class UsageExtractor(ABC):
    @abstractmethod
    def extract_usage(self, response: Any) -> UsageMetrics:
        pass


class PricingCalculator(ABC):
    @abstractmethod
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        pass
