from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from imap_tools import MailMessage

from finn.config import PROJEKT_ROOT, lade_config
from finn.dienste import OfflineDienste

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg(tmp_path):
    return replace(lade_config(), vertraege_dir=PROJEKT_ROOT / "data" / "vertraege",
                   cache_dir=tmp_path / "cache")


@pytest.fixture
def offline():
    return OfflineDienste(FIXTURES / "referenz")


@pytest.fixture
def auftrag() -> MailMessage:
    return MailMessage.from_bytes((FIXTURES / "auftrag.eml").read_bytes())


@pytest.fixture
def plan_bytes() -> bytes:
    return (PROJEKT_ROOT / "data" / "Wirtschaftsplan_2027.xlsx").read_bytes()


def D(x) -> Decimal:
    return Decimal(str(x))
